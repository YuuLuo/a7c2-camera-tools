# A7C II Camera Tools for Windows

[简体中文](README.zh-CN.md)

On the first run, choose **FL2/FL3**, **electronic shutter sound only**, or both. Sound can use the camera's original sample at its original level without an uploaded file. Custom sound accepts an MP3/WAV of up to 2 seconds and a **1–100%** level. Generated DAT files and manifests stay under `runtime/runs/<serial>/`.

The feature screen also offers **Skip NTSC startup notice** (default: Keep). It can be combined with any selection above and is saved with the per-camera plan. It skips the two selected NTSC message paths without changing PAL/NTSC settings. Existing runs retain their saved selection. This DAT port passed offline verification, and one A7C II user reported the mod working after QA on 2026-11-08. Detailed hardware coverage and recovery remain unverified. See [NTSC patch details](../native/NTSC.md).

The tool builds the selected version 2.00 package from an unmodified official ILCE-7CM2 2.01 `BODYDATA.DAT`. It backs up p1 and BK4, stages the package on the photo card, applies a temporary update gate and guides the camera menu update. It restores the original p1 afterward. FL2/FL3 selection also writes the live CP color table and checks both BK4 copies, writing either copy only if needed. Sound-only selection leaves these color properties unchanged.

The underlying workflow has been tested on Windows 10, Windows 11 and macOS with mainland China and Japanese-market bodies. On a research camera, the locally generated p1 patch completed its six-step apply and restore sequences and passed full p1 readback. After a cold boot, ST, FL, FL2 and FL3 playback icons and JPEG/ARW ColorMode values were checked as `0`, `18`, `22` and `23`. The generated 2.00 DAT passed full offline decryption and byte-by-byte verification. The separate macOS installer is under [`../macos/`](../macos/).

## Requirements

- Windows 10/11 x64, administrator access and Python 3.10 or newer. The first Python dependency install needs an internet connection.
- **Upgrade the ILCE-7CM2 to unmodified official 2.01 first.** Use a charged battery and an exFAT photo card larger than 32 GiB with at least 2.4 GiB free. Set USB Connection Mode to **Mass Storage (MSC)** and [USB LUN to Multi](https://helpguide.sony.net/ilc/2360/v1/en/contents/0601_usb_lun_setting.html) so Windows sees both the photo card and `PMHOME`.
- Download official 2.01 firmware from [Sony's ILCE-7CM2 support page](https://www.sony.com/electronics/support/product/ilce-7cm2/downloads). Put the extracted DAT beside `run.bat` as `ILCE-7CM2-v2.01-BODYDATA.DAT`. The tool checks its SHA-256. The repository contains neither official nor generated DAT files.
- Configure WinUSB before the first run. Download and open [Zadig](https://zadig.akeo.ie/), choose **Device → Load Preset Device**, and load [`runtime/tools/a7c2_service_0336.cfg`](runtime/tools/a7c2_service_0336.cfg). Confirm VID `054C`, PID `0336`, no MI and target driver **WinUSB** before installing. Reconnect the camera and rerun. Check the USB ID before changing any driver. The file format follows [Zadig's official preset guide](https://github.com/pbatard/libwdi/wiki/Zadig#example-of-a-zadig-preset-device-config-file).

When Windows binds the camera to WinUSB, the camera may display **“Check the connected device”** during service access. The photo card should reappear after the workflow restores USB Mass Storage and the camera reconnects.

## Run

Double-click `run.bat`, choose Chinese or English, then **Install or resume**. The first run creates `.venv` and installs dependencies. The interface shows the current step and progress; background steps continue automatically. It waits for input only when you need to handle USB, operate the camera or install a driver. The body starts at installed **2.01**, but the temporary version gate makes the update confirmation show **1.99 → 2.00** for up to 600 seconds. Execute only when the camera explicitly shows **1.99 → 2.00**.

Original backups, receipts and logs are stored by camera serial under `runtime/runs/<serial>/`. Keep that directory and the official DAT until cold-boot verification finishes. If an interrupted run reports a state mismatch, inspect its log before retrying. **Restore original p1 only** is available from the main menu if the temporary p1 patch was applied but the update cannot continue.

## Risks

This tool uses unofficial firmware. It temporarily modifies the camera's internal p1 partition and installs modified firmware; FL2/FL3 selection also changes color properties. A failed update, mismatched data or loss of power can prevent the camera from booting and may require hardware service. [Sony also warns about interrupted updates](https://www.sony.com/electronics/support/downloads/W0010781). Unauthorized changes may affect warranty coverage; check your region's terms ([US warranty example](https://www.sony.com/articleimage/servlet/servlet.FileDownload?file=0155F000007dHdmQAE)). Keep the original camera backups and use a charged battery.

Do not edit, or ask an AI to edit, camera memory, firmware, offsets, hashes or write scripts without the knowledge and tools to independently validate and recover the camera.

## Repository layout

| Path | Purpose |
| --- | --- |
| `run.bat`, `runtime/ui.py` | Launcher and bilingual interface |
| `runtime/a7c2_200_windows.py` | Resumable Windows workflow |
| `runtime/windows_*.py` | Camera communication, step verification and card handling |
| `runtime/release/` | Offline firmware builder and exact patch manifest |
| `runtime/core/` | Service protocol, p1 and BK4 workers, PMCA USB code |
| `runtime/cp_color_200/` | CP worker template and manifest |
| `runtime/tools/` | Driver INF/CAT and 0336 Zadig preset; download Zadig separately |
| `../native/` | Editable AArch64 worker sources and private-header generator |

Original project code is [GPL-3.0-only](../LICENSE). PMCA-derived code in `runtime/core/pmca/` retains its [MIT license](runtime/core/PMCA_LICENSE.txt); see [licenses and provenance](../THIRD_PARTY_NOTICES.md) for other files. The repository contains no official Sony DAT or camera-specific backups.
