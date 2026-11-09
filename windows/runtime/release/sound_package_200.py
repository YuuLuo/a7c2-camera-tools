#!/usr/bin/env python3
"""Build an optional A7C II 2.00 electronic shutter sound from user audio."""

import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

import numpy as np

import ntsc_package_200 as ntsc

ROOT = Path(__file__).resolve().parent
if (ROOT / "fl23_windows.py").is_file():
    import fl23_windows as firmware
else:
    import fl23_package_200 as firmware

SPEC_PATH = ROOT / "sound_patch_200.json"
SPEC_SHA = "a7a3ca439c24ff03612ba9e9482387db8ccc4308233830138b0061067c4ac290"
OUTPUT_NAME = "BODYDATA_FEATURES_200.DAT"
MANIFEST_NAME = "selected_package_200.json"
PACKAGE_SIZE = 1_139_929_560
CLUSTER_SIZE = 0x4000
TESTED_REGISTRATION_BYTES = 47_776
OFFICIAL_PLAIN_SHA = "03eee07301010ff644fae1073f7c7f6dd2d60278f18aa3e6053938d5f1426d1f"
OFFICIAL_P8_SHA = "8700f570aed3eb32038f313590759736a06162f402637518f8078dd51b6f1541"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def spec_data():
    raw = SPEC_PATH.read_bytes()
    require(sha(raw) == SPEC_SHA, "sound patch manifest differs")
    data = json.loads(raw)
    require(data["format"] == 1 and data["feature"] ==
            "custom_electronic_shutter_sound" and
            data["source_package_sha256"] ==
            "a3076b2bf3b29ffa879bd35904e4002de10e669721b913796025b27bb5e138de" and
            data["source_plain_sha256"] == firmware.TARGET_200_PLAIN_SHA and
            data["audio"]["rate"] == 24_000 and
            data["audio"]["max_seconds"] == 2 and
            data["audio"]["samples_per_frame"] == 31 and
            data["audio"]["frame_bytes"] == 32 and
            data["audio"]["control"] == 5 and
            data["cp"]["append_cluster_pool"] == [1251, 1252, 1253] and
            len(data["app_spans"]) == 8 and len(data["wbi_spans"]) == 6,
            "sound patch manifest identity differs")
    return data


def ffmpeg_executable():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        path = shutil.which("ffmpeg")
        require(path is not None, "FFmpeg is required for custom sound")
        return path


def encode_audio(source, settings, volume_percent=100):
    require(type(volume_percent) is int and 1 <= volume_percent <= 100,
            "custom audio volume must be 1..100 percent")
    source = Path(source)
    require(not source.is_symlink(), "audio file must not be a link")
    source = source.resolve()
    require(source.is_file() and
            source.suffix.lower() in (".mp3", ".wav") and
            0 < source.stat().st_size <= 50_000_000,
            "audio file missing, linked, empty or too large")
    command = [ffmpeg_executable(), "-nostdin", "-loglevel", "error",
               "-i", str(source), "-map", "0:a:0", "-vn", "-ac", "1",
               "-ar", str(settings["rate"]), "-t", "2.1", "-f", "f32le", "pipe:1"]
    try:
        result = subprocess.run(command, capture_output=True, timeout=45,
                                check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("audio decoding timed out") from exc
    require(result.returncode == 0 and len(result.stdout) % 4 == 0,
            "audio decoding failed: " + result.stderr.decode(errors="replace")[-200:])
    samples = np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)
    require(0 < samples.size <= settings["rate"] * settings["max_seconds"] and
            np.isfinite(samples).all(),
            "audio must be nonempty and at most 2 seconds")
    source_samples = int(samples.size)
    maximum = float(np.max(np.abs(samples)))
    require(maximum > 0, "audio contains only silence")
    signed = np.rint(samples * (settings["peak"] * volume_percent / 100 / maximum)).clip(
        -128, 127).astype(np.int8)
    frame_count = (source_samples + settings["samples_per_frame"] - 1) // settings["samples_per_frame"]
    capacity = frame_count * settings["samples_per_frame"]
    payload_bytes = frame_count * settings["frame_bytes"]
    require(payload_bytes <= 0xffff, "sound registration length exceeds one MOVZ immediate")
    padded = np.zeros(capacity, dtype=np.int8)
    padded[:len(signed)] = signed
    output = bytearray(payload_bytes)
    for frame in range(frame_count):
        offset = frame * settings["frame_bytes"]
        output[offset] = settings["control"]
        output[offset + 1:offset + settings["frame_bytes"]] = padded[
            frame * settings["samples_per_frame"]:
            (frame + 1) * settings["samples_per_frame"]].tobytes()
    require(len(output) == payload_bytes, "sound frame count differs")
    return bytes(output), {"source_audio_sha256": firmware.sha_file(source),
                           "encoded_audio_sha256": sha(output),
                           "volume_percent": volume_percent,
                           "samples": source_samples,
                           "duration_seconds": round(source_samples / settings["rate"], 6),
                           "resource_duration_seconds": round(capacity / settings["rate"], 6),
                           "frame_count": frame_count,
                           "tail_padding_samples": capacity - source_samples,
                           "payload_bytes": payload_bytes}


