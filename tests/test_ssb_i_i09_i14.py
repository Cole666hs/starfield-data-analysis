"""I-09 (headerSize) und I-14 (Sequenzkonsistenz): Absicherung mit Falsifikation.

I-09 war bis 1.5.3 statisch UNKNOWN. Die Beziehung
``headerSize == padding_end - 16`` ist an sechs realen Saves belegt; hier wird
sie gegen synthetische Header mit **unabhängig variierenden** Längen für Name,
Ort, Rasse und Spielzeit geprüft — plus Negativfälle, in denen kein PASS
entstehen darf.

I-14 war implementiert, wurde aber über die CLI nie ausgeführt, weil
``cmd_save_verify`` keine Sequenz übergab. Hier werden Aufruf, Sortierung und
Grenzfälle abgesichert.
"""
from __future__ import annotations

import dataclasses
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import (build_dat_payload, build_synthetic_sfs, expected_header_size)
from ssb_i.save_integrity import (FAILED, NOT_CHECKED, PASS, WARNING,
                                  check_i09_header_size, check_i14_sequence,
                                  build_context, collect_sequence,
                                  playtime_minutes, run_all)


def _save(tmp_path: Path, name: str = "s.sfs", **kwargs) -> Path:
    path = tmp_path / name
    path.write_bytes(build_synthetic_sfs(build_dat_payload(**kwargs)))
    return path


def _i09(path: Path):
    result = run_all(path).by_id("I-09")
    assert result is not None, "I-09 fehlt im Report"
    return result


# ---------------------------------------------------------------------------
# I-09 — Formel und Feldpositionen
# ---------------------------------------------------------------------------
def test_i09_passes_on_default_synthetic_header(tmp_path):
    result = _i09(_save(tmp_path))
    assert result.status == PASS, result.detail
    assert result.confidence == "deterministic"
    assert result.evidence["expected"] == result.evidence["header_size"]


def test_i09_uses_parser_positions_not_constants(tmp_path):
    """``padding_end`` kommt aus dem Parser, nicht aus einer festen Zahl."""
    path = _save(tmp_path, player_name="EinSehrLangerCharakternameXYZ",
                 player_location="A",
                 playtime="9d.23h.59m.9 Tage.23 Stunden.59 Minuten",
                 race_name="X")
    result = _i09(path)
    assert result.status == PASS, result.detail
    evidence = result.evidence
    assert evidence["padding_end"] != 141          # nicht der Golden-Wert
    assert evidence["header_size"] == evidence["padding_end"] - 16
    assert evidence["header_size"] == evidence["expected"]


# --- Variation je eines Feldes --------------------------------------------
@pytest.mark.parametrize("value", ["", "A", "Ab", "Ein sehr langer Name mit 40 Zeichen XY"])
def test_i09_name_length_variation(tmp_path, value):
    result = _i09(_save(tmp_path, player_name=value))
    assert result.status == PASS, (value, result.detail)


@pytest.mark.parametrize("value", ["", "X", "Jemison - New Atlantis",
                                   "Eine sehr lange Ortsbezeichnung im Sternenfeld 12"])
def test_i09_location_length_variation(tmp_path, value):
    result = _i09(_save(tmp_path, player_location=value))
    assert result.status == PASS, (value, result.detail)


@pytest.mark.parametrize("value", ["", "R", "HumanRace",
                                   "Eine sehr lange Rassenbezeichnung der Kolonie"])
def test_i09_race_length_variation(tmp_path, value):
    result = _i09(_save(tmp_path, race_name=value))
    assert result.status == PASS, (value, result.detail)


@pytest.mark.parametrize("value", ["0d.0h.0m.", "2d.10h.34m.2 Tage.10 Stunden.34 Minuten",
                                   "123d.23h.59m.123 Tage.23 Stunden.59 Minuten"])
def test_i09_playtime_length_variation(tmp_path, value):
    result = _i09(_save(tmp_path, playtime=value))
    assert result.status == PASS, (value, result.detail)


# --- Kombinationen --------------------------------------------------------
@pytest.mark.parametrize("combo", [
    {"player_name": "", "player_location": "", "race_name": "", "playtime": ""},
    {"player_name": "A", "player_location": "B", "race_name": "C", "playtime": "1d.1h.1m."},
    {"player_name": "ABCDEFGHIJ", "player_location": "KLMNOPQRSTUVWXYZ1234567890",
     "race_name": "abcdefghijklmno", "playtime": "99d.19h.49m.99 Tage.19 Stunden.49 Minuten"},
    {"player_name": "Kurz", "player_location": "Ein ziemlich langer Ortsname hier",
     "race_name": "R", "playtime": "5d.5h.5m.5 Tage.5 Stunden.5 Minuten"},
], ids=["leer", "minimal", "lang", "gemischt"])
def test_i09_combined_length_variation(tmp_path, combo):
    """Mehrere Feldlängen gleichzeitig verändert bleiben exakt."""
    result = _i09(_save(tmp_path, **combo))
    assert result.status == PASS, (combo, result.detail)
    evidence = result.evidence
    assert evidence["header_size"] == (
        evidence["padding_end"] - evidence["header_count_start"])


