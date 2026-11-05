"""VTable indirekter Aufruf Regression (SSB-I static, Punkt C)."""
from __future__ import annotations

from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from ssb_i.ssb_pe_lib import PE  # noqa: E402

BIN = Path("/home/cole/Developer/seneca-ghidra/input/Starfield.original.exe")


@pytest.fixture(scope="module")
def pe() -> PE:
    if not BIN.exists():
        pytest.skip(f"Trust-root binary not present: {BIN}")
    p = PE(BIN)
    p.build_pdata()
    return p


# VTable indirekter Aufruf (Punkt C)
def test_vtable_call_0922ac3_bytes(pe: PE) -> None:
    """RVA 0x0922AC3 holds `FF 92 30 02 00 00` = call qword ptr [rdx+0x230].
    Register: RDX loaded from [RAX]; object type & callee are UNKNOWN.
    NOT linked to 0x2116840 -- no dataflow edge is asserted."""
    off = pe.rva_to_off(0x0922AC3)
    assert off is not None
    raw = pe.blob[off:off + 6]
    assert raw.hex() == "ff9230020000"


def test_vtable_0922ab8_not_e8(pe: PE) -> None:
    """RVA 0x0922AB8 byte is 0x48 (start of `48 85 C0` test rax,rax),
    NOT an E8 call as a prior claim repeated. Real call sits at 0x0922AB3."""
    off = pe.rva_to_off(0x0922AB8)
    assert pe.blob[off] == 0x48
    off3 = pe.rva_to_off(0x0922AB3)
    assert pe.blob[off3] == 0xE8


def test_vtable_objettype_unknown(pe: PE) -> None:
    """Only the instruction bytes are PROVEN. No RTTI/constructor/vtable-
    assignment inside the enclosing function asserts an object type, so any
    object-type or callee claim stays UNKNOWN. Pin the enclosing fn exists."""
    fs = pe.fn_start(0x0922AC3)
    assert fs is not None
    assert pe.read(0x0922AC3, 1) == b"\xff"
