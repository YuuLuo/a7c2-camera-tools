# Licenses and provenance

Original project code: Copyright (C) 2026 YuuLuo. Licensed under
GPL-3.0-only; see [LICENSE](LICENSE).

The following files retain their own copyright and license terms:

| Files | Origin | Terms |
| --- | --- | --- |
| `windows/runtime/core/pmca/`, `macos/mac_service_readonly/pmca/` | [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) by ma1co | MIT; see each platform's `PMCA_LICENSE.txt` |
| `windows/runtime/tools/*_winusb_export/*.inf` and `.cat` | Generated with [libwdi](https://github.com/pbatard/libwdi) by Pete Batard | LGPL; see [libwdi notice](licenses/libwdi-LGPL-3.0.txt) and upstream source |
| `ntsc_package_200.py`, `ntsc_patch_200.json` on both platforms, and `native/verify_ntsc_boot.py` | Instruction-window research from `a7c2-fl23-macos`, revision `41950d3eab53e0b801f315af07505a2d0d3f76af`, by MDHan and macOS adapter / A7C II preview contributors | MIT; see [upstream license](licenses/a7c2-fl23-macos-MIT.txt) |
| Firmware format and AES constants in the offline packagers | [fwtool.py](https://github.com/ma1co/fwtool.py) format research by ma1co | MIT; see [fwtool notice](licenses/fwtool-MIT.txt) |

The installer requires a user-supplied official ILCE-7CM2 2.01 DAT. It does
not include Sony firmware, camera backups, or complete firmware data blocks.
Optional audio conversion installs `imageio-ffmpeg` and its FFmpeg executable
as a Python dependency; these are not included in this source archive.
The FL2/FL3 color adjustments use a small set of functional compatibility
parameters derived from the official FX2 1.01 property and converted to the
A7C II property format. This provenance statement does not claim ownership of
Sony firmware or grant permission to redistribute it.