def test_i09_header_size_grows_with_field_lengths(tmp_path):
    """Längere Felder ergeben einen größeren headerSize — 1:1."""
    (tmp_path / "base").mkdir()
    (tmp_path / "long").mkdir()
    base = _i09(_save(tmp_path / "base", "base.sfs"))
    longer = _i09(_save(tmp_path / "long", "long.sfs",
                        player_name="VIERZEICHENMEHR"))
    assert base.status == PASS
    assert longer.status == PASS
    delta = longer.evidence["header_size"] - base.evidence["header_size"]
    assert delta == len("VIERZEICHENMEHR") - len("TestPilot")


# --- Negativfälle: hier darf kein PASS entstehen --------------------------
@pytest.mark.parametrize("offset", [+1, -1, +8, -8])
def test_i09_wrong_header_size_fails(tmp_path, offset):
    name, loc, play, race = "TestPilot", "Jemison - New Atlantis", \
        "1d.2h.3m.1 Tag.2 Stunden.3 Minuten", "HumanRace"
    correct = expected_header_size(name, loc, play, race)
    result = _i09(_save(tmp_path, player_name=name, player_location=loc,
                        playtime=play, race_name=race,
                        header_size_field=correct + offset))
    assert result.status == FAILED, (offset, result.detail)
    assert result.evidence["delta"] == offset


def test_i09_truncated_header_is_not_pass(tmp_path):
    """Abgeschnittenes Padding: Header nicht dekodierbar -> kein PASS."""
    path = _save(tmp_path, truncate_at=0x80)      # mitten im Header
    report = run_all(path)
    i09 = report.by_id("I-09")
    assert i09 is not None
    assert i09.status != PASS
    assert i09.status in (NOT_CHECKED, FAILED)


def test_i09_truncated_padding_is_not_pass(tmp_path):
    """Schnitt genau im Padding-Feld."""
    name, loc, play, race = "TestPilot", "Jemison - New Atlantis", \
        "1d.2h.3m.1 Tag.2 Stunden.3 Minuten", "HumanRace"
    # padding_end liegt bei 16 + headerSize
    cut = 16 + expected_header_size(name, loc, play, race) - 4
    path = _save(tmp_path, player_name=name, player_location=loc,
                 playtime=play, race_name=race, truncate_at=cut)
    i09 = run_all(path).by_id("I-09")
    assert i09 is not None and i09.status != PASS


def test_i09_invalid_string_length_is_not_pass(tmp_path):
    """Unmögliche Stringlänge: Header-Prüfung (I-08) schlägt fehl, I-09 nie PASS."""
    payload = bytearray(build_dat_payload())
    name_len, = struct.unpack_from("<H", payload, 0x19)
    location_length_offset = 0x19 + 2 + name_len + 4
    struct.pack_into("<H", payload, location_length_offset, 4000)
    path = tmp_path / "badlen.sfs"
    path.write_bytes(build_synthetic_sfs(bytes(payload)))
    report = run_all(path)
    assert report.statuses["I-08"] == FAILED
    assert report.statuses["I-09"] != PASS


def test_i09_missing_header_is_not_checked(tmp_path):
    """Kein Payload -> Header fehlt -> NOT_CHECKED, nicht PASS."""
    path = tmp_path / "empty.sfs"
    path.write_bytes(build_synthetic_sfs(b""))
    i09 = run_all(path).by_id("I-09")
    assert i09 is not None and i09.status == NOT_CHECKED


# --- Golden Saves ---------------------------------------------------------
def test_i09_passes_on_all_real_saves(real_saves):
    """Sechs reale Spielstände: die Formel trifft exakt."""
    for path in real_saves:
        result = _i09(path)
        assert result.status == PASS, (path.name, result.detail)
        evidence = result.evidence
        assert evidence["header_size"] == evidence["padding_end"] - 16
        assert evidence["delta"] == 0
        assert evidence["padding_end"] in (139, 141)
        assert evidence["header_size"] in (123, 125)


# ---------------------------------------------------------------------------
# I-14 — Spielzeit-Normalisierung
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("2d.10h.34m.2 Tage.10 Stunden.34 Minuten", 3514),
    ("0d.0h.0m.", 0),
    ("1d.0h.0m.1 Tag.", 1440),
    ("123d.23h.59m.", 123 * 1440 + 23 * 60 + 59),
])
def test_playtime_minutes_parses_machine_head(raw, expected):
    assert playtime_minutes(raw) == expected


@pytest.mark.parametrize("raw", ["", "unbekannt", "2 Tage", "d.h.m.", None])
def test_playtime_minutes_returns_none_when_unreadable(raw):
    assert playtime_minutes(raw) is None


# ---------------------------------------------------------------------------
# I-14 — Sequenzlogik
# ---------------------------------------------------------------------------
def _header(base, **overrides):
    return dataclasses.replace(base, **overrides)


def test_i14_not_checked_without_sequence(synthetic_save):
    assert run_all(synthetic_save).statuses["I-14"] == NOT_CHECKED


def test_i14_not_checked_with_single_save(synthetic_save):
    header = build_context(synthetic_save).header
    assert header is not None
    result = run_all(synthetic_save, sequence=(header,)).by_id("I-14")
    assert result.status == NOT_CHECKED
    assert "zwei brauchbare" in result.detail


