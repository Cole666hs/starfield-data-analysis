# Nexus Mods — Beschreibungstext (Vorlage, nicht veröffentlicht)

**Name (Titel des Mod-Eintrags):** Starfield Data Analysis

**Summary (Feld „Kurzbeschreibung", max. 350 Zeichen):**

> Read-only inspection tools for Starfield saves and executables: plugin lists,
> save-to-save differentials, hex view and PE integrity checks. No game process
> is touched, no file is modified.

**Kategorie:** Utilities for Modders · **Spiel:** Starfield

---

## Beschreibung (Feld „Description")

**Starfield Data Analysis** — Advanced Starfield Inspection & Analysis Toolkit
by **Entropy Development**

A read-only toolkit for looking inside Starfield data files. It answers the
questions that come up while building or debugging a load order:

**Which plugins does this savegame actually use?**
Open a `.sfs` save and see the player, level, location, save version, game
version, the container layout and the plugin list — split into normal, light and
medium plugins, with native plugins marked.

**What changed between two savegames?**
Compare two saves byte by byte. You get the number of differing bytes, the
ratio, and the changed regions grouped into clusters, with an explicit verdict
whether the difference set is even interpretable. Export it as a JSON or
Markdown report.

**Is this Starfield.exe the file I think it is?**
Point the tool at any PE executable and get SHA-256, image base and the full
section table, plus a comparison against the documented hash of the unmodified
binary, so a patched or foreign build is recognisable at a glance.

**What is actually in there at offset 0x…?**
The hex view shows any loaded buffer as offset | hex | ASCII, with paging,
jump-to-offset and search for text or hex patterns. It works on the decoded
savegame or on any file you open directly.

### What you get in the package

- Graphical application with three pages: Savegame Analyzer, Hex Viewer, Event Log
- Command line program `sfda` with six commands and JSON output for scripting:
  `save info`, `save header`, `save plugins`, `save diff`, `pe info`, `pe sections`
- A headless self-test to verify the installation (`--self-test`)

### Requirements

- 64-bit Windows or Linux — use the package built for your system
- No Python installation needed
- Starfield itself is not required; the tools work on files

### Installation

Unpack the archive into any folder you can write to and run the application.
There is no installer, no registry entry and no background process. See
`INSTALL.md` in the package.

### Important notes

- **Read-only.** Every input file is opened read-only and never modified. This
  was verified by tracing a complete analysis run: no write access at all, and
  no Starfield or Steam path is touched.
- **No game process.** The tools never attach to, hook, patch or modify a running
  game.
- **Fail-closed.** If a plugin list cannot be decoded reliably, the tool says so
  (`UNVERIFIED` with a reason) instead of inventing data.
- **Scope of validation.** Verified against Starfield 1.16.244 (save version 153)
  and the matching executable. Other versions may work but are not verified.
- **Differentials are evidence, not interpretation.** The tool reports which bytes
  and regions differ; it does not claim which ship part, record or FormID that
  corresponds to.

### Credits and license

Savegame container layout cross-checked against the public work of the Starfield
save-tooling community. Built with Qt for Python (PySide6) and QDarkStyle.
Thanks to the Starfield modding community for documenting the formats.

MIT licensed — see `LICENSE.txt`. Copyright (c) 2026 Entropy Development.
