"""Read-only Save-A/Save-B differential bridge for SSB-I.

This module deliberately stops at byte-level evidence.  It does not write or
recompress saves and it does not infer ship parts, transforms, parents, or
attachments from byte patterns.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .savegame_provider import DatHeader, PluginInfo, SfsDecodeProvider

PROVEN = "PROVEN"
STRONG = "STRONG EVIDENCE"
PLAUSIBLE = "PLAUSIBLE"
UNKNOWN = "UNKNOWN"
DISPROVEN = "DISPROVEN"
MATCHED = "MATCHED"
PARTIAL_MATCH = "PARTIAL_MATCH"
UNSUITABLE = "UNSUITABLE"
NON_STABLE_CONTEXTUAL = "NON-STABLE / CONTEXTUAL ONLY"

_FORMID_RE = re.compile(r"\b(?:0x)?([0-9A-Fa-f]{6,8})\b")


@dataclass(frozen=True)
class DiffCluster:
    start: int
    end: int
    size: int
    differing_bytes: int
    classification: str = PROVEN

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cluster_offsets(offsets: Iterable[int], *, max_gap: int = 0) -> list[DiffCluster]:
    """Group sorted differing offsets; ``max_gap`` joins small holes."""
    values = sorted(set(int(x) for x in offsets))
    if not values:
        return []
    clusters: list[DiffCluster] = []
    start = previous = values[0]
    count = 1
    for offset in values[1:]:
        if offset - previous > max_gap + 1:
            clusters.append(DiffCluster(start, previous + 1, previous + 1 - start, count))
            start = offset
            count = 1
        else:
            count += 1
        previous = offset
    clusters.append(DiffCluster(start, previous + 1, previous + 1 - start, count))
    return clusters


def _header_fields(header: DatHeader) -> dict[str, Any]:
    return {
        "current_game_version": header.current_game_version,
        "created_game_version": header.created_game_version,
        "save_version": header.save_version,
        "save_version_2": header.save_version_2,
        "engine_version": header.engine_version,
        "player_name": header.player_name,
        "player_level": header.player_level,
        "save_number": header.save_number,
        "player_location": header.player_location,
        "playtime": header.playtime,
        "race_name": header.race_name,
        "gender": header.gender,
    }


def _plugin_key(info: PluginInfo) -> tuple[tuple[tuple[str, bool, str | None, str | None], ...], ...]:
    return (
        tuple((p.name, p.is_native, p.creation_name, p.creation_id) for p in info.normal),
        tuple((p.name, p.is_native, p.creation_name, p.creation_id) for p in info.light),
        tuple((p.name, p.is_native, p.creation_name, p.creation_id) for p in info.medium),
    )


def _parse_header_and_plugins(provider: SfsDecodeProvider, raw: bytes) -> tuple[DatHeader, PluginInfo]:
    header = provider.parse_dat_header(raw)
    return header, provider.parse_plugin_info(raw, header)


def compare_metadata(
    container_a: Mapping[str, Any], container_b: Mapping[str, Any],
    header_a: DatHeader, header_b: DatHeader,
    plugins_a: PluginInfo, plugins_b: PluginInfo,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    fields_a, fields_b = _header_fields(header_a), _header_fields(header_b)
    for field in fields_a:
        equal = fields_a[field] == fields_b[field]
        checks[field] = {"equal": equal, "a": fields_a[field], "b": fields_b[field],
                         "classification": PROVEN if equal else DISPROVEN}
    plugin_equal = _plugin_key(plugins_a) == _plugin_key(plugins_b)
    checks["plugin_list"] = {"equal": plugin_equal, "a": plugins_a.to_dict(), "b": plugins_b.to_dict(),
                             "classification": PROVEN if plugin_equal else DISPROVEN}
    structure_fields = ("chunk_size_pre", "padding_size", "compressed_offset", "chunk_count")
    structure_equal = all(container_a.get(k) == container_b.get(k) for k in structure_fields)
    checks["container_structure"] = {"equal": structure_equal,
        "a": {k: container_a.get(k) for k in structure_fields},
        "b": {k: container_b.get(k) for k in structure_fields},
        "classification": PROVEN if structure_equal else DISPROVEN}
    identity_equal = header_a.player_name == header_b.player_name
    version_equal = all(fields_a[field] == fields_b[field] for field in (
        "current_game_version", "created_game_version", "save_version",
        "save_version_2", "engine_version"))
    if not version_equal or not plugin_equal:
        suitability, reason = UNSUITABLE, "Starfield-/Save-Version oder Pluginbasis weicht ab."
    elif not structure_equal:
        suitability, reason = UNSUITABLE, "SFS-Containerstruktur weicht ab."
    elif not identity_equal:
        suitability, reason = UNSUITABLE, "Spieleridentität weicht ab."
    elif any(fields_a[field] != fields_b[field] for field in fields_a
             if field not in {"current_game_version", "created_game_version", "save_version",
                              "save_version_2", "engine_version", "player_name"}):
        suitability, reason = PARTIAL_MATCH, "Identität/Version/Plugins passen, aber weitere Save-Metadaten ändern sich."
    else:
        suitability, reason = MATCHED, "Version, Pluginbasis, Spieleridentität und Containerstruktur passen."
    return {"checks": checks, "suitability_preliminary": suitability, "suitability_reason": reason}


def load_known_formids(paths: Sequence[str | Path]) -> set[int]:
    """Read hexadecimal IDs from existing reference text; never assign semantics."""
    result: set[int] = set()
    for path in paths:
        p = Path(path)
        if not p.is_file():
            continue
        for match in _FORMID_RE.finditer(p.read_text(encoding="utf-8", errors="replace")):
            value = int(match.group(1), 16)
            if 0 < value <= 0xFFFFFFFF:
                result.add(value)
    return result


def formid_candidates(data: bytes, clusters: Sequence[DiffCluster], known: set[int]) -> list[dict[str, Any]]:
    """Report known 4-byte values inside clusters as candidates only."""
    candidates: list[dict[str, Any]] = []
    for cluster in clusters:
        scan_start = max(0, cluster.start - 3)
        scan_end = min(cluster.end, len(data) - 3)
        for offset in range(scan_start, scan_end):
            if offset < 0 or offset + 4 > len(data):
                continue
            value = int.from_bytes(data[offset:offset + 4], "little")
            if value in known:
                candidates.append({"offset": offset, "value": f"0x{value:08X}",
                    "classification": UNKNOWN,
                    "statement": "Known FormID value occurs in a changed cluster; not proven to be a Part-Instanz."})
    return candidates


def analyze_bytes(a: bytes, b: bytes, *, known_formids: set[int] | None = None,
                  max_gap: int = 0, unsuitable_diff_ratio: float = 0.25) -> dict[str, Any]:
    limit = min(len(a), len(b))
    offsets = [i for i in range(limit) if a[i] != b[i]]
    offsets.extend(range(limit, max(len(a), len(b))))
    clusters = cluster_offsets(offsets, max_gap=max_gap)
    ratio = len(offsets) / max(len(a), len(b), 1)
    if not offsets:
        noise = {"classification": PROVEN, "ratio": 0.0, "reason": "No byte differences."}
    elif ratio > unsuitable_diff_ratio:
        noise = {"classification": STRONG, "ratio": ratio,
                 "reason": "Difference set is large; no semantic interpretation is forced."}
    else:
        noise = {"classification": UNKNOWN, "ratio": ratio,
                 "reason": "A byte difference set alone does not prove a controlled ship change."}
    known_formids = known_formids or set()
    return {
        "sizes": {"a": len(a), "b": len(b)},
        "differing_byte_count": len(offsets),
        "differing_ratio": ratio,
        "clusters": [c.to_dict() for c in clusters],
        "noise_assessment": noise,
        "formid_candidates": formid_candidates(b, clusters, known_formids),
        "negative_evidence": [
            {"statement": "A byte difference is not automatically ship-part evidence.", "classification": UNKNOWN},
            {"statement": "FormID hits are not automatically identified part instances.", "classification": UNKNOWN},
            {"statement": "Offsets and float patterns are not interpreted as a transform.", "classification": UNKNOWN},
            {"statement": "Parent/attachment relations were not extracted.", "classification": UNKNOWN},
            {"statement": "0x147D9C is not used as a part or transform anchor.", "classification": DISPROVEN},
        ],
        "known_offset_0x147D9C": {"classification": NON_STABLE_CONTEXTUAL,
            "statement": "Context reference only; no stable file position and no part/transform semantics."},
    }


def analyze_paths(path_a: str | Path, path_b: str | Path, *, known_formid_paths: Sequence[str | Path] = (),
                  max_gap: int = 0, unsuitable_diff_ratio: float = 0.25) -> dict[str, Any]:
    provider = SfsDecodeProvider()
    container_a = provider.read_container(str(path_a)).to_dict()
    container_b = provider.read_container(str(path_b)).to_dict()
    raw_a, raw_b = provider.decompress(str(path_a)), provider.decompress(str(path_b))
    header_a, plugins_a = _parse_header_and_plugins(provider, raw_a)
    header_b, plugins_b = _parse_header_and_plugins(provider, raw_b)
    metadata = compare_metadata(container_a, container_b, header_a, header_b, plugins_a, plugins_b)
    result = {"read_only": True, "classification_vocabulary": [PROVEN, STRONG, PLAUSIBLE, UNKNOWN, DISPROVEN],
        "inputs": {"a": str(path_a), "b": str(path_b)},
        "containers": {"a": container_a, "b": container_b},
        "headers": {"a": header_a.to_dict(), "b": header_b.to_dict()},
        "metadata_comparison": metadata,
        "analysis": analyze_bytes(raw_a, raw_b, known_formids=load_known_formids(known_formid_paths),
                                  max_gap=max_gap, unsuitable_diff_ratio=unsuitable_diff_ratio)}
    if metadata["suitability_preliminary"] == UNSUITABLE:
        result["result"] = UNSUITABLE
        result["reason"] = metadata["suitability_reason"]
    elif result["analysis"]["noise_assessment"]["classification"] == STRONG:
        result["result"] = UNSUITABLE
        result["reason"] = "Obviously large difference set; no artificial ship interpretation."
    else:
        result["result"] = metadata["suitability_preliminary"]
        result["reason"] = metadata["suitability_reason"]
    return result


def markdown_report(report: Mapping[str, Any]) -> str:
    analysis = report["analysis"]
    lines = ["# SSB-I Savegame Differential Report", "", "**READ-ONLY:** yes",
             f"**RESULT:** `{report['result']}`", f"**REASON:** {report['reason']}", "",
             "## Inputs", f"- Save A: `{report['inputs']['a']}`",
             f"- Save B: `{report['inputs']['b']}`", "", "## Metadata check"]
    for name, check in report["metadata_comparison"]["checks"].items():
        lines.append(f"- `{name}`: {'equal' if check['equal'] else 'different'} — `{check['classification']}`")
    lines += ["", "## Difference",
              f"- A size: `{analysis['sizes']['a']}` bytes",
              f"- B size: `{analysis['sizes']['b']}` bytes",
              f"- Differing bytes: `{analysis['differing_byte_count']}`",
              f"- Difference ratio: `{analysis['differing_ratio']:.6f}`", "", "### Clusters"]
    if analysis["clusters"]:
        for c in analysis["clusters"]:
            lines.append(f"- `0x{c['start']:X}..0x{c['end'] - 1:X}` — {c['size']} bytes, "
                         f"{c['differing_bytes']} changed — `{c['classification']}`")
    else:
        lines.append("- No difference clusters.")
    lines += ["", "## FormID candidates"]
    if analysis["formid_candidates"]:
        lines += [f"- `{x['value']}` at `0x{x['offset']:X}` — `{x['classification']}`; {x['statement']}"
                  for x in analysis["formid_candidates"]]
    else:
        lines.append("- No known FormID candidates in difference clusters.")
    lines += ["", "## Explicit negative evidence"]
    lines += [f"- {x['statement']} — `{x['classification']}`" for x in analysis["negative_evidence"]]
    lines += ["", "## 0x147D9C",
              f"- `{analysis['known_offset_0x147D9C']['classification']}` — "
              f"{analysis['known_offset_0x147D9C']['statement']}", ""]
    return "\n".join(lines)


def write_reports(report: Mapping[str, Any], json_path: str | Path, markdown_path: str | Path) -> None:
    Path(json_path).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    Path(markdown_path).write_text(markdown_report(report), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("save_a", type=Path)
    parser.add_argument("save_b", type=Path)
    parser.add_argument("--json", type=Path, default=Path("savegame-differential.json"))
    parser.add_argument("--markdown", type=Path, default=Path("savegame-differential.md"))
    parser.add_argument("--known-formids", type=Path, action="append", default=[])
    parser.add_argument("--max-gap", type=int, default=0)
    parser.add_argument("--unsuitable-diff-ratio", type=float, default=0.25)
    args = parser.parse_args(argv)
    report = analyze_paths(args.save_a, args.save_b, known_formid_paths=args.known_formids,
                           max_gap=args.max_gap, unsuitable_diff_ratio=args.unsuitable_diff_ratio)
    write_reports(report, args.json, args.markdown)
    print(json.dumps({"result": report["result"], "reason": report["reason"],
                      "json": str(args.json), "markdown": str(args.markdown)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
