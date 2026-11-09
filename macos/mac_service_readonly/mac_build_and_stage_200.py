#!/usr/bin/env python3
"""Build the selected 2.00 package and verify its copy on this camera card."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import fl23_package_200 as package
import feature_package_200 as feature_package
import mac_probe_fl23 as probe
import run_backup_snapshot_ro as identity

PACKAGE_SIZE = 1_139_929_560


def require(ok, message):
    if not ok:
        raise ValueError(message)


def official_source(explicit):
    if explicit is not None:
        require(explicit.is_file() and package.sha_file(explicit) == package.SOURCE_SHA,
                "selected file is not untouched A7C II official 2.01 DAT")
        return explicit.resolve()
    preferred = Path.cwd() / package.SOURCE_NAME
    if preferred.is_file() and package.sha_file(preferred) == package.SOURCE_SHA:
        return preferred.resolve()
    matches = [item for item in Path.cwd().glob("*.DAT")
               if item.name != package.OUT_NAME and
               package.sha_file(item) == package.SOURCE_SHA]
    require(len(matches) == 1,
            "place exactly one official A7C II 2.01 DAT in this directory or pass --official")
    return matches[0].resolve()


def current_card(camera, card, pmhome):
    identity.wait_for_camera_volumes(camera, card, pmhome)
    volumes = probe.volume_inventory()
    require(not volumes.get("error"), "diskutil card inventory failed")
    found = []
    for item in volumes.get("external_disks", []):
        disk = item.get("disk", {})
        if (disk.get("BusProtocol") != "USB" or disk.get("Internal") is not False or
                disk.get("RemovableMedia") is not True or
                disk.get("Writable") is not True or
                disk.get("TotalSize") != card[0].get("TotalSize") or
                disk.get("MediaName") != card[0].get("MediaName")):
            continue
        for part in item.get("partitions", []):
            if (part.get("VolumeUUID") == card[1].get("VolumeUUID") and
                    part.get("FilesystemName") == "ExFAT" and
                    part.get("DeviceIdentifier") and
                    part.get("VolumeName") == card[1].get("VolumeName")):
                found.append(part)
    require(len(found) == 1, "camera photo card identity is ambiguous")
    part = found[0]
    if not part.get("MountPoint"):
        identifier = part["DeviceIdentifier"]
        require(re.fullmatch(r"disk[0-9]+s[0-9]+", identifier) is not None,
                "unexpected camera card partition identifier")
        result = subprocess.run(["diskutil", "mount", identifier],
                                capture_output=True, text=True, timeout=45)
        require(result.returncode == 0,
                "cannot mount verified camera photo card: " + result.stderr[:200])
        mounted = identity.wait_for_camera_volumes(camera, card, pmhome)
        matches = [entry for entry in mounted if
                   entry.get("VolumeUUID") == card[1]["VolumeUUID"]]
        require(len(matches) == 1 and matches[0].get("MountPoint"),
                "camera photo card did not mount with the same UUID")
        part = matches[0]
    root = Path(part["MountPoint"]).resolve()
    require(root.is_dir() and (root / "DCIM").is_dir() and
            part.get("Writable") is True,
            "identified photo card is not writable or camera formatted")
    return root, part


def stage(output, mountpoint, card_uuid, selected_sha):
    active = mountpoint / "BODYDATA.DAT"
    old_backup = mountpoint / "BODYDATA_official201_backup.DAT"
    temp = mountpoint / "BODYDATA.FEATURES.COPYING"
    require(not temp.exists() and not temp.is_symlink(),
            "stale card copy exists; inspect before retry")
    if active.exists() or active.is_symlink():
        info = active.lstat()
        require(stat.S_ISREG(info.st_mode), "existing card BODYDATA.DAT is not a regular file")
        active_sha = package.sha_file(active)
        if active_sha == selected_sha:
            print("card_bodydata_200_already_verified:", selected_sha, flush=True)
            return
        require(active_sha == package.SOURCE_SHA and not old_backup.exists(),
                "existing active DAT is neither official 2.01 nor this verified 2.00")
    print("camera_card_uuid:", card_uuid, flush=True)
    print("package_sha256:", selected_sha, flush=True)
    moved_old = False
    promoted = False
    try:
        with output.open("rb") as src, temp.open("xb") as dst:
            shutil.copyfileobj(src, dst, 8 << 20)
            dst.flush()
            os.fsync(dst.fileno())
        require(temp.stat().st_size == PACKAGE_SIZE and
                package.sha_file(temp) == selected_sha,
                "copied DAT full card readback differs")
        if active.exists():
            active.rename(old_backup)
            moved_old = True
        temp.rename(active)
        promoted = True
        require(package.sha_file(active) == selected_sha,
                "active DAT full card readback differs")
    except BaseException:
        if temp.exists():
            temp.unlink()
        if promoted and active.exists():
            active.unlink()
        if moved_old and not active.exists():
            old_backup.rename(active)
        raise
    print("card_bodydata_200_verified:", selected_sha, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path)
    parser.add_argument("--probe-json", type=Path, required=True)
    parser.add_argument("--fl23", action="store_true")
    parser.add_argument("--disable-ntsc-warning", action="store_true")
    parser.add_argument("--audio-mode", choices=("none", "stock", "custom"),
                        required=True)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--volume", type=int, default=100)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    require(sys.platform == "darwin", "macOS required")
    feature_package.features(args.fl23, args.audio_mode, args.disable_ntsc_warning)
    require((args.audio is None) == (args.audio_mode != "custom"),
            "custom audio selection differs")
    source = official_source(args.official)
    report = json.loads(args.probe_json.read_text(encoding="utf-8"))
    camera, card, pmhome = identity.report_identity(report)
    require(args.out_dir.resolve() == ROOT / "runs" / camera["serial_num"],
            "selected package must stay in this camera's private run directory")
    if not args.execute:
        print(json.dumps({"camera_access": False, "official_sha256": package.SOURCE_SHA,
                          "feature_ids": feature_package.features(
                              args.fl23, args.audio_mode, args.disable_ntsc_warning),
                          "camera_serial": camera["serial_num"],
                          "card_uuid": card[1]["VolumeUUID"]}))
        return 0
    print("building_and_independently_verifying_2.00_DAT", flush=True)
    require(shutil.disk_usage(source.parent).free > 2 * PACKAGE_SIZE + 1_000_000_000,
            "too little free disk space for complete DAT build and verification")
    output, manifest = feature_package.build(
        source, args.out_dir, args.fl23, args.audio_mode, args.audio,
        args.volume, args.disable_ntsc_warning)
    output, selected_sha = feature_package.selected(manifest, args.audio)
    mountpoint, _ = current_card(camera, card, pmhome)
    require(shutil.disk_usage(mountpoint).free > PACKAGE_SIZE + 100_000_000,
            "camera photo card has too little free space")
    stage(output, mountpoint, card[1]["VolumeUUID"], selected_sha)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("error:", exc, file=sys.stderr)
        raise SystemExit(1)
