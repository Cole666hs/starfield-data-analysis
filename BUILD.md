# Building from source

Everything below was run on Windows 10 (10.0.26200) with Python 3.14.6, PySide6 6.11.2 and
PyInstaller 6.22.2; the full build takes about 65 seconds. The same steps work on Linux x64.

1. Clone and create a virtual environment.

       git clone https://github.com/Cole666hs/starfield-data-analysis.git
       cd starfield-data-analysis
       python -m venv .venv
       .venv\Scripts\activate          # Windows
       source .venv/bin/activate       # Linux

2. Install the dependencies. `requirements.txt` pins `PySide6==6.11.2` and `QDarkStyle==3.2.3`; the
   only other things a build needs are PyInstaller and pytest.

       pip install -r requirements.txt
       pip install pyinstaller==6.22.2 pytest

   `capstone` is optional. Without it every command still works and only
   `PE.verify_call_boundaries()` reports `capstone_or_section_unavailable`.

3. Run the tests. Qt needs an offscreen platform on a machine without a display.

       QT_QPA_PLATFORM=offscreen python -m pytest tests -q          # Linux
       set QT_QPA_PLATFORM=offscreen && python -m pytest tests -q    # Windows cmd

   On a clean machine that is `77 passed, 28 skipped`. The tests behind those skips need real game
   files that are not part of the repository; point the variables below at your own copies and the
   run becomes `95 passed, 10 skipped`:

       STARFIELD_ORIGINAL_EXE   unmodified Starfield.exe (trust root for the PE tests)
       STARFIELD_EXE            the installed Starfield.exe
       SDFA_REAL_SAVE           a real .sfs savegame

4. Build. The spec file already contains the entry points and the Qt collection settings, so no extra
   flags are needed beyond a clean run.

       pyinstaller --noconfirm --clean Starfield-Data-Analysis.spec

   The result is the usual onedir layout under `dist/StarfieldDataAnalysis/`:
   `StarfieldDataAnalysis` (`.exe` on Windows) for the GUI, `sfda` (`.exe`) for the command line,
   and `_internal/` with the Qt runtime.

5. Check that the binaries work before you package them.

       dist/StarfieldDataAnalysis/sfda --version
       dist/StarfieldDataAnalysis/StarfieldDataAnalysis --dump-pages --out pages.txt

   `--version` prints `sfda 1.6.0 - Starfield Data Analysis (Entropy Development)`. `--dump-pages`
   writes the page inventory and exits without opening a window, which is what I use on a headless
   machine to prove a package is intact. On Windows, use the `.exe` paths.

6. Package it the way the released files are packaged: copy `CHANGELOG.md`, `INSTALL.md`,
   `LICENSE.txt`, `README.md` and `requirements.txt` into `dist/StarfieldDataAnalysis/`, write a
   `SHA256SUMS` next to them, and zip the folder itself so that `StarfieldDataAnalysis/` is the
   archive root.

Two things are worth knowing before comparing results. PyInstaller builds are not
bit-reproducible — two builds of the same commit differ byte-wise because of embedded timestamps and
archive ordering, so a rebuilt binary will never match the SHA-256 of a downloaded one. And nothing
in the build or at runtime needs network access.

Licence: MIT, see `LICENSE.txt`.
