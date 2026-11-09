"""Skip the selected NTSC startup message in the exact official 2.01 program.

Instruction windows ported from a7c2-fl23-macos research/two-profiles (MIT).
Copyright (c) 2026 MDHan and macOS adapter contributors
Copyright (c) 2026 A7C II FL2/FL3 preview contributors
See licenses/a7c2-fl23-macos-MIT.txt for the full upstream license.
"""

import hashlib
import json
import mmap
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("ntsc_patch_200.json")
SPEC_SHA = "366949701245649a816f0c2fe1261fe7c36ff30bd6064b4e5b38ed358a44bcc3"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def spec_data():
    raw = SPEC_PATH.read_bytes()
    require(sha(raw) == SPEC_SHA, "NTSC patch specification differs")
    return json.loads(raw)


def patch_plain(plain, firmware):
    data = spec_data()
    require(data["source_package_sha256"] == firmware.SOURCE_SHA and
            data["app_source_sha256"] == firmware.APP_SOURCE_SHA,
            "NTSC source identity differs")
    p15, _, _, listing = firmware.tar_parts(plain)
    with plain.open("r+b") as stream:
        mm = mmap.mmap(stream.fileno(), 0)
        try:
            require(mm[0x20:0x22] == b"\0\x02", "NTSC base version differs")
            listed = bytes(mm[listing.offset_data:listing.offset_data + listing.size])
            lines = [line for line in listed.splitlines()
                     if line.endswith(b"dev/nflasha15,")]
            require(len(lines) == 1 and lines[0].startswith(b"0,") and
                    len(lines[0][2:10]) == 8, "NTSC partition checksum entry differs")
            before_crc = firmware.crc_window(mm, p15.offset_data, p15.size)
            require(int(lines[0][2:10], 16) == before_crc,
                    "NTSC base partition checksum differs")
            writes = []
            for row in data["spans"]:
                at = p15.offset_data + row["partition_relative_offset"]
                size = row["source_context_size"]
                require(p15.offset_data <= at - 64 and
                        at - 64 + size <= p15.offset_data + p15.size and
                        sha(mm[at - 64:at - 64 + size]) ==
                        row["source_context_sha256"] and
                        sha(mm[at:at + 4]) == row["old_sha256"],
                        "NTSC original instruction or context differs")
                replacement = bytes.fromhex(row["new"])
                require(len(replacement) == 4, "NTSC instruction size differs")
                writes.append((at, replacement))
            # Validate both windows and the checksum before changing any bytes.
            for at, replacement in writes:
                mm[at:at + 4] = replacement
                require(mm[at:at + 4] == replacement, "NTSC writeback differs")
            after_crc = firmware.crc_window(mm, p15.offset_data, p15.size)
            crc_at = listing.offset_data + listed.find(lines[0]) + 2
            mm[crc_at:crc_at + 8] = f"{after_crc:08x}".encode()
            mm.flush()
            return {"spec_sha256": SPEC_SHA, "windows": len(writes),
                    "partition_crc32": {"old": f"{before_crc:08x}",
                                        "new": f"{after_crc:08x}"}}
        finally:
            mm.close()
