#!/usr/bin/env python3
"""Emulate the NTSC selection windows from extracted A7C II programs, no USB.

execute() adapted from a7c2-fl23-macos research/ntsc-boot-notice/audit_extended.py.
Copyright (c) 2026 MDHan and macOS adapter contributors
Copyright (c) 2026 A7C II FL2/FL3 preview contributors
MIT; see ../licenses/a7c2-fl23-macos-MIT.txt.
External calls are fixtures, not observed camera services. No complete boot,
rendering, video, or proof of hardware reachability is provided.
"""
import argparse
import collections
import hashlib
import itertools
import json
from pathlib import Path
import struct
from unicorn import (Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE,
                     UC_HOOK_MEM_WRITE, UC_PROT_READ, UC_PROT_EXEC)
from unicorn import arm64_const as regs

def execute(raw, path, current, default, reset, boot_type, display,
            pending, other_id, predicate_a, predicate_b, selector_b,
            predicate_c, region=1, initial_mode=0):
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.mem_map(0x2060000, 0x3000, UC_PROT_READ | UC_PROT_EXEC)
    uc.mem_write(0x2060000, raw[0x2060000:0x2063000])
    uc.mem_map(0x70000000, 0x10000)
    fp = 0x70004000
    for i in range(29):
        uc.reg_write(getattr(regs, 'UC_ARM64_REG_X' + str(i)), 0xA7000000 + i)
    uc.reg_write(regs.UC_ARM64_REG_X29, fp)
    uc.reg_write(regs.UC_ARM64_REG_SP, fp)
    for offset, value in [(0xA8, region), (0xAC, current), (0xB8, default),
                          (0xA4, reset), (0x98, boot_type)]:
        uc.mem_write(fp + offset, struct.pack('<I', value))
    for register, value in [(19, fp + 0xE0), (20, fp + 0xD0),
                            (21, 0x70008000), (23, initial_mode), (25, other_id), (28, pending)]:
        uc.reg_write(getattr(regs, 'UC_ARM64_REG_X' + str(register)), value)
    # Calls are identified by their actual BL destination, not by an outcome.
    display_pointer, selector_pointer = 0x70009000, 0x70009010
    uc.mem_write(display_pointer, struct.pack('<I', display))
    uc.mem_write(selector_pointer, struct.pack('<I', selector_b))
    fixtures = {
        0x2E06CC0: None, 0x2E068CC: None,  # lock/unlock
        0x251DD4C: None, 0x251DD5C: None,  # model access scope
        0x1660700: display_pointer,
        0x1660718: selector_pointer,
        0x205F250: predicate_a,
        0x205F1EC: predicate_b,
        0x25AA880: predicate_c,
    }
    result, trace = {}, []

    def on_write(emu, access, address, size, value, data):
        raise AssertionError('Native selection window unexpectedly wrote memory')

    def on_code(emu, pc, size, data):
        trace.append(pc)
        word = struct.unpack_from('<I', raw, pc)[0]
        if word & 0xFC000000 != 0x94000000:
            return
        displacement = word & 0x3FFFFFF
        displacement = (displacement ^ 0x2000000) - 0x2000000
        target = pc + displacement * 4
        if target == 0x205F144:
            result.update(message_id=emu.reg_read(regs.UC_ARM64_REG_X2),
                          mode=emu.reg_read(regs.UC_ARM64_REG_X1))
            emu.emu_stop()
            return
        if target not in fixtures:
            raise AssertionError('Unexpected external call: ' + hex(target))
        value = fixtures[target]
        if value is not None:
            emu.reg_write(regs.UC_ARM64_REG_X0, value)
        emu.reg_write(regs.UC_ARM64_REG_PC, pc + 4)

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    uc.emu_start(0x206179C if path == 'first' else 0x2061CF8, 0x2062200, count=300)
    assert result and uc.reg_read(regs.UC_ARM64_REG_SP) == fp
    registers = tuple(uc.reg_read(getattr(regs, 'UC_ARM64_REG_X' + str(i))) for i in range(31))
    return result, trace, registers


def verify(original, candidate):
    if not __debug__:
        raise RuntimeError('Do not disable verification assertions')
    source, target = Path(original).read_bytes(), Path(candidate).read_bytes()
    assert hashlib.sha256(source).hexdigest() == '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
    window = bytearray(source[0x2060000:0x2063000])
    for offset, new in ((0x1880, '07000014'), (0x1da8, '0a000014')):
        assert window[offset:offset+4] == bytes.fromhex('626d8052')
        window[offset:offset+4] = bytes.fromhex(new)
    assert bytes(window) == target[0x2060000:0x2063000]
    reports = {}
    for mode in (0, 1):
        counts = collections.Counter()
        cases = itertools.product(
            range(2), ('first', 'second'), range(2), range(2), range(2),
            range(4), range(2), [(0, 0x4b7), (0, 0x36c), (1, 0x390), (1, 0x391)],
            range(2), [(0, 0), (0, 1), (1, 0)], range(2))
        for region, entry, current, default, reset, boot, display, pair, pa, bp, pc in cases:
            params = (entry, current, default, reset, boot, display, *pair, pa, *bp, pc)
            old = execute(source, *params, region=region, initial_mode=mode)
            new = execute(target, *params, region=region, initial_mode=mode)
            if old[0]['message_id'] == 0x36b:
                assert new[0]['message_id'] != 0x36b
                assert new[0] == execute(source, *params, region=0, initial_mode=mode)[0]
                counts['ntsc_removed'] += 1
            else:
                assert old == new, (mode, region, params, old[0], new[0])
                counts['other_message_trace_registers_identical'] += 1
            counts['cases'] += 1
        assert counts['cases'] == 12288 and counts['ntsc_removed'] == 288
        reports[str(mode)] = dict(counts)
    return {'camera_access': False, 'by_mode': reports,
            'source_sha256': hashlib.sha256(source).hexdigest(),
            'candidate_sha256': hashlib.sha256(target).hexdigest(),
            'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'limits': ['External calls use explicit fixtures.',
                       'No full boot, rendering, video, or hardware reachability test.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-app', type=Path, required=True)
    parser.add_argument('--candidate-app', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.original_app, args.candidate_app), indent=2))
