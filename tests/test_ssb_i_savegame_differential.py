from __future__ import annotations

from typing import Any
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ssb_i.savegame_differential import (  # noqa: E402
    DISPROVEN,
    MATCHED,
    PARTIAL_MATCH,
    UNKNOWN,
    analyze_bytes,
    cluster_offsets,
    compare_metadata,
)
from ssb_i.savegame_provider import DatHeader, PluginInfo, SfsContainer  # noqa: E402
from ssb_i.savegame_provider import PluginEntry  # noqa: E402


def test_identical_saves_have_no_differences() -> None:
    result = analyze_bytes(b"abcdef", b"abcdef")
    assert result["differing_byte_count"] == 0
    assert result["clusters"] == []
    assert result["noise_assessment"]["classification"] == "PROVEN"


def test_controlled_change_forms_one_cluster() -> None:
    result = analyze_bytes(b"0123456789", b"012X456789")
    assert result["differing_byte_count"] == 1
    assert result["clusters"] == [{
        "start": 3, "end": 4, "size": 1, "differing_bytes": 1,
        "classification": "PROVEN",
    }]


def test_separate_changes_form_separate_clusters() -> None:
    result = analyze_bytes(b"0123456789ABCDEF", b"0X23456789ABCDYF")
    assert [(x["start"], x["end"]) for x in result["clusters"]] == [(1, 2), (14, 15)]


def test_cluster_gap_option_joins_only_requested_gap() -> None:
    assert [(x.start, x.end) for x in cluster_offsets([1, 2, 4], max_gap=0)] == [(1, 3), (4, 5)]
    assert [(x.start, x.end) for x in cluster_offsets([1, 2, 4], max_gap=1)] == [(1, 5)]


def test_incompatible_metadata_is_representable_without_semantic_inference() -> None:
    # Byte-level API cannot invent headers; this verifies unknown data remains unknown.
    result = analyze_bytes(b"old", b"new")
    assert result["formid_candidates"] == []
    assert any(x["classification"] == UNKNOWN for x in result["negative_evidence"])


def test_known_offset_is_context_only_and_not_a_part_anchor() -> None:
    result = analyze_bytes(b"a", b"b")
    marker = result["known_offset_0x147D9C"]
    assert marker["classification"] == "NON-STABLE / CONTEXTUAL ONLY"
    assert any(x["classification"] == DISPROVEN and "0x147D9C" in x["statement"]
               for x in result["negative_evidence"])


def test_large_difference_is_unsuitable_signal_for_cli_layer() -> None:
    result = analyze_bytes(b"a" * 100, b"b" * 100, unsuitable_diff_ratio=0.25)
    assert result["noise_assessment"]["classification"] == "STRONG EVIDENCE"


def test_match_constants_are_stable() -> None:
    assert MATCHED == "MATCHED"


def _header(**changes):
    values = dict(header_size=1, engine_version=1, save_version=1, save_number=1,
                  player_name="Cole", player_level=10, player_location="Jemison",
                  playtime="1h", race_name="Human", gender=0, experience=1.0,
                  experience_required=2.0, filetime=1, save_version_2=1,
                  current_game_version="1.16.244.0", created_game_version="1.16.244.0",
                  plugin_info_offset=1, plugin_info_size=1)
    values.update(changes)
    return DatHeader(**values)


def test_non_identity_save_metadata_yields_partial_match() -> None:
    container = SfsContainer(1, 262144, 16, 10, 240, 1).to_dict()
    result = compare_metadata(container, container, _header(), _header(playtime="2h"), PluginInfo(), PluginInfo())
    assert result["suitability_preliminary"] == PARTIAL_MATCH


def test_version_and_plugin_detail_changes_are_not_matched() -> None:
    container = SfsContainer(1, 262144, 16, 10, 240, 1).to_dict()
    base_plugins = PluginInfo(normal=[PluginEntry("Starfield.esm", True)])
    changed_plugins = PluginInfo(normal=[PluginEntry("Starfield.esm", False)])
    version = compare_metadata(container, container, _header(),
                               _header(engine_version=2), base_plugins, base_plugins)
    plugins = compare_metadata(container, container, _header(), _header(),
                               base_plugins, changed_plugins)
    assert version["suitability_preliminary"] == "UNSUITABLE"
    assert plugins["suitability_preliminary"] == "UNSUITABLE"


def test_formid_candidate_scan_handles_single_byte_cluster_at_start() -> None:
    result = analyze_bytes(b"\x00\x00\x00\x00", b"\x01\x00\x00\x00", known_formids={1})
    assert result["formid_candidates"]
    assert result["formid_candidates"][0]["classification"] == UNKNOWN


def test_analyze_paths_integration_and_read_only(tmp_path: Path, monkeypatch) -> None:
    class FakeProvider:
        def read_container(self, path):
            return SfsContainer(1, 262144, 16, 4, 240, 1)

        def decompress(self, path):
            return (b"ABCD" if path.endswith("a.sfs") else b"ABcD")

        def parse_dat_header(self, raw):
            return _header()

        def parse_plugin_info(self, raw, header):
            return PluginInfo()

    import ssb_i.savegame_differential as module
    monkeypatch.setattr(module, "SfsDecodeProvider", FakeProvider)
    a = tmp_path / "a.sfs"
    b = tmp_path / "b.sfs"
    a.write_bytes(b"source-a")
    b.write_bytes(b"source-b")
    before_a, before_b = a.read_bytes(), b.read_bytes()
    report = module.analyze_paths(a, b)
    assert report["result"] == "MATCHED"
    assert report["analysis"]["differing_byte_count"] == 1
    assert a.read_bytes() == before_a
    assert b.read_bytes() == before_b