def test_i14_passes_on_monotonic_series(synthetic_save):
    header = build_context(synthetic_save).header
    assert header is not None
    sequence = (
        _header(header, filetime=100, player_level=10, playtime="1d.0h.0m."),
        _header(header, filetime=200, player_level=20, playtime="2d.0h.0m."),
        _header(header, filetime=300, player_level=30, playtime="3d.0h.0m."),
    )
    result = run_all(synthetic_save, sequence=sequence).by_id("I-14")
    assert result.status == PASS, result.detail
    assert result.evidence["ordered_pairs"] == 2


def test_i14_warns_on_level_regression(synthetic_save):
    header = build_context(synthetic_save).header
    assert header is not None
    sequence = (
        _header(header, filetime=100, player_level=40, playtime="4d.0h.0m."),
        _header(header, filetime=200, player_level=10, playtime="5d.0h.0m."),
    )
    result = run_all(synthetic_save, sequence=sequence).by_id("I-14")
    assert result.status == WARNING
    assert "Level faellt von 40 auf 10" in result.detail


def test_i14_warns_on_playtime_regression(synthetic_save):
    """Level steigt, Spielzeit fällt — muss erkannt werden."""
    header = build_context(synthetic_save).header
    assert header is not None
    sequence = (
        _header(header, filetime=100, player_level=10,
                playtime="5d.0h.0m.5 Tage."),
        _header(header, filetime=200, player_level=20,
                playtime="2d.0h.0m.2 Tage."),
    )
    result = run_all(synthetic_save, sequence=sequence).by_id("I-14")
    assert result.status == WARNING
    assert "Spielzeit faellt" in result.detail


def test_i14_duplicate_timestamp_is_never_pass(synthetic_save):
    """Gleicher FileTime: Reihenfolge unbestimmt -> mindestens WARNING.

    Das innere Paar wird nicht bewertet, aber der Übergang zur nächsten Gruppe
    nutzt ein beliebiges Element. Deshalb darf daraus kein PASS entstehen —
    auch wenn alle bewertbaren Paare monoton sind.
    """
    header = build_context(synthetic_save).header
    assert header is not None
    sequence = (
        _header(header, filetime=100, player_level=10, playtime="1d.0h.0m."),
        _header(header, filetime=100, player_level=15, playtime="1d.1h.0m."),
        _header(header, filetime=200, player_level=20, playtime="2d.0h.0m."),
    )
    result = run_all(synthetic_save, sequence=sequence).by_id("I-14")
    assert result is not None
    assert result.status == WARNING
    assert "identischem FileTime" in result.detail
    assert result.evidence["duplicate_timestamps"] == 1


def test_i14_duplicate_timestamp_still_reports_real_regression(synthetic_save):
    """Ein echter Abfall wird zusätzlich zur Unbestimmtheit gemeldet."""
    header = build_context(synthetic_save).header
    assert header is not None
    sequence = (
        _header(header, filetime=100, player_level=10, playtime="1d.0h.0m."),
        _header(header, filetime=100, player_level=50, playtime="9d.0h.0m."),
        _header(header, filetime=200, player_level=20, playtime="2d.0h.0m."),
    )
    result = run_all(synthetic_save, sequence=sequence).by_id("I-14")
    assert result is not None
    assert result.status == WARNING
    assert "identischem FileTime" in result.detail
    assert "Level faellt von 50 auf 20" in result.detail


def test_i14_not_checked_when_all_timestamps_identical(synthetic_save):
    header = build_context(synthetic_save).header
    assert header is not None
    sequence = tuple(_header(header, filetime=100, player_level=lvl)
                     for lvl in (10, 20, 30))
    result = run_all(synthetic_save, sequence=sequence).by_id("I-14")
    assert result.status == NOT_CHECKED
    assert "keine eindeutig sortierbare Reihenfolge" in result.detail


def test_i14_discards_unusable_headers(synthetic_save):
    header = build_context(synthetic_save).header
    assert header is not None
    sequence = (
        _header(header, filetime=0, player_level=10),        # keine Zeit
        _header(header, filetime=100, player_level=0),       # kein Level
        _header(header, filetime=200, player_level=30, playtime="2d.0h.0m."),
    )
    result = run_all(synthetic_save, sequence=sequence).by_id("I-14")
    assert result.status == NOT_CHECKED
    assert result.evidence["discarded"] == 2


def test_i14_only_compares_same_character(synthetic_save):
    """Ein fremder Charakter im Ordner darf keine Zeitreihe bilden."""
    header = build_context(synthetic_save).header
    assert header is not None
    sequence = (
        _header(header, filetime=100, player_level=40, player_name="TestPilot"),
        _header(header, filetime=200, player_level=10, player_name="TestPilot"),
        _header(header, filetime=150, player_level=1, player_name="Fremder"),
    )
    result = run_all(synthetic_save, sequence=sequence).by_id("I-14")
    # Bezugssave ist PTestPilot -> der Fremde fliegt raus, Abfall bleibt sichtbar.
    assert result.status == WARNING
    assert "Level faellt von 40 auf 10" in result.detail
    # R1_6: der Spielername ist NICHT mehr oeffentlich. Intern bleibt er
    # fuer Diagnose erhalten (F-1).
    assert "character" not in result.evidence
    assert "TestPilot" not in result.detail
    assert result.evidence["character_count"] == 1
    assert result.internal.get("character") == "TestPilot"


