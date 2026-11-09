# A7C II Camera Tools

[简体中文](README.zh-CN.md)

Research and reproducible firmware tools for the Sony ILCE-7CM2. The installer builds a version 2.00 package from a user-supplied, unmodified official 2.01 DAT; the normal official 2.01 update path remains available afterward.

## Features

| Selection | Firmware changes | Post-update work |
| --- | --- | --- |
| FL2/FL3 | Enables the two Creative Look modes, playback icons and photo metadata | Writes the live CP color table and checks both BK4 copies |
| Electronic shutter sound | Enables the capture sound path and two sound menu choices | Uses the camera's built-in sound or user audio; leaves FL2/FL3 color properties unchanged |
| Both | Combines both sets of changes in one DAT | Performs the FL2/FL3 color steps and checks the sound |

Sound can use the camera's original sample at its original level without an uploaded file. Custom sound accepts an MP3/WAV of up to 2 seconds and a **1–100%** level.

The feature screen also offers **Skip NTSC startup notice** (default: Keep). It can be combined with any selection above and is saved with the per-camera plan. It skips the two selected NTSC message paths without changing PAL/NTSC settings. Existing runs retain their saved selection. This DAT port passed offline verification, and one A7C II user reported the mod working after QA on 2026-11-08. Detailed hardware coverage and recovery remain unverified. See [NTSC patch details](native/NTSC.md).

## How it works

1. The camera connects in USB Mass Storage mode (`054C:0E8A`). The host authenticates and switches it to service mode (`054C:0336`), where Jiritsu file commands are available.
2. A bounded AArch64 worker is staged in the camera's Work area. Service commands set a preload entry and trigger a child process. The host checks the versioned, checksummed result, removes the preload entry and verifies the return to normal USB mode. See the [service probes](windows/runtime/core/sony-service-research/).
3. Read-only captures of p1 and both BK4 copies establish the camera baseline. The selected 2.00 DAT is fully decrypted for verification, copied to the photo card and read back by full hash. A temporary p1 patch opens the update version gate; the original p1 is restored after the camera update.
4. FL2/FL3 connects mode paths already present in the camera and supplies four color-property rows converted from FX2-format functional parameters. The sound patch connects the camera's existing KindID 3 shutter sample. Custom mode also extends `SYSSOUND.BIN` and updates sound registration in the main application and boot overlay.

A7C II 2.01 already contains FL2/FL3 menu resources and shared processing code. This project enables the missing routing and supplies color parameters; it does not transplant the full FX2 imaging program.

## Run

| Platform | Entry |
| --- | --- |
| Windows 10/11 | [windows/run.bat](windows/run.bat) · [setup](windows/README.md) |
| macOS | [macos/run.command](macos/run.command) |

Place your own official 2.01 DAT beside the launcher. Both platforms use a fixed-screen Chinese/English interface and save per-camera resume records. The workflow has run on Windows 10, Windows 11 and macOS with mainland China and Japanese-market bodies.

The repository contains project code, patch descriptions and driver files, but no Sony firmware, camera captures, generated DAT, user audio or run logs. Original project code is [GPL-3.0-only](LICENSE); see [licenses and provenance](THIRD_PARTY_NOTICES.md) for other components.

Compatibility testing passed on nearly ten A7C II cameras without boot problems. Unofficial firmware can still affect warranty or prevent a camera from booting. **Do not use this tool if you are unwilling to accept those risks.** Keep your camera-specific backups and use a charged battery. Do not alter firmware offsets, hashes, memory access or write steps without independent validation and recovery capability.
