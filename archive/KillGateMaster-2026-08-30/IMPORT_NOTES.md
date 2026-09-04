# KillGateMaster archive import notes

Source archive: `KillGateMaster 830 949pm - Copy.zip`

The archive was unpacked and inspected on 2026-09-04 before publication to the public GitHub repository.

## Archive inventory

- 8,746 files total
- approximately 168 MB unpacked
- 311 files are selected by the archive's own `.gitignore` rules
- approximately 7.72 MiB of selected files

## Deliberately excluded from public GitHub

The archive's own `.gitignore` excludes local configuration/credentials, Python virtual environments and caches, build/release output, Android packages, local databases, and tool state. Those exclusions were honored.

In particular, the following were not published:

- `runtime/.env.local`
- `.venv/` and other virtual-environment contents
- `.pytest_cache/` and `.ruff_cache/`
- `KillGate-1.2.0.aab`
- generated build/release artifacts ignored by the archive

`email_addresses.csv` was also withheld because it contains real personal email addresses and this repository is public.

## Import location

Archive material is kept under:

`archive/KillGateMaster-2026-08-30/`

This keeps the existing Killgate policy/gate files at the repository root intact and avoids overwriting the current project documentation.

## Connector limitation

The connected GitHub writer supports GitHub text-file and Git-object writes, but it does not expose a filesystem-directory upload or local binary-file upload operation. Binary assets in the unpacked archive therefore cannot be transferred directly from the local archive through this connector in a faithful bulk import.
