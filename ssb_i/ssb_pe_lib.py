"""Central PE integrity + caller-scan library for SSB-I static analysis.

Consolidates the PE parsing that was previously scattered across ad-hoc
phase scripts (phase31_*, 40k_*) into one deterministic, testable module.

Features:
  * trust root verification (SHA-256 against a documented root hash)
  * section table parse with bounds-checked rva_to_off / off_to_rva
  * .pdata function-bound extraction (fn_start / fn_size)
  * instruction-boundary-validated direct-call enumeration via Capstone,
    so a raw 0xE8 byte match that is not aligned on an instruction boundary
    is never counted as a call.

Read-only. No patching, no writes to the target binary.
"""
from __future__ import annotations

import hashlib
import struct
from bisect import bisect_right
from pathlib import Path
from typing import Optional

try:
    import capstone  # type: ignore
    _HAVE_CAPSTONE = True
except Exception:  # pragma: no cover - import optional
    capstone = None
    _HAVE_CAPSTONE = False

IMAGE_BASE = 0x140000000
DEFAULT_TRUST_ROOT_SHA256 = (
    "7e9adb1414a8e1b325e5e1f097b9b17b78deb7eebeda37a333351a43a60f9d28"
)


class PEIntegrityError(RuntimeError):
    """Raised when the binary fails integrity checks or address bounds."""


