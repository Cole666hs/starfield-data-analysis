# Changelog — Starfield Data Analysis

## 1.0.0 — 2026-11-05

First public release by Entropy Development.

**Included**

- Savegame Analyzer: BCPS container and `SFS_SAVEGAME` header decoding, plugin
  list split into normal / light / medium, JSON report export.
- Savegame Differential: byte-level comparison of two saves with clusters and an
  explicit result assessment; Markdown report export.
- Hex Viewer: `offset | hex | ASCII` view of the decoded buffer or any file, with
  paging, jump-to-offset and text/hex search.
- PE inspection: SHA-256, image base, section table, optional `.pdata` function
  count, comparison against the documented trusted-root hash.
- Command line `sfda` with six documented commands and `--json` output.
- Headless self-test (`--self-test`, `--out`) for installation checks.

**Safety**

- All input files are opened read-only; verified by tracing a full analysis run.
- Fail-closed behaviour: unreadable plugin blocks are reported as `UNVERIFIED`
  instead of being guessed.

**Known limitations**

- Validated against Starfield 1.16.244 (save version 153) only.
- The differential reports bytes and regions, not parts or FormIDs.

**Not part of this release**

- AISC 3D preview (belongs to a separate project).
- Plugin configuration, DLL deployment, runtime capture (belong to the separate
  runtime module).
