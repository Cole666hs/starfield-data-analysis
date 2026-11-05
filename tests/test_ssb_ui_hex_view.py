"""Tests für die Hex-Ansicht (``ssb_ui/pages/hex_view_page.py``).

Die Seite ist read-only und arbeitet auf einem übergebenen Puffer — damit ist
sie ohne Savegame und ohne laufendes Spiel testbar. Geprüft werden Rendering,
Seitenweise-Blättern, Offset-Sprung, Suche und die Grenzfälle (leerer Puffer,
Muster nicht gefunden).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("PySide6", reason="PySide6 nur im Build-venv vorhanden")

from PySide6.QtWidgets import QApplication  # noqa: E402

from ssb_ui.pages.hex_view_page import (  # noqa: E402
    PAGE_BYTES, HexViewPage, format_rows, parse_pattern,
)


# ------------------------------------------------------------------ reine Logik
def test_parse_pattern_hex_with_spaces():
    assert parse_pattern("4E 50 43") == b"NPC"


def test_parse_pattern_hex_with_colons():
    # 0x63 ist das kleine 'c' — Hex ist byteweise, nicht textweise
    assert parse_pattern("4e:50:63") == b"NPc"


def test_parse_pattern_text():
    assert parse_pattern("SOC_") == b"SOC_"


def test_format_rows_offsets_and_ascii():
    text = format_rows(b"ABCD" + b"\x00\x01" + b"xyz", base_offset=0x100)
    line = text.splitlines()[0]
    assert line.startswith("00000100")
    assert "41 42 43 44 00 01 78 79 7A" in line
    assert line.endswith("|ABCD..xyz|")


def test_format_rows_dots_for_non_printable():
    text = format_rows(b"\x00\xff", base_offset=0)
    assert "|..|" in text


# ----------------------------------------------------------------------- Seite
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(app):
    return HexViewPage()


def test_empty_page_reports_empty(page):
    assert page.status_text() == "empty"
    assert page.view.toPlainText() == ""


def test_set_buffer_renders_first_line(page):
    page.set_buffer(b"SFS_SAVEGAME" + bytes(3), "synthetisch")
    lines = page.view.toPlainText().splitlines()
    assert lines[0].startswith("00000000")
    # Nicht druckbare Bytes werden als '.' gezeigt
    assert "|SFS_SAVEGAME...|" in lines[0]
    assert "15 bytes" in page.info_label.text()


def test_goto_offset_pages_forward(page):
    # Puffer muss deutlich größer als ein Fenster sein, sonst klemmt die Grenze
    data = bytes(range(256)) * ((PAGE_BYTES // 256) * 3)
    page.set_buffer(data, "gross")
    page.goto_offset(PAGE_BYTES)
    assert page._offset == PAGE_BYTES
    assert page.view.toPlainText().splitlines()[0].startswith(f"{PAGE_BYTES:08X}")


def test_goto_offset_is_clamped(page):
    page.set_buffer(b"x" * 100, "klein")
    page.goto_offset(-50)
    assert page._offset == 0
    page.goto_offset(10_000)          # hinter dem Ende
    assert page._offset >= 0


def test_find_next_text_pattern(page):
    # Puffer groß genug, dass der Sprung NICHT an der Fenstergrenze klemmt
    payload = b"\x00" * PAGE_BYTES + b"NEEDLE" + b"\x00" * (PAGE_BYTES * 2)
    page.set_buffer(payload, "suche")
    assert page.find_next(b"NEEDLE") == PAGE_BYTES
    assert page._offset == PAGE_BYTES


def test_find_next_hex_pattern(page):
    payload = b"\x00" * PAGE_BYTES + bytes.fromhex("4E5043") + b"\x00" * 8
    page.set_buffer(payload, "suche")
    assert page.find_next(parse_pattern("4E 50 43")) == PAGE_BYTES


def test_find_next_missing_returns_none(page):
    page.set_buffer(b"abcdef", "suche")
    assert page.find_next(b"zzz") is None


def test_find_next_wraps_to_beginning(page):
    payload = b"HEAD" + b"\x00" * (PAGE_BYTES * 2)
    page.set_buffer(payload, "wrap")
    page.goto_offset(PAGE_BYTES)
    assert page.find_next(b"HEAD") == 0
    assert page._offset == 0


def test_buffer_getter_is_used(page, app):
    page2 = HexViewPage(buffer_getter=lambda: ("aus-analyzer", b"SFS_SAVEGAME"))
    assert page2.load_from_source(interactive=False) is True
    assert page2._data.startswith(b"SFS_SAVEGAME")
    assert "aus-analyzer" in page2.info_label.text()


def test_load_from_source_without_data_is_silent(app):
    """Ohne Puffer darf der automatische Aufruf KEINEN Dialog öffnen."""
    page = HexViewPage(buffer_getter=lambda: (None, b""))
    assert page.load_from_source(interactive=False) is False
    assert page.status_text() == "empty"


def test_load_from_source_without_source_is_silent(app):
    page = HexViewPage(buffer_getter=None)
    assert page.load_from_source(interactive=False) is False
