# Starfield Data Analysis

**Advanced Starfield Inspection & Analysis Toolkit**
Developed by **Entropy Development**

A read-only toolkit for looking inside Starfield data files. It answers concrete
questions that come up while modding or troubleshooting a load order:

- Which plugins does this savegame actually use — and how many are light or medium?
- Are the plugins in two savegames the same, and what changed between them?
- Is this `Starfield.exe` the file I think it is, or a patched one?
- What does the raw data look like at a specific offset?

Nothing in this package writes to game files, patch processes, or modify a
savegame.

## What it is not

- Not a ship builder or ship editor. It does not place, move or create parts.
- Not a mod manager. It does not install, enable or sort plugins.
- No runtime hooks, no detours, no injection, no memory writes.

## Programs in this package

| Program | Purpose |
|---|---|
| `StarfieldDataAnalysis` | graphical interface (Savegame Analyzer, Hex Viewer, Event Log) |
| `sfda` | command line, same functions, scriptable, JSON output |

## Features

**Savegame Analyzer** — opens `.sfs` saves (BCPS container, `SFS_SAVEGAME`
header), shows player, level, location, game version, save version, chunk layout
and the plugin list split into normal / light / medium.

**Savegame Differential** — compares two savegames byte by byte and reports the
differing byte count, the ratio and the changed regions as clusters. Optionally
writes a Markdown report. The result includes an explicit assessment, and it
refuses to claim which ship part changed: a byte difference is evidence, not
interpretation.

**Hex Viewer** — shows any loaded buffer as `offset | hex | ASCII`, with paging,
jump-to-offset and search for text (`SOC_`) or hex (`4E 50 43`). Works on the
decoded savegame or on any file you open directly.

**PE inspection** — reads `Starfield.exe` (or any PE32+ binary): SHA-256, image
base, section table, optionally the `.pdata` function count, and a comparison
against the documented trusted-root hash so a patched binary is recognisable.

**Plugin metadata** — the plugin decoding is fail-closed: if the plugin block
cannot be read reliably, the tool reports `UNVERIFIED` with a reason instead of
inventing a list.

## Requirements

- 64-bit Windows or Linux (use the package built for your system).
- No Python installation required for the packaged build.
- Starfield itself is **not** required — the tools work on files.

## Installation

Unpack the archive anywhere you can write to and run the program. There is no
installer and no registry entry. See `INSTALL.md`.

## Command line

```
sfda --version
sfda save info    <save.sfs>            container, header, plugin counts
sfda save header  <save.sfs>            full SFS_SAVEGAME header
sfda save plugins <save.sfs>            plugin list, normal/light/medium
sfda save diff    <a.sfs> <b.sfs>       byte-level differential
sfda pe   info    <binary> [--pdata]    PE header, sections, SHA-256, trust root
sfda pe   sections <binary>             section table
```

Add `--json` for machine-readable output on stdout; errors and notes go to
stderr. Exit codes: `0` success, `1` analysis or input error, `2` usage error.

```
$ sfda save info "Save44_…_24_0_4.sfs"
File          Save44_…_24_0_4.sfs
Player        Cole (level 24)
Location      Jemison - New Atlantis
Save version  153
Game version  1.16.244.0
Playtime      2d.10h.38m.2 Tage.10 Stunden.38 Minuten
BCPS chunks   90
Decompressed  23,444,728 bytes
Plugins       VALIDATED | 24 normal | 50 light | 0 medium
Note: 24 normal (declared 24), 50 light, 0 medium; per-record metadata block NOT decoded
```

The `Playtime` line is reproduced verbatim from the save header. Starfield
stores that string in the language the save was written in.

## Safety

- Every input file is opened read-only.
- Verified by tracing a full analysis run: zero `O_WRONLY`/`O_CREAT`/`unlink`
  calls, and no Starfield or Steam path is touched.
- The only files written are the reports you export yourself.

## Known limitations

- Validated against Starfield 1.16.244 saves (save version 153) and the matching
  `Starfield.exe`. Other versions may work but are not verified.
- The differential reports changed bytes and regions; it does not identify which
  ship part, record or FormID changed.
- Plugin list decoding depends on the save's plugin block being readable; some
  saves report `UNVERIFIED` by design.
- The graphical interface does not create reports for the PE inspection (CLI
  only, `--json`).
- The build is platform-specific; there is no single cross-platform binary.

## Credits

- Savegame container layout cross-checked against the public work of the
  Starfield save-tooling community.
- Built with Qt for Python (PySide6) and QDarkStyle.
- Thanks to the Starfield modding community for documenting the data formats.

## License

MIT — see `LICENSE.txt`. Copyright (c) 2026 Entropy Development.
