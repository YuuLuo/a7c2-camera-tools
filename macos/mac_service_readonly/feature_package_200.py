"""Build and identify the selected A7C II 2.00 feature package."""

import argparse
import json
from pathlib import Path

import sound_package_200 as sound

firmware = sound.firmware
MANIFEST_NAME = sound.MANIFEST_NAME
FL23_SHA = "a3076b2bf3b29ffa879bd35904e4002de10e669721b913796025b27bb5e138de"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def features(fl23, audio_mode, disable_ntsc_warning=False):
    require(type(disable_ntsc_warning) is bool and
            type(fl23) is bool and audio_mode in ("none", "stock", "custom") and
            (fl23 or audio_mode != "none"), "feature selection is empty or invalid")
    return (["fl2_fl3"] if fl23 else []) + (
        [] if audio_mode == "none" else ["electronic_shutter_sound"] +
        (["custom_audio"] if audio_mode == "custom" else [])) + (
        ["no_ntsc_notice_v2"] if disable_ntsc_warning else [])


def selected(manifest_path, audio=None):
    manifest_path = Path(manifest_path)
    require(not manifest_path.is_symlink() and manifest_path.name == MANIFEST_NAME and
            manifest_path.is_file(), "selected package manifest is missing or linked")
    report = json.loads(manifest_path.read_text(encoding="utf-8"))
    fl23 = report.get("fl23") if "fl23" in report else \
        "fl2_fl3" in report.get("feature_ids", [])
    mode = report.get("audio_mode")
    disable = report.get("disable_ntsc_warning", False)
    ids = features(fl23, mode, disable)
    require(report.get("format") == 2 and report.get("feature_ids") == ids and
            report.get("source_official_sha256") == firmware.SOURCE_SHA and
            report.get("package_version") == "2.00" and
            report.get("full_decrypt_verified") is True and
            report.get("output_size") == sound.PACKAGE_SIZE,
            "selected package manifest differs")
    if mode == "none" and not disable:
        output = Path(report.get("output_path", ""))
        require(fl23 and output.name == firmware.OUT_NAME and
                report.get("output_sha256") == FL23_SHA,
                "FL2/FL3 package identity differs")
    else:
        output = manifest_path.with_name(sound.OUTPUT_NAME)
        expected_base = FL23_SHA if fl23 else firmware.SOURCE_SHA
        require(report.get("base_package_sha256") == expected_base and
                report.get("ntsc_patch_spec_sha256") ==
                (sound.ntsc.SPEC_SHA if disable else None) and
                report.get("sound_patch_spec_sha256") == sound.SPEC_SHA and
                type(report.get("volume_percent")) is int and
                1 <= report["volume_percent"] <= 100 and
                (mode == "custom" or report["volume_percent"] == 100),
                "sound package identity differs")
        if mode == "stock":
            require(report.get("source_audio_sha256") is None and
                    report.get("encoded_audio_sha256") is None and
                    report.get("cp", {}).get("sys_sound_sha256") ==
                    sound.spec_data()["original_sys_sound_sha256"] and
                    report.get("registration_length_bytes") == 0x4c0,
                    "stock camera sound was changed")
        elif mode == "custom":
            require(all(isinstance(report.get(field), str) and
                        len(report[field]) == 64 for field in
                        ("source_audio_sha256", "encoded_audio_sha256")) and
                    isinstance(report.get("registration_length_bytes"), int) and
                    0 < report["registration_length_bytes"] <= 0xffff,
                    "custom sound proof differs")
            if audio is not None:
                require(firmware.sha_file(Path(audio)) ==
                        report["source_audio_sha256"],
                        "selected custom audio changed")
    if disable:
        sound.ntsc.spec_data()
        require(report.get("ntsc", {}).get("spec_sha256") == sound.ntsc.SPEC_SHA and
                report.get("ntsc", {}).get("windows") == 2,
                "NTSC patch verification differs")
    if mode == "none" and disable:
        require(report.get("source_audio_sha256") is None and
                report.get("encoded_audio_sha256") is None and
                report.get("registration_length_bytes") is None and
                "cp" not in report, "no-sound selection contains sound changes")
    require(not output.is_symlink() and output.is_file() and
            output.stat().st_size == sound.PACKAGE_SIZE and
            firmware.sha_file(output) == report.get("output_sha256"),
            "selected DAT full hash differs")
    return output, report["output_sha256"]