def test_i14_unreadable_playtime_is_reported(synthetic_save):
    header = build_context(synthetic_save).header
    assert header is not None
    sequence = (
        _header(header, filetime=100, player_level=10, playtime="unbekannt"),
        _header(header, filetime=200, player_level=20, playtime="auch unbekannt"),
    )
    result = run_all(synthetic_save, sequence=sequence).by_id("I-14")
    # Ohne lesbare Spielzeit ist die Sequenz nicht vollständig bewertbar -> WARNING.
    assert result.status == WARNING
    assert "Spielzeit in keinem Paar lesbar" in result.detail


# ---------------------------------------------------------------------------
# I-14 — Sequenz-Sammlung aus dem Verzeichnis
# ---------------------------------------------------------------------------
def test_collect_sequence_reads_directory(tmp_path):
    for index, level in enumerate((10, 20, 30)):
        (tmp_path / f"Save{index}.sfs").write_bytes(
            build_synthetic_sfs(build_dat_payload(
                normal=[], light=[], medium=[],
                header_size_field=None)))
    # filetime unterscheidet sich nicht -> nur ein Header nach Dedup
    sequence = collect_sequence(tmp_path / "Save0.sfs")
    assert len(sequence) == 1        # identische Payloads werden dedupliziert


def test_collect_sequence_deduplicates_identical_payloads(tmp_path):
    payload = build_synthetic_sfs(build_dat_payload())
    (tmp_path / "a.sfs").write_bytes(payload)
    (tmp_path / "b.sfs").write_bytes(payload)          # Kopie, gleicher Inhalt
    sequence = collect_sequence(tmp_path / "a.sfs")
    assert len(sequence) == 1


def test_collect_sequence_is_deterministic(tmp_path):
    for name in ("c.sfs", "a.sfs", "b.sfs"):
        (tmp_path / name).write_bytes(
            build_synthetic_sfs(build_dat_payload(playtime=f"{len(name)}d.1h.1m.")))
    first = [h.playtime for h in collect_sequence(tmp_path / "a.sfs")]
    second = [h.playtime for h in collect_sequence(tmp_path / "a.sfs")]
    assert first == second


def test_collect_sequence_empty_directory_yields_nothing(tmp_path):
    assert collect_sequence(tmp_path / "missing.sfs") == ()


# ---------------------------------------------------------------------------
# CLI-Verdrahtung
# ---------------------------------------------------------------------------
def test_cli_verify_runs_sequence_on_real_saves(real_saves):
    """Über den regulären CLI-Aufruf muss I-14 tatsächlich bewertet werden."""
    import json
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "sfda_cli.py"), "--json", "save", "verify",
         str(real_saves[0])],
        capture_output=True, text=True, cwd=str(repo), timeout=300)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    i14 = next(c for c in payload["checks"] if c["check_id"] == "I-14")
    assert i14["status"] == PASS, i14
    assert i14["evidence"]["saves"] >= 2
    assert i14["evidence"]["ordered_pairs"] >= 1


def test_cli_verify_no_sequence_switch(real_saves):
    import json
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "sfda_cli.py"), "--json", "save", "verify",
         "--no-sequence", str(real_saves[0])],
        capture_output=True, text=True, cwd=str(repo), timeout=300)
    payload = json.loads(result.stdout)
    i14 = next(c for c in payload["checks"] if c["check_id"] == "I-14")
    assert i14["status"] == NOT_CHECKED


def test_cli_verify_coverage_is_twelve(real_saves):
    """I-09 und I-14 sind jetzt bewertet: 12 von 14."""
    import json
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "sfda_cli.py"), "--json", "save", "verify",
         str(real_saves[0])],
        capture_output=True, text=True, cwd=str(repo), timeout=300)
    payload = json.loads(result.stdout)
    assert payload["coverage"]["assessed"] == 12
    assert payload["coverage"]["UNKNOWN"] == 0
    assert payload["total"] == PASS
    assert payload["total_with_gaps"] == NOT_CHECKED   # I-12/I-13 offen


# ---------------------------------------------------------------------------
# I-14/L1 — Sortierverantwortung: collect_sequence waehlt aus, check_i14 ordnet
# ---------------------------------------------------------------------------
def test_collect_sequence_returns_filename_order_not_chronology(tmp_path):
    """Der Sammler sortiert NICHT chronologisch — das tut ausschliesslich I-14.

    Wenn jemand die Sortierung in ``collect_sequence`` verschiebt, kippt dieser
    Test: die Rueckgabe steht dann in Zeitfolge statt in Dateinamen-Reihenfolge.
    """
    # Dateiname aufsteigend (a, b, c), filetime absteigend (300, 200, 100):
    # Dateinamen-Reihenfolge und Chronologie sind damit gegenlaeufig.
    _save(tmp_path, "a.sfs", filetime=300, playtime="3d.0h.0m.")
    _save(tmp_path, "b.sfs", filetime=200, playtime="2d.0h.0m.")
    _save(tmp_path, "c.sfs", filetime=100, playtime="1d.0h.0m.")

    sequence = collect_sequence(tmp_path / "a.sfs")
    assert [h.filetime for h in sequence] == [300, 200, 100]    # Dateinamen

    result = run_all(tmp_path / "a.sfs", sequence=sequence).by_id("I-14")
    assert result.status == PASS, result.detail
    assert result.evidence["span"] == [100, 300]                # erst hier geordnet
    assert result.evidence["order_basis"] == "Header-FileTime (Tiebreak save_number)"