def fat12_get(fat, cluster):
    offset = cluster + cluster // 2
    value = fat[offset] | fat[offset + 1] << 8
    return (value >> 4 if cluster & 1 else value) & 0xfff


def fat12_set(fat, cluster, value):
    require(0 <= value <= 0xfff, "FAT12 cluster value differs")
    offset = cluster + cluster // 2
    if cluster & 1:
        fat[offset] = (fat[offset] & 0x0f) | ((value & 0x0f) << 4)
        fat[offset + 1] = value >> 4
    else:
        fat[offset] = value & 0xff
        fat[offset + 1] = (fat[offset + 1] & 0xf0) | (value >> 8)


def sound_file(image):
    fat = image[0x4000:0x8000]
    require(fat == image[0x8000:0xc000] and
            image[510:512] == b"\x55\xaa", "CP FAT12 copies or boot sector differ")
    root = 0xc000
    matches = [root + index * 32 for index in range(512)
               if image[root + index * 32:root + index * 32 + 11] ==
               b"SYSSOUNDBIN"]
    require(len(matches) == 1, "SYSSOUND.BIN root entry differs")
    entry_at = matches[0]
    length = struct.unpack_from("<I", image, entry_at + 28)[0]
    cluster = struct.unpack_from("<H", image, entry_at + 26)[0]
    chain, content = [], bytearray()
    while cluster < 0xff8:
        require(2 <= cluster < 1500 and cluster not in chain,
                "SYSSOUND.BIN cluster chain differs")
        chain.append(cluster)
        start = 0x10000 + (cluster - 2) * CLUSTER_SIZE
        content.extend(image[start:start + CLUSTER_SIZE])
        cluster = fat12_get(fat, cluster)
    require(cluster == 0xfff and len(content) >= length,
            "SYSSOUND.BIN end-of-chain differs")
    return bytes(content[:length]), chain, entry_at


def patch_cp(image, audio, data, source_sha):
    expected = data["cp"]
    require(len(image) == expected["partition_size"] and
            sha(image) == source_sha, "2.00 CP partition differs")
    original, chain, entry_at = sound_file(image)
    require(len(original) == expected["sys_sound_original_size"] and
            sha(original) == data["original_sys_sound_sha256"] and
            chain == expected["sys_sound_chain_before"],
            "official system sound file differs")
    patched = bytearray(image)
    extended = original if audio is None else original + audio
    new_chain = chain
    if audio is not None:
        required_clusters = (len(extended) + CLUSTER_SIZE - 1) // CLUSTER_SIZE
        additional = required_clusters - len(chain)
        pool = expected["append_cluster_pool"]
        require(0 <= additional <= len(pool) and len(audio) % 32 == 0 and
                len(audio) <= 0xffff,
                "sound file exceeds verified FAT or registration capacity")
        new_chain = chain + pool[:additional]
        require(new_chain[:len(chain)] == chain and
                len(new_chain) == required_clusters and
                all(0x10000 + (cluster - 1) * CLUSTER_SIZE <= len(image)
                    for cluster in new_chain),
                "sound file cluster geometry differs")
        for cluster in new_chain[len(chain):]:
            require(fat12_get(image[0x4000:0x8000], cluster) == 0,
                    "required CP sound cluster is occupied")
        tail = len(original) - (len(chain) - 1) * CLUSTER_SIZE
        require(tail == 832, "original sound tail alignment differs")
        for index, cluster in enumerate(new_chain):
            start = 0x10000 + (cluster - 2) * CLUSTER_SIZE
            segment = extended[index * CLUSTER_SIZE:(index + 1) * CLUSTER_SIZE]
            if index == len(chain) - 1:
                require(patched[start:start + tail] == original[-tail:],
                        "original system sound tail differs")
                patched[start + tail:start + len(segment)] = segment[tail:]
            elif index >= len(chain):
                patched[start:start + CLUSTER_SIZE] = segment.ljust(CLUSTER_SIZE, b"\0")
        for fat_start in (0x4000, 0x8000):
            fat = bytearray(patched[fat_start:fat_start + 0x4000])
            for index in range(len(chain) - 1, len(new_chain) - 1):
                fat12_set(fat, new_chain[index], new_chain[index + 1])
            fat12_set(fat, new_chain[-1], 0xfff)
            patched[fat_start:fat_start + 0x4000] = fat
        struct.pack_into("<I", patched, entry_at + 28, len(extended))
    trigger = expected["trigger_partition_offset"]
    old = bytes(patched[trigger:trigger + 1])
    require(sha(old) == expected["trigger_old_sha256"],
            "CP shutter trigger source differs")
    patched[trigger] = int(expected["trigger_new"], 16)
    final, final_chain, final_entry = sound_file(patched)
    require(final == extended and final_chain == new_chain and
            final_entry == entry_at and
            patched[0x10000 + (chain[0] - 2) * CLUSTER_SIZE:
                    0x10000 + (chain[0] - 2) * CLUSTER_SIZE + len(original)] == original,
            "extended system sound readback differs")
    return bytes(patched), {"source_sha256": sha(image),
                            "target_sha256": sha(patched),
                            "sys_sound_sha256": sha(extended),
                            "appended_audio_sha256": sha(audio) if audio is not None else None,
                            "chain": new_chain, "file_size": len(extended),
                            "registered_audio_bytes": len(audio) if audio is not None else
                            0x4c0}