def check_plan(manifest_path, plan):
    """Bind a resumed package to the saved selection before update writes."""
    ids = features(plan["fl23"], plan["audio_mode"],
                   plan.get("disable_ntsc_warning", False))
    manifest_path = Path(manifest_path)
    require(not manifest_path.is_symlink() and manifest_path.is_file(),
            "saved feature package manifest is missing or linked")
    report = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(report.get("feature_ids") == ids and
            report.get("audio_mode") == plan["audio_mode"] and
            type(report.get("disable_ntsc_warning", False)) is bool and
            report.get("disable_ntsc_warning", False) ==
            plan.get("disable_ntsc_warning", False) and
            type(plan.get("volume_percent")) is int and
            report.get("volume_percent") == plan["volume_percent"] and
            (plan["audio_mode"] != "custom" or
             report.get("source_audio_sha256") == plan.get("audio_sha256")),
            "saved feature plan and selected package differ")


def build(official, run_dir, fl23, audio_mode, audio=None, volume_percent=100,
          disable_ntsc_warning=False):
    official, run_dir = Path(official), Path(run_dir)
    require(not official.is_symlink() and not run_dir.is_symlink(),
            "official DAT or run directory is a link")
    official, run_dir = official.resolve(), run_dir.resolve()
    ids = features(fl23, audio_mode, disable_ntsc_warning)
    require(official.is_file() and not official.is_symlink() and
            firmware.sha_file(official) == firmware.SOURCE_SHA and
            run_dir.is_dir() and not run_dir.is_symlink(),
            "official 2.01 or private run directory differs")
    manifest = run_dir / MANIFEST_NAME
    if audio_mode == "none" and not disable_ntsc_warning:
        require(audio is None and volume_percent == 100,
                "FL2/FL3-only selection has sound options")
        output = firmware.build(official)
        require(firmware.sha_file(output) == FL23_SHA,
                "FL2/FL3 output hash differs")
        report = {"format": 2, "feature_ids": ids, "fl23": True,
                  "audio_mode": "none", "volume_percent": 100,
                  "source_official_sha256": firmware.SOURCE_SHA,
                  "output_path": str(output), "output_sha256": FL23_SHA,
                  "output_size": sound.PACKAGE_SIZE,
                  "package_version": "2.00", "full_decrypt_verified": True,
                  "camera_access": False}
        if manifest.exists():
            require(json.loads(manifest.read_text(encoding="utf-8")) == report,
                    "existing selected feature plan differs")
        else:
            with manifest.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")
    else:
        output, report = sound.build(official, fl23, audio_mode, audio,
                                     volume_percent, run_dir / sound.OUTPUT_NAME,
                                     disable_ntsc_warning)
        require(report["feature_ids"] == ids, "built sound features differ")
    verified, digest = selected(manifest, audio)
    require(verified == output and digest == report["output_sha256"],
            "selected package does not match its builder")
    return verified, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--fl23", action="store_true")
    parser.add_argument("--disable-ntsc-warning", action="store_true")
    parser.add_argument("--audio-mode", choices=("none", "stock", "custom"),
                        required=True)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--volume", type=int, default=100)
    args = parser.parse_args()
    output, manifest = build(args.official, args.out_dir, args.fl23,
                             args.audio_mode, args.audio, args.volume,
                             args.disable_ntsc_warning)
    print(json.dumps({"event": "feature_package_200_built",
                      "output": str(output), "manifest": str(manifest),
                      "sha256": selected(manifest)[1],
                      "feature_ids": features(args.fl23, args.audio_mode,
                                              args.disable_ntsc_warning),
                      "camera_access": False}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser_error = f"error: {exc}"
        raise SystemExit(parser_error)