def test_sequence_is_backwards_compatible_tuple(tmp_path):
    _save(tmp_path, "a.sfs")
    sequence = collect_sequence(tmp_path / "a.sfs")
    assert isinstance(sequence, tuple)
    assert sequence == tuple(sequence)
    assert [h.player_name for h in sequence] == ["TestPilot"]
    # Nicht existierendes Verzeichnis -> leere Sequenz (kein Fehler).
    assert collect_sequence(tmp_path / "nirgends" / "missing.sfs") == ()
    # Leeres Tupel bleibt ein gueltiger Rueckgabewert fuer run_all.
    report = run_all(tmp_path / "a.sfs", sequence=())
    assert report.statuses["I-14"] == NOT_CHECKED


# ---------------------------------------------------------------------------
# I-14/L2 — Header-only-Scan: keine vollstaendige Dekompression je Save
# ---------------------------------------------------------------------------
def test_header_only_matches_full_payload_on_real_saves(real_saves):
    """Der Header aus Chunk 0 ist feldgleich zum Header aus dem ganzen Strom."""
    from ssb_i.savegame_provider import SfsDecodeProvider

    provider = SfsDecodeProvider()
    for path in real_saves:
        probe = provider.read_header(str(path))
        full = provider.parse_dat_header(provider.decompress(str(path)))
        assert probe["header"] == full, path.name
        assert probe["chunks_total"] >= 1
        assert probe["chunks_decoded"] <= probe["chunks_total"]


def test_collect_sequence_does_not_decompress_the_body(tmp_path, monkeypatch):
    """Sequenzscan: 0 volle Dekompressionen; die Pruefung: genau 1."""
    from ssb_i.savegame_provider import SfsDecodeProvider

    for index in range(3):
        _save(tmp_path, "Save%d.sfs" % index, playtime="%dd.0h.0m." % (index + 1))

    calls = {"full": 0}
    original = SfsDecodeProvider.decompress

    def counted(self, *args, **kwargs):
        calls["full"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SfsDecodeProvider, "decompress", counted)

    sequence = collect_sequence(tmp_path / "Save0.sfs")
    assert len(sequence) == 3
    assert calls["full"] == 0
    assert sequence.stats["full_decompressions"] == 0
    assert sequence.stats["header_only"] == 3

    run_all(tmp_path / "Save0.sfs", sequence=sequence)
    assert calls["full"] == 1          # nur der Bezugssave, genau einmal


def test_collect_sequence_rejects_truncated_container(tmp_path):
    blob = build_synthetic_sfs(build_dat_payload())
    (tmp_path / "Save0.sfs").write_bytes(blob)
    (tmp_path / "Save1.sfs").write_bytes(blob[:len(blob) - 40])

    sequence = collect_sequence(tmp_path / "Save0.sfs")
    assert len(sequence) == 1
    assert len(sequence.discarded) == 1
    entry = sequence.discarded[0]
    assert entry.name == "Save1.sfs"
    assert entry.kind == "structurally_invalid"
    assert "truncated" in entry.reason


def test_collect_sequence_rejects_missing_header_data(tmp_path):
    (tmp_path / "Save0.sfs").write_bytes(build_synthetic_sfs(build_dat_payload()))
    (tmp_path / "Save1.sfs").write_bytes(
        build_synthetic_sfs(b"NOT_A_SAVEGAME" + b"\x00" * 64))

    sequence = collect_sequence(tmp_path / "Save0.sfs")
    assert len(sequence) == 1
    entry = sequence.discarded[0]
    assert entry.name == "Save1.sfs"
    assert entry.kind == "no_header_data"
    assert "SFS_SAVEGAME" in entry.reason


def test_collect_sequence_rejects_unreadable_path(tmp_path):
    (tmp_path / "Save0.sfs").write_bytes(build_synthetic_sfs(build_dat_payload()))
    (tmp_path / "Save1.sfs").mkdir()

    sequence = collect_sequence(tmp_path / "Save0.sfs")
    assert len(sequence) == 1
    assert sequence.discarded[0].kind == "unreadable"


def _container_with_level(payload: bytes, level: int, *, chunk_size_pre: int = 256,
                          padding: int = 16) -> bytes:
    """BCPS-Container mit waehlbarer zlib-Stufe: gleicher Payload, anderer Strom."""
    import zlib

    chunks = [payload[i:i + chunk_size_pre]
              for i in range(0, len(payload), chunk_size_pre)] or [b""]
    compressed = [zlib.compress(chunk, level) for chunk in chunks]
    sizes = [len(blob) for blob in compressed]
    chunk_sizes_offset = 72
    table = struct.pack("<%di" % len(sizes), *sizes)
    compressed_offset = chunk_sizes_offset + len(table)
    if padding and compressed_offset % padding:
        compressed_offset = (compressed_offset + padding - 1) // padding * padding
    header = bytearray(72)
    header[0:4] = b"BCPS"
    struct.pack_into("<i", header, 4, 1)
    struct.pack_into("<q", header, 8, chunk_sizes_offset)
    struct.pack_into("<q", header, 16, 0)
    struct.pack_into("<q", header, 24, compressed_offset)
    struct.pack_into("<q", header, 32, len(payload))
    struct.pack_into("<f", header, 40, 2.0)
    struct.pack_into("<i", header, 44, 0)
    struct.pack_into("<q", header, 48, chunk_size_pre)
    struct.pack_into("<q", header, 56, padding)
    struct.pack_into("<i", header, 64, 0)
    header[68:72] = b"ZIP "
    body = bytearray(table)
    body += b"\x00" * (compressed_offset - chunk_sizes_offset - len(table))
    for blob in compressed:
        body += blob
        if padding:
            body += b"\x00" * ((-len(blob)) % padding)
    return bytes(header) + bytes(body)