def replacement_for(item, audio_length):
    replacement = bytes.fromhex(item["new"])
    if item["name"] != "registration_cave":
        return replacement
    reference = struct.pack("<I", 0xd2800009 | (TESTED_REGISTRATION_BYTES << 5))
    require(len(replacement) == 20 and replacement[:4] == reference and
            0 < audio_length <= 0xffff and audio_length % 32 == 0,
            "sound registration instruction template differs")
    return struct.pack("<I", 0xd2800009 | (audio_length << 5)) + replacement[4:]


def patch_plain(plain, data, audio, fl23):
    p15, p5, p8, listing = firmware.tar_parts(plain)
    with plain.open("r+b") as stream:
        mm = mmap.mmap(stream.fileno(), 0)
        try:
            require(mm[0x20:0x22] == b"\0\x02",
                    "base package version is not 2.00")
            partitions = ((b"dev/nflasha15,", p15),
                          (b"dev/nflasha5,", p5),
                          (b"dev/nflasha8,", p8))
            old_crc = {label: firmware.crc_window(mm, part.offset_data,
                                                  part.size)
                       for label, part in partitions}
            changed = []
            app_changes = []
            app_spans = [item for item in data["app_spans"]
                         if audio is not None or not item["name"].startswith("registration_")]
            wbi_spans = [item for item in data["wbi_spans"]
                         if audio is not None or not item["name"].startswith("registration_")]
            for item in app_spans:
                at = p15.offset_data + item["partition_relative_offset"]
                marker_at = at - 64
                marker = mm[marker_at:marker_at + item["source_context_size"]]
                replacement = replacement_for(item, len(audio) if audio else 0)
                before = bytes(mm[at:at + len(replacement)])
                require(marker_at >= p15.offset_data and
                        marker_at + len(marker) <= p15.offset_data + p15.size and
                        sha(marker) == item["source_context_sha256"] and
                        sha(before) == item["old_sha256"] and
                        before != replacement, item["name"] + " app source differs")
                app_changes.append((at, replacement))
                changed.append(item["name"])
            for at, replacement in app_changes:
                mm[at:at + len(replacement)] = replacement
            for item in wbi_spans:
                at = p5.offset_data + item["partition_relative_offset"]
                replacement = replacement_for(item, len(audio) if audio else 0)
                before = bytes(mm[at:at + len(replacement)])
                require(p5.offset_data <= at and
                        at + len(replacement) <= p5.offset_data + p5.size and
                        sha(before) == item["old_sha256"] and
                        before != replacement, item["name"] + " WBI2 source differs")
                mm[at:at + len(replacement)] = replacement
                changed.append(item["name"] + "_WBI2")
            cp_source = bytes(mm[p8.offset_data:p8.offset_data + p8.size])
            cp_target, cp_report = patch_cp(
                cp_source, audio, data,
                data["source_cp_partition_sha256"] if fl23 else OFFICIAL_P8_SHA)
            mm[p8.offset_data:p8.offset_data + p8.size] = cp_target
            listed = bytes(mm[listing.offset_data:listing.offset_data + listing.size])
            crc_report = {}
            for label, part in partitions:
                lines = [line for line in listed.splitlines() if line.endswith(label)]
                require(len(lines) == 1 and lines[0].startswith(b"0,") and
                        len(lines[0][2:10]) == 8,
                        "partition checksum entry differs")
                before = int(lines[0][2:10], 16)
                require(before == old_crc[label],
                        "base package partition checksum differs")
                after = firmware.crc_window(mm, part.offset_data, part.size)
                crc_at = listing.offset_data + listed.find(lines[0]) + 2
                mm[crc_at:crc_at + 8] = f"{after:08x}".encode()
                crc_report[label.decode()] = {"old": f"{before:08x}",
                                              "new": f"{after:08x}"}
            mm.flush()
            return {"patches": changed, "cp": cp_report,
                    "partition_crc32": crc_report}
        finally:
            mm.close()


