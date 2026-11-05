"""Regression tests for SSB-I static PE integrity (ssb_pe_lib)."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from ssb_i.ssb_pe_lib import PE, PEIntegrityError, DEFAULT_TRUST_ROOT_SHA256  # noqa: E402,F401

try:  # optional dependency: only the call-boundary check needs a disassembler
    import capstone  # noqa: F401
    HAS_CAPSTONE = True
except Exception:  # pragma: no cover
    HAS_CAPSTONE = False

needs_capstone = pytest.mark.skipif(
    not HAS_CAPSTONE, reason="capstone not installed (optional; only the call-boundary check needs it)")

#: Reference binary for the integrity tests. Not shipped: point the environment
#: variable at your own copy of the unmodified Starfield executable.
BIN = Path(os.environ.get(
    "STARFIELD_ORIGINAL_EXE",
    "/home/cole/Developer/seneca-ghidra/input/Starfield.original.exe"))


@pytest.fixture(scope="module")
def pe() -> PE:
    if not BIN.exists():
        pytest.skip(f"Trust-root binary not present: {BIN}")
    return PE(BIN)


# -------------------------------------------------------------- trust root
def test_trust_root_sha256(pe: PE) -> None:
    assert pe.sha256 == DEFAULT_TRUST_ROOT_SHA256


def test_trust_root_imagebase(pe: PE) -> None:
    assert pe.image_base == 0x140000000


def test_trust_root_sections(pe: PE) -> None:
    assert ".text" in pe.sec and ".pdata" in pe.sec
    assert pe.size_of_image > 0x8000000


# ------------------------------------------------------ address round-trips
def test_rva_offset_roundtrip_2116840(pe: PE) -> None:
    off = pe.rva_to_off(0x2116840)
    assert off is not None
    assert pe.off_to_rva(off) == 0x2116840
    assert pe.section_of(0x2116840) == ".text"


def test_rva_offset_roundtrip_365d408(pe: PE) -> None:
    off = pe.rva_to_off(0x365D408)
    assert off is not None
    assert pe.off_to_rva(off) == 0x365D408


def test_addendum_cited_offsets_are_wrong(pe: PE) -> None:
    """The 2026-10-18 addendum cited File-Off 0x0211A4BC for RVA 0x2116840
    and 0x03661084 for RVA 0x365D408. Those are accounting errors: they
    resolve to RVA 0x0211AEBC / 0x03661A84 instead."""
    assert pe.off_to_rva(0x0211A4BC) == 0x0211AEBC
    assert pe.off_to_rva(0x03661084) == 0x03661A84
    assert pe.rva_to_off(0x2116840) == 0x02115E40
    assert pe.rva_to_off(0x365D408) == 0x0365CA08


def test_out_of_range_rva_rejected(pe: PE) -> None:
    assert pe.rva_to_off(0x8FFF_FFFF) is None
    assert pe.in_image(0x8FFF_FFFF) is False
    assert pe.section_of(0x8FFF_FFFF) is None


# -------------------------------------------------------------------- pdata
def test_pdata_fn_start_2116840(pe: PE) -> None:
    pe.build_pdata()
    assert pe.fn_start(0x2116840) == 0x2116840


def test_pdata_fn_start_0922a90(pe: PE) -> None:
    pe.build_pdata()
    assert pe.fn_start(0x0922A90) == 0x0922A90


# ------------------------------------------------------------- call targets
def test_call_13f0bf9_targets_2116840(pe: PE) -> None:
    """Direct call at RVA 0x13F0BF9 (E8 42 5C D2 00) targets 0x2116840."""
    off = pe.rva_to_off(0x13F0BF9)
    assert pe.blob[off] == 0xE8
    import struct
    rel = struct.unpack_from("<i", pe.blob, off + 1)[0]
    assert (0x13F0BF9 + 5 + rel) == 0x2116840


def test_call_0919f50_does_not_target_2116840(pe: PE) -> None:
    """Direct call at RVA 0x0919F50 (E8 AB 52 01 00) targets 0x0092F200,
    NOT 0x2116840. The earlier report mis-labelled it as an editor caller."""
    off = pe.rva_to_off(0x0919F50)
    assert pe.blob[off] == 0xE8
    import struct
    rel = struct.unpack_from("<i", pe.blob, off + 1)[0]
    assert (0x0919F50 + 5 + rel) == 0x0092F200


def test_call_0922ab3_inside_image(pe: PE) -> None:
    """The call near 0x0922AB8 is at RVA 0x0922AB3, target 0x005DE3B0,
    inside .text -- NOT outside the image as a prior claim suggested."""
    import struct
    off = pe.rva_to_off(0x0922AB3)
    assert pe.blob[off] == 0xE8
    rel = struct.unpack_from("<i", pe.blob, off + 1)[0]
    tgt = 0x0922AB3 + 5 + rel
    assert tgt == 0x005DE3B0
    assert pe.in_image(tgt)
    assert pe.section_of(tgt) == ".text"


# ------------------------------------------------- caller count (boundary)
@needs_capstone
def test_671_callers_boundary_validated(pe: PE) -> None:
    cand = [h for h in pe.raw_e8_targets() if h["target_rva"] == 0x2116840]
    verified, failures = pe.verify_call_boundaries(cand)
    assert len(verified) == 671
    assert len(failures) == 0
    # known real caller present, known non-caller absent
    ver = {h["call_rva"] for h in verified}
    assert 0x13F0BF9 in ver
    assert 0x0919F50 not in ver


def test_linear_sweep_is_unreliable(pe: PE) -> None:
    """Regression: a naive step-by-5 scan yields 669 (drops 2 overlapping-E8
    candidates) and a fresh whole-section linear Capstone sweep yields 0.
    The module must step by 1 and then boundary-verify, giving 671."""
    cand = [h for h in pe.raw_e8_targets() if h["target_rva"] == 0x2116840]
    assert len(cand) == 671  # step-by-1 raw count


@needs_capstone
def test_invalid_target_raises_via_boundaries(pe: PE) -> None:
    # a call_rva outside any function must be flagged (no_function), not crash
    cand = [{"call_rva": 0x8FFF_FFFF, "target_rva": 0x2116840, "bytes": "00", "insn_len": 5}]
    verified, failures = pe.verify_call_boundaries(cand)
    assert verified == []
    assert 0x8FFF_FFFF in failures