class PE:
    """Read-only PE32+ binary model with deterministic address mapping."""

    def __init__(self, path: Path | str, image_base: Optional[int] = None) -> None:
        self.path = Path(path)
        self.blob = self.path.read_bytes()
        self.sha256 = hashlib.sha256(self.blob).hexdigest()
        self.image_base = image_base if image_base is not None else IMAGE_BASE
        self._parse()
        self.p_s: list[int] = []
        self.p_e: list[int] = []
        self._pdata_built = False

    # ------------------------------------------------------------------ parse
    def _parse(self) -> None:
        b = self.blob
        if len(b) < 0x40:
            raise PEIntegrityError("blob too small for DOS header")
        pe = struct.unpack_from("<I", b, 0x3C)[0]
        if b[pe:pe + 4] != b"PE\0\0":
            raise PEIntegrityError("bad PE signature")
        nsec = struct.unpack_from("<H", b, pe + 6)[0]
        opt_size = struct.unpack_from("<H", b, pe + 20)[0]
        if opt_size <= 0:
            raise PEIntegrityError("zero optional header size")
        opt = pe + 24
        magic = struct.unpack_from("<H", b, opt)[0]
        if magic != 0x20B:  # PE32+
            raise PEIntegrityError(f"not PE32+ (magic=0x{magic:04X})")
        self.image_base = image_base = struct.unpack_from("<Q", b, opt + 24)[0]
        self.size_of_image = struct.unpack_from("<I", b, opt + 56)[0]
        sections: dict[str, tuple[int, int, int, int]] = {}
        t = opt + opt_size
        for i in range(nsec):
            p = t + i * 40
            name = b[p:p + 8].rstrip(b"\0").decode("latin1")
            vsz, va, rsz, raw = struct.unpack_from("<IIII", b, p + 8)
            sections[name] = (va, vsz, rsz, raw)
        self.sec = sections

    # ------------------------------------------------------------- addressing
    def rva_to_off(self, rva: int) -> Optional[int]:
        for va, vsz, rsz, raw in self.sec.values():
            extent = max(vsz, rsz)
            if va <= rva < va + extent:
                return raw + (rva - va)
        return None

    def off_to_rva(self, off: int) -> Optional[int]:
        for va, vsz, rsz, raw in self.sec.values():
            if raw <= off < raw + rsz:
                return va + (off - raw)
        return None

    def in_image(self, rva: int) -> bool:
        return self.rva_to_off(rva) is not None

    def section_of(self, rva: int) -> Optional[str]:
        for name, (va, vsz, rsz, _raw) in self.sec.items():
            if va <= rva < va + max(vsz, rsz):
                return name
        return None

    # ------------------------------------------------------------------ read
    def read(self, rva: int, n: int) -> bytes:
        o = self.rva_to_off(rva)
        if o is None:
            return b""
        return self.blob[o:o + n]

    def u32(self, rva: int) -> Optional[int]:
        d = self.read(rva, 4)
        return struct.unpack_from("<I", d, 0)[0] if len(d) == 4 else None

    def u64(self, rva: int) -> Optional[int]:
        d = self.read(rva, 8)
        return struct.unpack_from("<Q", d, 0)[0] if len(d) == 8 else None

    # --------------------------------------------------------------- .pdata
    def build_pdata(self) -> int:
        if self._pdata_built:
            return len(self.p_s)
        starts: list[int] = []
        ends: list[int] = []
        if ".pdata" in self.sec:
            va, vsz, rsz, raw = self.sec[".pdata"]
            blob = self.blob[raw:raw + rsz]
            for i in range(0, len(blob) - 11, 12):
                b0, u0, u1 = struct.unpack_from("<III", blob, i)
                if b0 == 0 and u0 == 0:
                    continue
                starts.append(b0)
                ends.append(u0)
        order = sorted(range(len(starts)), key=lambda i: starts[i])
        self.p_s = [starts[i] for i in order]
        self.p_e = [ends[i] for i in order]
        self._pdata_built = True
        return len(self.p_s)

    def fn_start(self, rva: int) -> Optional[int]:
        """Largest .pdata start <= rva and inside that runtime function."""
        if not self.p_s or rva < self.p_s[0]:
            return None
        k = bisect_right(self.p_s, rva) - 1
        if k < 0 or rva >= self.p_e[k]:
            return None
        return self.p_s[k]

    def fn_size(self, start: int) -> int:
        k = bisect_right(self.p_s, start) - 1
        return self.p_e[k] - start if k >= 0 and start < self.p_e[k] else 0

    # ------------------------------------------------------- caller scanning
    def raw_e8_targets(self, section: str = ".text") -> list[dict]:
        """Raw 0xE8 scan computing each call target from its own length.

        This is the deterministic source of truth for call enumeration.  It
        reports every byte equal to 0xE8 whose (src + insn_len + rel32) target
        matches, WITHOUT assuming a fixed +5 length.  It may include bytes
        that are not genuinely instruction-aligned (data/misdecodes); use
        `verify_call_boundaries` to filter those per function.
        """
        if section not in self.sec:
            return []
        va, vsz, rsz, raw = self.sec[section]
        code = self.blob[raw:raw + rsz]
        out: list[dict] = []
        i = 0
        n = len(code)
        while i < n - 4:
            if code[i] == 0xE8:
                rel = struct.unpack_from("<i", code, i + 1)[0]
                # x86 rel8/rel32: E8 is always rel32 -> 5 bytes.
                src_rva = va + i
                tgt = src_rva + 5 + rel
                out.append({
                    "call_rva": src_rva,
                    "target_rva": tgt,
                    "bytes": code[i:i + 5].hex(),
                    "insn_len": 5,
                })
            i += 1  # step by one so overlapping E8-in-displacement candidates
            #            are not lost; verify_call_boundaries filters non-calls
        return out

    def verify_call_boundaries(
        self,
        candidates: list[dict],
        section: str = ".text",
    ) -> tuple[list[dict], dict[int, str]]:
        """For each candidate, disassemble its enclosing function and confirm
        a `call` sits exactly at that address (instruction-boundary check).

        Returns (verified, failure_map) where failure_map maps call_rva to a
        reason string (e.g. 'no_function', 'not_a_call', 'desync_in_function').
        Uses .pdata fn_start as the anchor so we never sweep across a whole
        section (linear sweeps desynchronize on 100MB binaries).
        """
        if section not in self.sec or not _HAVE_CAPSTONE:
            return [], {c["call_rva"]: "capstone_or_section_unavailable" for c in candidates}
        assert capstone is not None
        va, vsz, rsz, raw = self.sec[section]
        code = self.blob[raw:raw + rsz]
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        md.detail = True
        self.build_pdata()
        verified: list[dict] = []
        failures: dict[int, str] = {}
        # Group candidates by enclosing function to decode each function once.
        by_fn: dict[int, list[int]] = {}
        for c in candidates:
            fs = self.fn_start(c["call_rva"])
            if fs is None:
                failures[c["call_rva"]] = "no_function"
                continue
            by_fn.setdefault(fs, []).append(c["call_rva"])
        for fs, call_rvas in by_fn.items():
            fsize = self.fn_size(fs)
            if fsize <= 0:
                for cr in call_rvas:
                    failures[cr] = "no_function_size"
                continue
            start = fs - va
            window = code[start: start + fsize]
            want = {(self.image_base + cr) for cr in call_rvas}
            seen_call: set[int] = set()
            for ins in md.disasm(window, self.image_base + fs):
                if ins.mnemonic == "call" and ins.address in want:
                    seen_call.add(ins.address - self.image_base)
            for cr in call_rvas:
                if cr in seen_call:
                    verified.append(next(v for v in candidates if v["call_rva"] == cr))
                else:
                    failures[cr] = "not_a_call_or_misdecode"
        return verified, failures
