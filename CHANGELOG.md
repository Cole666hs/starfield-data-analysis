# Changelog — Starfield Data Analysis

## 1.6.0 — 2026-11-09

Player card completed, guard made field-aware, column width measured against
the real font. Read-only throughout: no save is written, repaired or
recompressed.

**Added**

- The Privacy Guard now resolves **which header field** a text actually
  carries. Every field is explicitly classified as identity, public or
  unknown; a field that is not declared stays unknown and is never released
  automatically. A new rule, `V4_IDENTITY_IN_PROTECTED_SINK`, reports an
  error when identity fields reach a diagnostic, status, export or error
  channel. The exception is granted to one concrete path — the player card —
  and not to a formatter as such. The resolution follows intermediate
  methods, so the guard sees the real chain in the application code.
  The guard is a static check; it is not a proof of runtime behaviour.
- Non-finite numbers are marked as such. `NaN`, `+inf` and `-inf` used to be
  formatted as ordinary numbers (`nan`, `inf`). They now show as
  `(nicht endlich) (NaN)` and the kind is named. Missing, empty, unassigned
  and non-finite values remain four distinguishable states. The decoded
  values themselves are untouched.

**Changed**

- The player card is no longer a fixed selection. Save time (raw value plus
  the UTC timestamp), created game version, header size, header body end,
  plugin block offset and size, and the previously unused header field are
  part of it now. The card is read-only and the text can be selected, so the
  values can be copied out.
- The list is driven by `PLAYER_VIEW_FIELDS` in
  `ssb_i/savegame_provider.py`. A parser field that is not classified there
  still appears (under its attribute name) and fails the coverage test in
  `tests/test_ssb_i_player_view.py`, so the card cannot quietly fall behind
  the parser.
- Values the save does not provide are marked as missing, empty or
  unassigned. No placeholder stands in for a measurement, and a code without
  a documented meaning (the gender field) is labelled as such.
- The two-column layout now measures its width with the font that is
  actually used (`QFontMetrics.horizontalAdvance`) instead of counting
  characters. A character that occupies two columns no longer shifts the
  right-hand column. On the test save the right column stays at the same
  pixel position for ASCII, CJK and emoji content.
- The stylesheets no longer name a single font family. A list of fallbacks
  ends in `monospace`. With the single name, Qt fell back to a proportional
  font on a system without that family, which shifted the columns by 77
  pixels on the widest row.
- The version is defined in one place only. `ssb_i.__version__` and
  `ssb_ui.__version__` are derived from `ssb_i.product.VERSION` now, so the
  package, the command line and the window title cannot report different
  versions.

**Fixed**

- Experience lost precision: 781.805 was displayed as 781.80. Three decimals
  now.
- The player card had no monospace style hint, so on systems without the
  bundled font family it fell back to a proportional font and the two
  columns drifted into each other.

**Privacy**

- The player card is the channel the user opens on purpose. Status line,
  header dump, export, CLI output and error texts are unchanged and still go
  through `public_header_view()`. `tests/test_ssb_i_player_view.py` checks
  both sides on the same header: the identity markers appear in the card and
  in none of the diagnostic channels.

**Interface**

- The user interface was unified: one accent colour instead of several
  decorative ones, semantic colours for the integrity status only, and
  neutral panels. The integrity view marks PASS, WARNING, FAILED, UNKNOWN
  and NOT_CHECKED differently. The theme still builds on qdarkstyle as a
  base; that base was not replaced.

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

- `docs/reports/SAVE_INTELLIGENCE_AUDIT.md`, `docs/reports/SAVE_INTELLIGENCE_SPEC.md`,
  `docs/reports/EXTERNAL_SAVEGAME_TOOLING_AUDIT.md` and
  `docs/reports/SAVE_FORMAT_AND_INTEGRITY_IMPLEMENTATION_REPORT.md`.

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
