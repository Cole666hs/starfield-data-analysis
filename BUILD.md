# Building Starfield Data Analysis from source

This document is the build recipe for the released packages. It is written for someone who has
never seen the project: every command is copy-paste ready on **Windows (x64)** and **Linux (x64)**.

Verified with: **Python 3.13 and 3.14**, **PySide6 6.11.2**, **QDarkStyle 3.2.3**, **PyInstaller 6.22.2**.

---

## 1. Requirements

| Item | Version | Notes |
|---|---|---|
| Python | 3.13 or 3.14 (64-bit) | `python --version` |
| pip | current | ships with Python |
| PySide6 | 6.11.2 | Qt 6 runtime, installed by step 2 |
| QDarkStyle | 3.2.3 | theme, installed by step 2 |
| PyInstaller | 6.22.2 | only needed to produce the binary package |
| capstone | 5.0.7 | **optional**; without it every command still works, only `PE.verify_call_boundaries()` reports `capstone_or_section_unavailable` |

The tool itself has **no network code** and reads only the files you point it at.

## 2. Get the source and install dependencies

```bash
git clone https://github.com/Cole666hs/starfield-data-analysis.git
cd starfield-data-analysis

python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux:    source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install "pyinstaller==6.22.2" pytest
```

`requirements.txt` pins exactly the two runtime packages (`PySide6==6.11.2`, `QDarkStyle==3.2.3`)
and documents the optional ones.

## 3. Run the test suite (before building)

```bash
# Linux
QT_QPA_PLATFORM=offscreen python -m pytest tests -q

# Windows (cmd)
set QT_QPA_PLATFORM=offscreen
python -m pytest tests -q
```

Expected: **77 passed, 28 skipped** on a clean machine.

18 additional tests need real game artifacts that are **not** part of the repository. If you have
them, point these environment variables at your own copies and the same suite reports
**95 passed, 10 skipped**:

| Variable | What it must point at |
|---|---|
| `STARFIELD_ORIGINAL_EXE` | an unmodified `Starfield.exe` (trust-root binary for the PE tests) |
| `STARFIELD_EXE` | the installed `Starfield.exe` |
| `SDFA_REAL_SAVE` | a real `.sfs` savegame |

## 4. Build the application

The repository ships a PyInstaller spec file; no flags are needed beyond `--noconfirm --clean`:

```bash
pyinstaller --noconfirm --clean Starfield-Data-Analysis.spec
```

Result (PyInstaller "onedir" layout):

```
dist/
└── StarfieldDataAnalysis/
    ├── StarfieldDataAnalysis.exe   # GUI (Windows)  /  StarfieldDataAnalysis (Linux)
    ├── sfda.exe                    # command line   /  sfda (Linux)
    └── _internal/                  # Qt6 + Python runtime
```

Build time is roughly 60–70 seconds on a modern machine (Windows, PySide6 included).

## 5. Verify the build

```bash
# command line
dist/StarfieldDataAnalysis/sfda --version
# -> sfda 1.0.0 - Starfield Data Analysis (Entropy Development)

# GUI acceptance check without opening a window (writes the page inventory as ASCII)
dist/StarfieldDataAnalysis/StarfieldDataAnalysis --dump-pages --out pages.txt
cat pages.txt
# -> Starfield Data Analysis 1.0.0 (Entropy Development)
#    pages: 3
#      0: Savegame Analyzer  [SavegamePage]
#      1: Hex Viewer  [HexViewPage]
#      2: Event Log  [LogPage]
```

On Windows use `dist\StarfieldDataAnalysis\sfda.exe` and `...\StarfieldDataAnalysis.exe`.

## 6. Package it the way the released files are packaged

1. Copy `CHANGELOG.md`, `INSTALL.md`, `LICENSE.txt`, `README.md`, `requirements.txt` into
   `dist/StarfieldDataAnalysis/`.
2. Generate a checksum file next to them:

```bash
cd dist/StarfieldDataAnalysis
# Windows PowerShell
Get-ChildItem -Recurse -File | Where-Object { $_.Name -ne 'SHA256SUMS' } |
  ForEach-Object { "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.FullName.Substring((Get-Location).Path.Length + 1).Replace('\','/'))" } |
  Sort-Object | Set-Content -Encoding ASCII SHA256SUMS
# Linux
find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs -d '\n' sha256sum > SHA256SUMS
```

3. Zip the **folder** (not its contents) so the archive root is `StarfieldDataAnalysis/`.

## 7. What is inside the binary package

* one unsigned application executable per entry point (GUI + CLI), produced by PyInstaller;
* the Qt6 runtime it links against (`_internal/`);
* **no** starter/batch scripts, **no** packed bytecode archives of project code, **no** nested
  archives inside the package.

`PyInstaller` compresses Python modules into its own archive format by design — that is the standard
behaviour of every PyInstaller build, not an obfuscation step: the same modules are readable here in
the repository as plain `.py` files.

## 8. Notes

* **PyInstaller output is not bit-reproducible.** Two builds from the same commit produce
  functionally identical but byte-different binaries (embedded timestamps, ordering). Compare source
  and behaviour, not binary hashes.
* The build does not need network access and does not download anything at runtime.
* `LICENSE.txt` is MIT, © Entropy Development.