def test_collect_sequence_detects_recompressed_duplicate(tmp_path):
    """Gleicher Payload, andere Kompression: gleiche Header, anderer Strom.

    Genau der Fall, den die Duplikaterkennung nicht raten darf: der Strom
    beweist hier nichts, also muss einmal vollstaendig entpackt und verglichen
    werden — sonst stuende derselbe Spielstand zweimal in der Zeitreihe.
    """
    payload = build_dat_payload(body=b"\x00" * 20000)
    blob_a = _container_with_level(payload, 9)
    blob_b = _container_with_level(payload, 0)
    assert blob_a != blob_b, "Testaufbau: die Stroeme muessen sich unterscheiden"
    (tmp_path / "a.sfs").write_bytes(blob_a)
    (tmp_path / "b.sfs").write_bytes(blob_b)

    sequence = collect_sequence(tmp_path / "a.sfs")
    assert len(sequence) == 1
    assert sequence.stats["payload_sha_checks"] == 1
    assert [e.name for e in sequence.duplicates] == ["b.sfs"]


# ---------------------------------------------------------------------------
# I-14/L3 — Auswahlbegrenzung und verworfene Header sind nachvollziehbar
# ---------------------------------------------------------------------------
def test_sequence_selection_limit_is_logged(tmp_path):
    import os

    for index in range(6):
        path = _save(tmp_path, "Save%d.sfs" % index,
                     playtime="%dd.0h.0m." % (index + 1))
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))

    sequence = collect_sequence(tmp_path / "Save5.sfs", max_files=4)
    assert sequence.limit_applied is True
    assert sequence.candidates == 6
    assert sequence.stats["files_considered"] == 4
    # Auswahl ueber mtime: die beiden aeltesten fallen raus.
    assert sorted(e.name for e in sequence.not_considered) == ["Save0.sfs", "Save1.sfs"]

    evidence = sequence.to_evidence()
    assert evidence["limit_applied"] is True
    assert evidence["not_considered"]["count"] == 2
    assert "mtime" in evidence["limit_basis"]


def test_sequence_seventy_files_hits_the_documented_limit(tmp_path):
    """70 Dateien: Limit 64 greift, 6 bleiben unberuecksichtigt — mit Namen."""
    import os

    for index in range(70):
        path = _save(tmp_path, "Save%02d.sfs" % index,
                     playtime="%dd.0h.0m." % (index + 1))
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))

    sequence = collect_sequence(tmp_path / "Save69.sfs")
    assert sequence.limit_applied is True
    assert sequence.candidates == 70
    assert sequence.stats["files_considered"] == 64
    assert len(sequence.not_considered) == 6
    evidence = sequence.to_evidence()
    # R1_6 / F-3: oeffentlich nur die Anzahl — keine Dateinamen.
    assert evidence["not_considered"]["count"] == 6
    assert "names" not in evidence["not_considered"]
    assert "truncated" not in evidence["not_considered"]
    # Die Namen bleiben intern nachvollziehbar.
    internal = sequence.to_internal_evidence()
    assert internal["not_considered"]["truncated"] is False
    assert len(internal["not_considered"]["names"]) == 6


def test_i14_evidence_carries_the_selection_report(tmp_path):
    import json

    for index in range(3):
        _save(tmp_path, "Save%d.sfs" % index, playtime="%dd.0h.0m." % (index + 1))

    sequence = collect_sequence(tmp_path / "Save0.sfs")
    report = run_all(tmp_path / "Save0.sfs", sequence=sequence)
    selection = report.by_id("I-14").evidence["selection"]
    assert selection["candidates"] == 3
    assert selection["considered"] == 3
    assert selection["limit_applied"] is False
    # R1_6 / F-3: oeffentlich die Anzahl, keine Dateinamen.
    assert selection["selected_count"] == 3
    assert "selected" not in selection
    assert "Header-only" in selection["body_check"]
    assert selection["discarded"] == []
    json.dumps(report.to_dict())        # bleibt serialisierbar


def test_collect_sequence_header_only_does_not_notice_damaged_body(tmp_path):
    """Header-only: ein kaputter Chunk im Rumpf wird NICHT entdeckt.

    Diese Grenze ist bewusst und steht als ``body_check`` im Befund; sie darf
    nur nicht als Vollpruefung gelesen werden. Der Test haelt beide Seiten
    fest: der Scan nimmt die Datei auf, die volle Dekompression scheitert.
    """
    from ssb_i.savegame_provider import SfsDecodeProvider

    payload = build_dat_payload(body=b"\x00" * 2000)
    blob = bytearray(build_synthetic_sfs(payload, chunk_size_pre=1024))
    sizes_offset = struct.unpack_from("<q", blob, 8)[0]
    compressed_offset = struct.unpack_from("<q", blob, 24)[0]
    count = (len(payload) + 1023) // 1024
    sizes = struct.unpack_from("<%di" % count, blob, sizes_offset)
    second_chunk = compressed_offset + (sizes[0] + 15) // 16 * 16
    blob[second_chunk] = 0x00                            # ungueltiger zlib-Kopf
    target = tmp_path / "Save0.sfs"
    target.write_bytes(bytes(blob))

    sequence = collect_sequence(target)
    assert len(sequence) == 1
    assert sequence.stats["full_decompressions"] == 0
    assert "Header-only" in sequence.to_evidence()["body_check"]

    with pytest.raises(ValueError):
        SfsDecodeProvider().decompress(str(target))


