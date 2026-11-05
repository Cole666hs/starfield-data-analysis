"""Tests for the UI page registry (product boundary).

Prüft, dass die Oberfläche keine Attrappen mehr enthält und dass die
Hex-Ansicht mit der Analyzer-Seite verdrahtet ist. Läuft kopflos (offscreen),
braucht keine Savegame-Datei.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("PySide6", reason="PySide6 nur im Build-venv vorhanden")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def app_module(app):
    import ssb_ui.app as module
    return module


def test_placeholder_classes_are_gone(app_module):
    for name in ("PluginPage", "DeployPage", "RuntimePage"):
        assert not hasattr(app_module, name), f"{name} existiert noch"


def test_page_list_has_no_placeholder(app_module):
    labels = [label for label, _pid, _widget in app_module.SSBWorkbench.build_pages()]
    joined = " ".join(labels).lower()
    for removed in ("plugin config", "dll deploy", "runtime capture"):
        assert removed not in joined
    assert any("savegame" in l.lower() for l in labels)
    assert any("hex" in l.lower() for l in labels)


def test_hex_page_is_wired_to_analyzer(app_module):
    pages = app_module.SSBWorkbench.build_pages()
    savegame = pages[0][2]
    hexpage = pages[1][2]
    assert type(savegame).__name__ == "SavegamePage"
    assert type(hexpage).__name__ == "HexViewPage"
    # Die Hex-Ansicht fragt die Analyzer-Seite nach dem Puffer
    assert hexpage._buffer_getter is not None
    assert hexpage.load_from_source(interactive=False) is False  # noch kein Save
    savegame._inner = type("Fake", (), {"current_buffer": lambda self: ("fake.sfs", b"ABCD")})()
    assert hexpage.load_from_source(interactive=False) is True
    assert "ABCD" in hexpage.view.toPlainText()


def test_sidebar_and_stack_stay_in_sync(app_module):
    win = app_module.SSBWorkbench()
    assert win.sidebar.count() == win.pages.count()
    for row in range(win.sidebar.count()):
        win.sidebar.setCurrentRow(row)
        assert win.pages.currentIndex() == row


def test_version_in_title(app_module):
    win = app_module.SSBWorkbench()
    assert app_module.PRODUCT_VERSION in win.windowTitle()


def _synthetic_save(tmp_path):
    """Baut ein gültiges Savegame über die Helfer des CLI-Tests."""
    import importlib.util
    path = Path(__file__).with_name("test_ssb_i_cli.py")
    spec = importlib.util.spec_from_file_location("_ssb_cli_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    save = tmp_path / "synthetic.sfs"
    save.write_bytes(module.SYNTH.build_synthetic_sfs(module.dat_header()))
    return save


def test_self_test_writes_report_file(app_module, app, tmp_path):
    """Windows-Build hat kein stdout — der Selbsttest muss eine Datei schreiben."""
    save = _synthetic_save(tmp_path)
    out = tmp_path / "selftest.txt"
    code = app_module.self_test(str(save), str(out))
    assert out.exists(), "Reportdatei wurde nicht geschrieben"
    text = out.read_text(encoding="utf-8")
    assert "SELF_TEST" in text
    # Synthetisches Save hat keine lesbare Plugin-Liste -> FAIL (fail-closed)
    assert code == 1
    assert "FAIL" in text


def test_self_test_without_report_still_returns_code(app_module, app, tmp_path):
    save = _synthetic_save(tmp_path)
    broken = tmp_path / "broken.sfs"
    broken.write_bytes(b"kein savegame")
    assert app_module.self_test(str(broken)) == 1

# --- Produktgrenze und Identitaet (Release-Gate 05.11.2026) ----------------
def test_exactly_three_pages(app_module):
    """Es gibt genau drei Seiten, jede mit echtem Zweck."""
    assert len(app_module.SSBWorkbench.build_pages()) == 3


def test_no_aisc_page_in_product(app_module):
    labels = [label.lower() for label, _id, _w in app_module.SSBWorkbench.build_pages()]
    assert not any("aisc" in l for l in labels), labels
    assert not any("3d" in l for l in labels), labels


def test_aisc_module_is_not_shipped():
    """Das AISC-Modul existiert in diesem Produkt nicht mehr."""
    import importlib.util
    assert importlib.util.find_spec("ssb_ui.pages.aisc_preview_page") is None


def test_public_identity_is_consistent(app_module):
    from ssb_i.product import DEVELOPER, PRODUCT_NAME, PRODUCT_SUBTITLE, VERSION
    assert PRODUCT_NAME == "Starfield Data Analysis"
    assert PRODUCT_SUBTITLE == "Advanced Starfield Inspection & Analysis Toolkit"
    assert DEVELOPER == "Entropy Development"
    assert VERSION == "1.0.0"
    assert app_module.APP_NAME == PRODUCT_NAME
    assert VERSION in app_module.SSBWorkbench().windowTitle()


def test_no_internal_product_name_in_ui_text(app_module):
    """'SSB-I' darf nicht mehr in Benutzertexten auftauchen."""
    win = app_module.SSBWorkbench()
    texts = [win.windowTitle(), win.statusbar.currentMessage()]
    texts += [win.sidebar.item(i).text() for i in range(win.sidebar.count())]
    log = win.pages.widget(2)
    texts.append(log.toPlainText())
    joined = " ".join(texts)
    assert "SSB-I" not in joined
    assert "ssb-i" not in joined


def test_dump_pages_writes_report(app_module, app, tmp_path):
    """Abnahme im Paket: Seitenliste ohne Fenster ausgeben."""
    out = tmp_path / "pages.txt"
    assert app_module.dump_pages(str(out)) == 0
    text = out.read_text(encoding="utf-8")
    assert "pages: 3" in text
    assert "Savegame Analyzer" in text and "Hex Viewer" in text
    assert "aisc" not in text.lower()
