# Reproducibility and file provenance

This file maps the files that were uploaded to Nexus Mods to the source in this repository, so the
files can be reviewed against the code that produced them.

## Files as uploaded to Nexus (mod 18730)

| Nexus file id | Name | Bytes | SHA-256 |
|---|---|---|---|
| 73815 | Starfield Data Analysis 1.0.0 (Windows x64) | 50,456,628 | `fc1665c521f2295cfc9338f43a2a79db050b0d5adcfe4716bf8d0539455a98ee` |
| 73816 | Starfield Data Analysis 1.0.0 (Linux x64) | 112,574,033 | `1c8302304beef35089122924cf95aba41820996ac063d505066a472c3b6c47fd` |
| 73817 | Starfield Data Analysis 1.0.0 (source) | 64,297 | `5aa9af28415901ed0b8de00b948e86b92bd52d5582d85376b8b9cae734f9c0a6` |

## Which source produced them

The two binary packages were built on **2026-11-05 between 11:12 and 11:13 (local time)** from this
source tree, **before the tree was committed**. The first commit (`dcfb754`, "Release 1.0.0",
2026-11-05 12:01) captures exactly that state; four follow-up commits (`cb08649`, `3fab3b0`,
`6df20e6`, `a2a84f9`) then touched only documentation, CLI output formatting, the PyInstaller spec
and tests.

Therefore:

* **Source of the uploaded binaries** = commit `dcfb754` (tag `v1.0.0`).
* **Current `main`** additionally contains the four follow-up commits. Nothing in them changes what
  the tool does with a savegame or an executable; they are console-output and packaging fixes plus
  tests.
* The source file uploaded as file id 73817 was archived from the same tree.

## How to check the code instead of the binary

1. Check out the release tag: `git checkout v1.0.0`
2. Follow `BUILD.md` (steps 2, 4, 5) to build and run.
3. Compare behaviour: `--version`, `--dump-pages`, and the CLI subcommands `save` / `pe` against a
   sample file.

**PyInstaller output is not bit-reproducible.** Two builds from the same commit differ byte-wise
(embedded timestamps and archive ordering), so a hash comparison of a rebuilt binary against the
uploaded one will never match — this is a property of the packer, not a sign of a modified file. The
checksum files inside the packages (`SHA256SUMS`) let you verify that the *downloaded* package is
unmodified relative to itself.

## What the packages contain

* the application executables produced by PyInstaller (GUI + CLI),
* the Qt6 runtime they link against (`_internal/`),
* the project documentation and `requirements.txt`,
* a `SHA256SUMS` listing every packaged file.

They contain **no** starter scripts, **no** nested archives, and no third-party code beyond
PySide6/QDarkStyle and the Python standard library. The Python sources of the application are exactly
the `.py` files in this repository.

## Contact

Entropy Development — the developer name on the mod page. Issues and questions: open an issue in this
repository.