# ---------------------------------------------------------------------------
# R1 — keine privaten Pfade in CLI- und JSON-Ausgaben
# ---------------------------------------------------------------------------
def test_error_reason_has_no_paths_for_oserror_subclasses():
    """Alle geforderten OSError-Faelle: Klasse bleibt, Pfad verschwindet."""
    from ssb_i.save_integrity import _error_reason

    marker = "/home/cole/PRIVAT-MARKER-R1/save.sfs"
    cases = (
        (IsADirectoryError(21, "Is a directory", marker),
         "IsADirectoryError", "Is a directory"),
        (FileNotFoundError(2, "No such file or directory", marker),
         "FileNotFoundError", "No such file"),
        (PermissionError(13, "Permission denied", marker),
         "PermissionError", "Permission denied"),
        (OSError(5, "Input/output error", marker),
         "OSError", "Input/output error"),
        (NotADirectoryError(20, "Not a directory", marker),
         "NotADirectoryError", "Not a directory"),
    )
    for exc, klass, message in cases:
        text = _error_reason(exc)
        assert marker not in text, text
        assert "/home/cole" not in text, text
        assert "PRIVAT-MARKER-R1" not in text, text
        assert klass in text, text
        assert message in text, text


def test_error_reason_redacts_paths_in_non_oserror():
    """Auch fremde Fehlertexte werden von Pfaden befreit."""
    from ssb_i.save_integrity import _error_reason

    for raw in ("kaputt in /home/cole/PRIVAT-R1/a.sfs",
                "Verzeichnis C:\\Users\\cole\\Saves nicht lesbar",
                "Fehler bei '/etc/privat-r1.conf'"):
        text = _error_reason(ValueError(raw))
        assert "ValueError" in text, text
        assert "/home/cole" not in text, text
        assert "/etc/privat-r1.conf" not in text, text
        assert "C:\\Users" not in text, text


def test_collect_sequence_discard_reason_does_not_leak_the_folder(tmp_path):
    """Reproduktion des Review-Befunds R1, jetzt ohne Pfad."""
    from ssb_i.save_integrity import collect_sequence

    _save(tmp_path, "Save0.sfs")
    (tmp_path / "Save1.sfs").mkdir()          # lsbar, aber open() scheitert

    sequence = collect_sequence(tmp_path / "Save0.sfs")
    assert len(sequence.discarded) == 1
    entry = sequence.discarded[0]
    assert entry.kind == "unreadable"
    assert "IsADirectoryError" in entry.reason
    assert str(tmp_path) not in entry.reason
    assert str(tmp_path) not in repr(sequence.to_evidence())


def test_permission_error_discard_reason_has_no_path(tmp_path):
    import os

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("als root greift chmod 000 nicht")

    from ssb_i.save_integrity import collect_sequence

    _save(tmp_path, "Save0.sfs")
    blocked = _save(tmp_path, "Save1.sfs", playtime="2d.0h.0m.")
    os.chmod(blocked, 0o000)
    try:
        sequence = collect_sequence(tmp_path / "Save0.sfs")
        assert len(sequence.discarded) == 1
        entry = sequence.discarded[0]
        assert "PermissionError" in entry.reason
        assert str(tmp_path) not in entry.reason
    finally:
        os.chmod(blocked, 0o644)


def test_unchanged_reasons_for_container_and_header_defects(tmp_path):
    """Andere Verwerfungsgruende bleiben unveraendert (Auftrag, Punkt 6)."""
    from ssb_i.save_integrity import collect_sequence

    _save(tmp_path, "Save0.sfs")
    (tmp_path / "Save1.sfs").write_bytes(b"kein BCPS")
    (tmp_path / "Save2.sfs").write_bytes(
        build_synthetic_sfs(b"NOT_A_SAVEGAME" + b"\x00" * 64))

    reasons = {e.name: e.reason for e in collect_sequence(tmp_path / "Save0.sfs").discarded}
    # R1.2: der Byte-Platzhalter gibt nur noch eine statische Beschreibung aus
    # (Befund N1). Die Verwerfungsgruende selbst — und damit I-09/I-14 —
    # bleiben unveraendert; die Pruefsumme ist byteidentisch.
    assert reasons["Save1.sfs"] == "ValueError: Not an SFS file: unknown signature (expected b'BCPS')"
    assert reasons["Save2.sfs"].startswith("SFS_SAVEGAME header not decodable")
    assert "Not a DAT file" in reasons["Save2.sfs"]