def verify_roundtrip(output, expected_plain, layout):
    require(firmware.parse_dat(output) == layout,
            "sound package DAT layout or CRC differs")
    with expected_plain.open("rb") as expected:
        for block in firmware.decoded_blocks(output, layout):
            require(expected.read(len(block)) == block,
                    "sound package full decrypt differs")
        require(expected.read(1) == b"", "sound package plaintext length differs")


def version_only(plain):
    with plain.open("r+b") as stream:
        mm = mmap.mmap(stream.fileno(), 0)
        try:
            require(mm[0x20:0x22] == b"\x01\x02",
                    "source plaintext version is not 2.01")
            mm[0x20:0x22] = b"\x00\x02"
            mm[8:12] = struct.pack("<I", zlib.crc32(mm[12:0x200]) & 0xffffffff)
            mm.flush()
        finally:
            mm.close()


def build(official, fl23, audio_mode, audio_source=None, volume_percent=100,
          output=None, disable_ntsc_warning=False):
    official = Path(official)
    require(not official.is_symlink(), "official package is a link")
    official = official.resolve()
    require(official.is_file() and firmware.sha_file(official) == firmware.SOURCE_SHA,
            "unmodified official 2.01 package required")
    require(type(fl23) is bool and audio_mode in ("none", "stock", "custom") and
            type(disable_ntsc_warning) is bool and
            (audio_mode != "none" or disable_ntsc_warning) and
            (fl23 or audio_mode != "none"),
            "sound feature selection differs")
    require(type(volume_percent) is int and 1 <= volume_percent <= 100 and
            (audio_mode == "custom" or volume_percent == 100),
            "sound volume selection differs")
    require((audio_source is None) == (audio_mode != "custom"),
            "custom mode requires one audio file; stock mode uses camera sound")
    if audio_source is not None:
        audio_source = Path(audio_source)
        require(not audio_source.is_symlink(), "audio file is a link")
        audio_source = audio_source.resolve()
    base = firmware.build(official) if fl23 else official
    output = base.with_name(OUTPUT_NAME) if output is None else Path(output)
    require(not output.is_symlink(), "sound package output is a link")
    output = output.resolve()
    require(output.name == OUTPUT_NAME and output.parent.is_dir() and
            not output.is_symlink() and output != base,
            "sound package output path differs")
    manifest = output.with_name(MANIFEST_NAME)
    require(not manifest.is_symlink(), "sound package manifest is a link")
    data = spec_data()
    base_sha = firmware.sha_file(base)
    require(base.stat().st_size == PACKAGE_SIZE and
            base_sha == (data["source_package_sha256"] if fl23 else
                         firmware.SOURCE_SHA),
            "verified feature base package required")
    encoded, audio_proof = (encode_audio(audio_source, data["audio"], volume_percent)
                            if audio_mode == "custom" else (None, None))
    feature_ids = (["fl2_fl3"] if fl23 else []) + (
        ["electronic_shutter_sound"] if audio_mode != "none" else [])
    if audio_mode == "custom":
        feature_ids.append("custom_audio")
    if disable_ntsc_warning:
        feature_ids.append("no_ntsc_notice_v2")
    if output.exists() or manifest.exists():
        require(output.is_file() and manifest.is_file(),
                "incomplete existing sound package build")
        report = json.loads(manifest.read_text(encoding="utf-8"))
        require(report.get("format") == 2 and
                report.get("feature_ids") == feature_ids and
                report.get("audio_mode") == audio_mode and
                report.get("disable_ntsc_warning", False) == disable_ntsc_warning and
                report.get("ntsc_patch_spec_sha256") ==
                (ntsc.SPEC_SHA if disable_ntsc_warning else None) and
                report.get("volume_percent") == volume_percent and
                report.get("source_official_sha256") == firmware.SOURCE_SHA and
                report.get("base_package_sha256") == base_sha and
                report.get("sound_patch_spec_sha256") == SPEC_SHA and
                report.get("source_audio_sha256") ==
                (audio_proof or {}).get("source_audio_sha256") and
                report.get("encoded_audio_sha256") ==
                (audio_proof or {}).get("encoded_audio_sha256") and
                report.get("full_decrypt_verified") is True and
                output.stat().st_size == PACKAGE_SIZE and
                firmware.sha_file(output) == report.get("output_sha256"),
                "existing sound package or source audio differs")
        return output, report
    plain = output.with_name(".feature_sound_plain_building.bin")
    temporary = output.with_name(".feature_sound_dat_building.bin")
    require(not plain.exists() and not temporary.exists(),
            "stale sound package build files present")
    try:
        layout = firmware.parse_dat(base)
        with plain.open("xb") as stream:
            for block in firmware.decoded_blocks(base, layout):
                stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())
        require(firmware.sha_file(plain) ==
                (data["source_plain_sha256"] if fl23 else OFFICIAL_PLAIN_SHA),
                "feature base plaintext differs")
        if not fl23:
            version_only(plain)
        changes = (patch_plain(plain, data, encoded, fl23)
                   if audio_mode != "none" else {})
        if disable_ntsc_warning:
            changes["ntsc"] = ntsc.patch_plain(plain, firmware)
            # The top-level CRC describes the final package, including NTSC.
            # Keep the intermediate sound-to-NTSC transition in the NTSC proof.
            final_crc = changes["ntsc"]["partition_crc32"]
            crcs = changes.setdefault("partition_crc32", {})
            prior = crcs.get("dev/nflasha15,", final_crc)
            crcs["dev/nflasha15,"] = {"old": prior["old"], "new": final_crc["new"]}
        target_plain_sha = firmware.sha_file(plain)
        dend_crc = firmware.encrypt_from(plain, base, temporary, layout)
        verify_roundtrip(temporary, plain, layout)
        output_sha = firmware.sha_file(temporary)
        require(temporary.stat().st_size == PACKAGE_SIZE,
                "sound DAT length differs")
        report = {"format": 2, "feature_ids": feature_ids,
                  "audio_mode": audio_mode, "volume_percent": volume_percent,
                  "disable_ntsc_warning": disable_ntsc_warning,
                  "ntsc_patch_spec_sha256": ntsc.SPEC_SHA if disable_ntsc_warning else None,
                  "output_path": str(output),
                  "source_official_sha256": firmware.SOURCE_SHA,
                  "base_package_sha256": base_sha,
                  "sound_patch_spec_sha256": SPEC_SHA,
                  "source_audio_sha256": (audio_proof or {}).get("source_audio_sha256"),
                  "encoded_audio_sha256": (audio_proof or {}).get("encoded_audio_sha256"),
                  "audio_samples": (audio_proof or {}).get("samples"),
                  "audio_duration_seconds": (audio_proof or {}).get("duration_seconds"),
                  "resource_duration_seconds": (audio_proof or {}).get("resource_duration_seconds"),
                  "audio_frame_count": (audio_proof or {}).get("frame_count"),
                  "tail_padding_samples": (audio_proof or {}).get("tail_padding_samples"),
                  "registration_length_bytes": changes.get("cp", {}).get("registered_audio_bytes"),
                  "output_sha256": output_sha,
                  "output_plain_sha256": target_plain_sha,
                  "output_size": PACKAGE_SIZE, "package_version": "2.00",
                  "full_decrypt_verified": True, "camera_access": False,
                  "dend_crc32": dend_crc, **changes}
        temporary.replace(output)
        manifest.write_text(json.dumps(report, indent=2) + "\n",
                            encoding="utf-8")
        return output, report
    finally:
        plain.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--fl23", action="store_true")
    parser.add_argument("--audio-mode", choices=("stock", "custom"), required=True)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--volume", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output, report = build(args.official, args.fl23, args.audio_mode,
                           args.audio, args.volume, args.output)
    print(json.dumps({"event": "sound_package_200_built",
                      "output": str(output), "sha256": report["output_sha256"],
                      "audio_mode": report["audio_mode"],
                      "audio_duration_seconds": report["audio_duration_seconds"],
                      "camera_access": False}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("error:", exc, file=sys.stderr)
        raise SystemExit(1)
