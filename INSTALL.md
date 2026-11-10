# Installation — Starfield Data Analysis

Version 1.6.0 · Entropy Development

The package is a folder. There is nothing to install, no registry entry, no
service and no background process.

## Windows

1. Unpack the ZIP to a folder you can write to, for example
   `D:\Tools\StarfieldDataAnalysis`.
2. Start the graphical interface: double-click `StarfieldDataAnalysis.exe`.
3. Start the command line: open `cmd` in that folder and run `sfda.exe --help`.

Windows SmartScreen may warn that the program is not commonly downloaded. That
is expected for a new, unsigned build: choose *More info* → *Run anyway*. The
package is not code-signed.

Keep the folder together: the two `.exe` files and the `_internal` folder belong
to each other. Copy only the whole folder.

## Linux

```
unzip Starfield-Data-Analysis-1.6.0-linux-x86_64.zip -d StarfieldDataAnalysis
cd StarfieldDataAnalysis/StarfieldDataAnalysis
./StarfieldDataAnalysis          # GUI (needs a graphical session)
./sfda --help                    # CLI
```

If the files lost their executable bit while unzipping:
`chmod +x StarfieldDataAnalysis sfda`.

## First check after unpacking

A headless self-test confirms that the package works on your machine:

```
StarfieldDataAnalysis.exe --self-test "C:\path\to\save.sfs" --out result.txt
```

The GUI program has no console on Windows, so the result is written to the file
you pass with `--out`. Exit code `0` means PASS, `1` means FAIL.

```
SELF_TEST player='Cole' level=24 game=1.16.244.0 save_version=153
SELF_TEST header_fields=18 decompressed_bytes=23444728
SELF_TEST plugins state=VALIDATED normal=24 light=50 medium=0
SELF_TEST PASS
```

The command line prints the same information directly:

```
sfda --version
sfda save info "C:\path\to\save.sfs"
```

## Where the program reads and writes

- Reads: only the file you open (a `.sfs` save, a binary for the PE commands, or
  any file for the hex view).
- Writes: only report files you export yourself. No temporary files, no
  configuration in your home directory, no writes to game directories.

## Uninstalling

Delete the folder.
