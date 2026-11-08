# Changelog — Starfield Data Analysis

## 1.5.3 — 2026-11-08

Save format corrections and the first integrity layer. Read-only throughout: no
save is written, repaired or recompressed.

**Fixed**

- Plugin list now includes the **medium chain**. The previous version stopped
  after the light chain and reported `medium = 0`, which understated the total by
  five plugins on every tested save (75 instead of 80). The medium block is now
  read strictly and its end is verified byte-exactly against the declared block
  size.
- `decompress()` compares the result with the declared `uncompressed_size` by
  default. Two failure modes that previously passed silently are now rejected: a
  tampered size field and a doubled `chunk_size_pre`, the latter delivering only
  half of the payload while looking plausible.
- `save info --json` keeps the 1.0.0 field layout (numbers per chain) and adds
  `total`, `declared`, `categories`, `metadata`, `block` and `entries`, so
  existing consumers are unaffected.

**Added**

- **Plugin metadata**: `extraInfo`, `creationName`, `creationId`, `flags`
  (published as `version`) and `achievementFriendly` per entry. Entries are
  classified as `present`, `absent` or `unreadable`; the engine placeholder
  `18446744073709551615.undefined` is normalised to "no creation ID".
- **`sfda save verify`** with the status model PASS / WARNING / FAILED / UNKNOWN /
  NOT_CHECKED, per-check evidence, a separate coverage line and an explicit
  disclaimer that structural integrity is not proof of loadability. Exit code is
  non-zero on FAILED.
- **`sfda save strings`** — read-only access to the body string pool (verified on
  six retail saves: 1709–1735 entries, 99.6 % printable). It returns text and
  position only; no FormID, record or object identity is derived.
- **Integrity tab** and **String Pool tab** in the Savegame Analyzer, plugin
  counts per category, and creation metadata shown only when actually present.
- Real save games are now a **required** test fixture (`SAVE_PROBES`, default
  `~/ssb_probes`). Previously every test against a retail save was silently
  skipped.

**Docs**

- `SAVE_INTELLIGENCE_AUDIT.md`, `SAVE_INTELLIGENCE_SPEC.md`,
  `EXTERNAL_SAVEGAME_TOOLING_AUDIT.md` and
  `SAVE_FORMAT_AND_INTEGRITY_IMPLEMENTATION_REPORT.md`.

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
