# Which code produced the uploaded files

The three files on the mod page (Starfield, mod 18730) come from this repository. As uploaded:

| File id | Name | Bytes | SHA-256 |
|---|---|---|---|
| 73815 | 1.0.0 (Windows x64) | 50,456,628 | `fc1665c521f2295cfc9338f43a2a79db050b0d5adcfe4716bf8d0539455a98ee` |
| 73816 | 1.0.0 (Linux x64) | 112,574,033 | `1c8302304beef35089122924cf95aba41820996ac063d505066a472c3b6c47fd` |
| 73817 | 1.0.0 (source) | 64,297 | `5aa9af28415901ed0b8de00b948e86b92bd52d5582d85376b8b9cae734f9c0a6` |

The two binary packages were built on 5 November 2026 between 11:12 and 11:13 from this source tree.
The tree was committed shortly afterwards as `dcfb754` ("Release 1.0.0", 12:01). Four small commits
followed that touch only console output, the PyInstaller spec and tests, plus one documentation
commit that added `BUILD.md`, this file and moved test-fixture paths into environment variables. The
tag `v1.0.0` marks that current state, so it contains the same application code as the binaries plus
the extra documentation.

That means `dcfb754` is the commit the uploaded binaries were built from, and a build from the tag
gives you the identical application code.

PyInstaller builds are not bit-reproducible: the same commit built twice differs byte-wise (embedded
timestamps, archive ordering), so a rebuild will never reproduce the SHA-256 of a downloaded file.
That is a property of the packer, not a sign of a modified file. The `SHA256SUMS` inside each package
lets you confirm that a downloaded package is unmodified relative to itself.

To check the code rather than the binary, build from the tag and compare behaviour: `--version`,
`--dump-pages`, and the `save` and `pe` subcommands against a sample file.

The packages contain the two PyInstaller executables, the Qt6 runtime they link against, the project
documentation and a `SHA256SUMS`. There are no launcher scripts, no nested archives, and no
third-party code beyond PySide6, QDarkStyle and the Python standard library. The Python sources of
the application are exactly the `.py` files in this repository.

Entropy Development — the developer name on the mod page. Questions or findings: open an issue here.
