# A7C II Camera Tools for macOS

[简体中文](README.zh-CN.md)

Use macOS with Python 3.10 or newer and an internet connection for the first dependency install. Place your unmodified official A7C II 2.01 DAT beside `run.command` as `ILCE-7CM2-v2.01-BODYDATA.DAT`. Set the camera to USB Mass Storage with USB LUN **Multi**, connect a camera-formatted exFAT photo card, and use a charged battery.

Open `run.command`, choose English or Chinese, then **Install or resume**. The launcher creates its own Python environment and installs the required packages, including libusb. macOS does not need a Zadig driver. The interface pauses for camera actions and keeps per-camera backups, logs and resume state under `mac_service_readonly/runs/<serial>/`.

Choose FL2/FL3, electronic shutter sound only, or both. Sound can use the built-in sample with no file, or a user MP3/WAV up to 2 seconds at 1–100% custom level. The built-in sample keeps its original level. A sound-only installation restores p1 and checks the version after a cold boot without writing FL2/FL3 color properties.

The feature screen also offers **Skip NTSC startup notice** (default: Keep). It can be combined with any selection above and is saved with the per-camera plan. It skips the two selected NTSC message paths without changing PAL/NTSC settings. Existing runs retain their saved selection. This DAT port passed offline verification, and one A7C II user reported the mod working after QA on 2026-11-08. Detailed hardware coverage and recovery remain unverified. See [NTSC patch details](../native/NTSC.md).

The body starts at official 2.01. The temporary update gate makes the camera confirmation show **1.99 → 2.00**. Execute only when those numbers appear. Keep the `runs` directory and official DAT until the final check finishes.