def test_cli_and_json_output_contain_no_private_paths(tmp_path):
    """Ende-zu-Ende: weder Text- noch JSON-Ausgabe nennt den vollen Pfad."""
    import json
    import subprocess

    from ssb_i.save_integrity import collect_sequence

    folder = tmp_path / "PRIVAT-R1-ORDNER"
    folder.mkdir()
    (folder / "Save0.sfs").write_bytes(build_synthetic_sfs(build_dat_payload()))
    (folder / "Save1.sfs").mkdir()                       # unreadable
    (folder / "Save2.sfs").write_bytes(b"kein BCPS")     # strukturell ungueltig

    assert str(folder) not in repr(collect_sequence(folder / "Save0.sfs").to_evidence())

    repo = Path(__file__).resolve().parents[1]
    text_run = subprocess.run(
        [sys.executable, str(repo / "sfda_cli.py"), "save", "verify",
         str(folder / "Save0.sfs")],
        capture_output=True, text=True, cwd=str(repo), timeout=300)
    combined = text_run.stdout + text_run.stderr
    assert str(folder) not in combined, combined
    assert "PRIVAT-R1-ORDNER" not in combined, combined
    assert "IsADirectoryError" in combined, combined

    json_run = subprocess.run(
        [sys.executable, str(repo / "sfda_cli.py"), "--json", "save", "verify",
         str(folder / "Save0.sfs")],
        capture_output=True, text=True, cwd=str(repo), timeout=300)
    parsed = json.loads(json_run.stdout)                  # bleibt gueltiges JSON
    i14 = next(c for c in parsed["checks"] if c["check_id"] == "I-14")
    selection = json.dumps(i14["evidence"]["selection"])
    # Fremdpfade duerfen im Auswahlprotokoll nicht auftauchen.
    assert str(folder) not in selection, selection[:800]
    assert "IsADirectoryError" in selection
    # R1_6 / F-2: der Pfad der geprueften Datei steht NICHT mehr im
    # oeffentlichen Bericht — auch nicht als Dateiname.
    assert "path" not in parsed
    assert "Save0.sfs" not in json.dumps(parsed)


# ---------------------------------------------------------------------------
# R3 — Auswahlgrenze: unveraendert, aber sichtbar dokumentiert
# ---------------------------------------------------------------------------
def test_sequence_limit_constant_and_documentation_unchanged():
    """Die Auswahlregel ist unangetastet; die Grenze steht in der Doku."""
    from ssb_i import save_integrity

    assert save_integrity.SEQUENCE_MAX_FILES == 64
    source = Path(save_integrity.__file__).read_text()
    doc = save_integrity.collect_sequence.__doc__ or ""
    assert "AUSWAHLGRENZE" in doc
    for punkt in ("mtime", "Spielzeit-RUECKGANG",
                  "nicht auf den vorhandenen Datenbestand"):
        assert punkt in doc, punkt
    # Auswahl bleibt mtime-basiert und auf max_files begrenzt
    assert "st_mtime" in source
    assert "[:max_files]" in source


def test_limit_is_reported_as_limitation_not_as_status(tmp_path):
    """Ausschluss wird benannt, aendert aber den Status NICHT (Auftrag Punkt 3)."""
    import os

    from ssb_i.save_integrity import (collect_sequence, format_sequence_summary,
                                      run_all)

    for index in range(5):
        path = _save(tmp_path, "Save%d.sfs" % index,
                     playtime="%dd.0h.0m." % (index + 1),
                     filetime=100 + index)
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))

    sequence = collect_sequence(tmp_path / "Save4.sfs", max_files=3)
    report = run_all(tmp_path / "Save4.sfs", sequence=sequence)

    text = "\n".join(format_sequence_summary(report))
    assert "EINSCHRAENKUNG" in text
    assert "NICHT die Konsistenz aller vorhandenen Saves" in text
    assert "2 Datei(en)" in text                       # Anzahl der Ausschluesse

    limitation = sequence.to_evidence()["limitation"]
    assert "2 Datei(en)" in limitation
    assert "Datei-mtime" in limitation

    # Keine stille Statusaenderung: die Auswahl aendert I-14 nicht.
    assert report.by_id("I-14").status == PASS


def test_no_limitation_text_when_everything_was_considered(tmp_path):
    from ssb_i.save_integrity import (collect_sequence, format_sequence_summary,
                                      run_all)

    for index in range(3):
        _save(tmp_path, "Save%d.sfs" % index,
              playtime="%dd.0h.0m." % (index + 1), filetime=100 + index)

    sequence = collect_sequence(tmp_path / "Save0.sfs")
    report = run_all(tmp_path / "Save0.sfs", sequence=sequence)
    assert sequence.to_evidence()["limitation"] == ""
    assert "EINSCHRAENKUNG" not in "\n".join(format_sequence_summary(report))


def test_limitation_reports_discarded_files_too(tmp_path):
    """Auch verworfene Dateien mindern die Aussagekraft und werden benannt."""
    from ssb_i.save_integrity import (collect_sequence, format_sequence_summary,
                                      run_all)

    for index in range(3):
        _save(tmp_path, "Save%d.sfs" % index,
              playtime="%dd.0h.0m." % (index + 1), filetime=100 + index)
    (tmp_path / "Save9.sfs").mkdir()

    sequence = collect_sequence(tmp_path / "Save0.sfs")
    report = run_all(tmp_path / "Save0.sfs", sequence=sequence)
    limitation = sequence.to_evidence()["limitation"]
    assert "verworfen" in limitation
    assert "NICHT die Konsistenz" in limitation
    assert "EINSCHRAENKUNG" in "\n".join(format_sequence_summary(report))
