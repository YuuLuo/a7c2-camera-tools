#!/usr/bin/env python3
"""Independently compare same-feature DATs with/without NTSC skipping; no USB.

Inputs are an existing baseline and candidate. No firmware is changed. Full
plaintext comparison admits only the two known instructions and AP CRC text.
"""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import struct
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'macos/mac_service_readonly'))
import fl23_package_200 as firmware

# Deliberately independent of the production NTSC manifest.
WINDOWS = ((0x2061880, 0x2789b480, bytes.fromhex('07000014')),
           (0x2061da8, 0x2789b9a8, bytes.fromhex('0a000014')))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class AppImage:
    """Read appFw.so through the pinned DAT's ext2 direct/indirect mapping."""
    def __init__(self, mm, partition):
        self.mm, self.part = mm, partition
        sb = self.read(1024, 1024)
        require(sb[56:58] == b'\x53\xef', 'not ext2')
        self.bs = 1024 << struct.unpack_from('<I', sb, 24)[0]
        self.ipg = struct.unpack_from('<I', sb, 40)[0]
        self.ins = struct.unpack_from('<H', sb, 88)[0]
        require(self.bs == 1024 and self.ipg > 0 and self.ins == 256,
                'unsupported filesystem geometry')

    def read(self, at, size):
        require(0 <= at and at + size <= self.part.size, 'ext2 read out of bounds')
        start = self.part.offset_data + at
        return self.mm[start:start + size]

    def inode(self, number):
        group, index = divmod(number - 1, self.ipg)
        table = struct.unpack_from('<I', self.read(2*self.bs + group*32, 32), 8)[0]
        return self.read(table*self.bs + index*self.ins, self.ins)

    def indirect(self, block, depth):
        if not depth:
            return [block]
        pointers = struct.unpack('<256I', self.read(block*self.bs, self.bs))
        return [item for p in pointers if p for item in self.indirect(p, depth-1)]

    def contents(self, number):
        inode = self.inode(number)
        require(not struct.unpack_from('<I', inode, 32)[0] & 0x80000,
                'extents not supported')
        size = struct.unpack_from('<I', inode, 4)[0]
        require(size <= self.part.size, 'file too large')
        pointers = struct.unpack_from('<15I', inode, 40)
        blocks = list(pointers[:12])
        for depth, block in enumerate(pointers[12:], 1):
            if block:
                blocks.extend(self.indirect(block, depth))
        blocks = blocks[:(size+self.bs-1)//self.bs]
        require(len(blocks)*self.bs >= size and all(blocks), 'sparse/short file')
        return b''.join(self.read(b*self.bs, self.bs) for b in blocks)[:size], blocks

    def app(self):
        number = 2
        for name in (b'lib', b'appFw.so'):
            directory, _ = self.contents(number)
            at = 0
            while at < len(directory):
                ino, size, length, _ = struct.unpack_from('<IHBB', directory, at)
                require(size >= 8 and at + size <= len(directory), 'bad directory')
                if ino and directory[at+8:at+8+length] == name:
                    number = ino
                    break
                at += size
            else:
                raise ValueError('appFw.so not found')
        return self.contents(number)


def verify(baseline, candidate, scratch, app_output=None):
    paths = (Path(baseline), Path(candidate))
    inputs = [firmware.sha_file(p) for p in paths]
    result = {'camera_access': False, 'baseline_sha256': inputs[0],
              'candidate_sha256': inputs[1]}
    with tempfile.TemporaryDirectory(prefix='ntsc-review-', dir=scratch) as folder:
        plains = []
        for i, path in enumerate(paths):
            plain = Path(folder) / str(i)
            with plain.open('xb') as stream:
                for block in firmware.decoded_blocks(path, firmware.parse_dat(path)):
                    stream.write(block)
            plains.append(plain)
        parts = [firmware.tar_parts(p) for p in plains]
        require(parts[0] == parts[1] or
                [(p.offset_data,p.size) for p in parts[0]] ==
                [(p.offset_data,p.size) for p in parts[1]], 'partition layouts differ')
        p15,p5,p8,listing = parts[0]
        with plains[0].open('rb') as a, plains[1].open('rb') as b, \
                mmap.mmap(a.fileno(),0,access=mmap.ACCESS_READ) as old, \
                mmap.mmap(b.fileno(),0,access=mmap.ACCESS_READ) as new:
            require(len(old)==len(new), 'plaintext sizes differ')
            crc_location = None
            result['partitions'] = {}
            for label,part in ((b'dev/nflasha15,',p15),(b'dev/nflasha5,',p5),
                               (b'dev/nflasha8,',p8)):
                checks=[]
                for mm in (old,new):
                    require(mm[:8]==b'UDTRFIRM' and mm[0x20:0x22]==b'\0\x02',
                            'unexpected plaintext version')
                    require(struct.unpack_from('<I',mm,8)[0] ==
                            zlib.crc32(mm[12:0x200]), 'header CRC differs')
                    table=mm[listing.offset_data:listing.offset_data+listing.size]
                    lines=[line for line in table.splitlines() if line.endswith(label)]
                    require(len(lines)==1, 'partition checksum not unique')
                    crc=firmware.crc_window(mm,part.offset_data,part.size)
                    require(int(lines[0][2:10],16)==crc, 'partition CRC differs')
                    checks.append(f'{crc:08x}')
                    if label==b'dev/nflasha15,':
                        at=listing.offset_data+table.find(lines[0])+2
                        require(crc_location is None or crc_location==at,'CRC moved')
                        crc_location=at
                result['partitions'][label.decode()]=checks
            allowed=[(crc_location,8)]
            for off,physical,replacement in WINDOWS:
                at=p15.offset_data+physical
                require(old[at:at+4]==bytes.fromhex('626d8052') and
                        new[at:at+4]==replacement,'wrong NTSC instruction')
                allowed.append((at,4))
            previous=0
            for at,size in sorted(allowed)+[(len(old),0)]:
                for start in range(previous,at,8<<20):
                    end=min(at,start+(8<<20))
                    require(old[start:end]==new[start:end],
                            f'unexpected changes in plaintext range {start:#x}:{end:#x}')
                previous=at+size
            app,blocks=AppImage(new,p15).app()
            base_app,base_blocks=AppImage(old,p15).app()
            require(blocks==base_blocks and app[:4]==b'\x7fELF','app mapping changed')
            expected=bytearray(base_app)
            for off,physical,replacement in WINDOWS:
                require(blocks[off//1024]*1024+off%1024==physical,'mapping differs')
                expected[off:off+4]=replacement
            require(bytes(expected)==app,'extracted app has unexpected changes')
            result.update(app_sha256=sha(app), baseline_app_sha256=sha(base_app),
                          boot_window_sha256=sha(app[0x2060000:0x2063000]),
                          allowed_changes_only=True, ext2_mapping_verified=True,
                          plaintext_sha256=firmware.sha_file(plains[1]))
            if app_output is not None:
                with Path(app_output).open('xb') as stream:
                    stream.write(app)
    require([firmware.sha_file(p) for p in paths]==inputs, 'inputs changed during audit')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--scratch',type=Path,required=True)
    parser.add_argument('--app-output',type=Path)
    args=parser.parse_args()
    print(json.dumps(verify(args.baseline,args.candidate,args.scratch,args.app_output),indent=2))
