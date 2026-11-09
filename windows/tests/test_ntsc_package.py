"""Offline NTSC window, manifest and failure-path regressions; no USB access."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime/release'))
import feature_package_200 as feature
import ntsc_package_200 as ntsc


class NtscPackageTests(unittest.TestCase):
    def test_resumed_package_must_match_saved_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / feature.MANIFEST_NAME
            plan = {'fl23': True, 'audio_mode': 'custom', 'volume_percent': 50,
                    'disable_ntsc_warning': True, 'audio_sha256': 'a' * 64}
            report = {'feature_ids': feature.features(True, 'custom', True),
                      'audio_mode': 'custom', 'volume_percent': 50,
                      'disable_ntsc_warning': True, 'source_audio_sha256': 'a' * 64}
            manifest.write_text(json.dumps(report))
            feature.check_plan(manifest, plan)
            for field, value in [('disable_ntsc_warning', False), ('fl23', False),
                                 ('audio_mode', 'stock'), ('volume_percent', 100),
                                 ('audio_sha256', 'b' * 64)]:
                changed = dict(plan, **{field: value})
                with self.subTest(field=field), self.assertRaises(ValueError):
                    feature.check_plan(manifest, changed)

    def test_legacy_plan_without_ntsc_field_still_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / feature.MANIFEST_NAME
            plan = {'fl23': True, 'audio_mode': 'none', 'volume_percent': 100}
            manifest.write_text(json.dumps({'feature_ids': ['fl2_fl3'],
                                'audio_mode': 'none', 'volume_percent': 100}))
            feature.check_plan(manifest, plan)

    def test_selection_composes_with_every_existing_profile(self):
        for fl23, mode in [(True, 'none'), (True, 'stock'), (True, 'custom'),
                            (False, 'stock'), (False, 'custom')]:
            original = feature.features(fl23, mode)
            self.assertEqual(feature.features(fl23, mode, True),
                             original + ['no_ntsc_notice_v2'])
            self.assertEqual(feature.features(fl23, mode, False), original)
        for invalid in (0, 1, 'true', None):
            with self.assertRaises(ValueError):
                feature.features(True, 'none', invalid)

    def test_pinned_branches_target_native_continuations(self):
        rows = ntsc.spec_data()['spans']
        self.assertEqual(len(rows), 2)
        for row, source, destination in zip(rows, [0x2061880, 0x2061da8],
                                            [0x206189c, 0x2061dd0]):
            self.assertEqual(row['offset'], source)
            word = int.from_bytes(bytes.fromhex(row['new']), 'little')
            self.assertEqual(word >> 26, 5)  # AArch64 B, not BL
            self.assertEqual(source + (word & 0x3ffffff) * 4, destination)
            self.assertEqual(row['old_sha256'], ntsc.sha(bytes.fromhex('626d8052')))

    def fixture(self, folder):
        raw = bytearray(1200)
        raw[0x20:0x22] = b'\0\x02'
        rows = []
        for at, new in [(256, '07000014'), (512, '0a000014')]:
            raw[at:at+4] = bytes.fromhex('626d8052')
            rows.append({'partition_relative_offset': at, 'new': new,
                         'old_sha256': ntsc.sha(raw[at:at+4]),
                         'source_context_size': 132,
                         'source_context_sha256': ntsc.sha(raw[at-64:at+68])})
        line = f'0,{zlib.crc32(raw[:1024]):08x},dev/nflasha15,\n'.encode()
        raw[1024:1024+len(line)] = line
        path = Path(folder) / 'plain.bin'
        path.write_bytes(raw)
        fw = SimpleNamespace(SOURCE_SHA='package', APP_SOURCE_SHA='app',
             tar_parts=lambda _: (SimpleNamespace(offset_data=0, size=1024), None,
                                  None, SimpleNamespace(offset_data=1024, size=len(line))),
             crc_window=lambda mm, at, size: zlib.crc32(mm[at:at+size]))
        data = {'source_package_sha256': 'package', 'app_source_sha256': 'app',
                'spans': rows}
        return path, bytes(raw), fw, data

    def test_patch_changes_only_two_instructions_and_partition_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            path, before, fw, data = self.fixture(folder)
            with patch.object(ntsc, 'spec_data', return_value=data):
                report = ntsc.patch_plain(path, fw)
            after = path.read_bytes()
            expected = bytearray(before)
            for row in data['spans']:
                at = row['partition_relative_offset']
                expected[at:at+4] = bytes.fromhex(row['new'])
            expected[1026:1034] = f'{zlib.crc32(expected[:1024]):08x}'.encode()
            self.assertEqual(after, expected)
            self.assertEqual(report['windows'], 2)
            self.assertEqual(report['spec_sha256'], ntsc.SPEC_SHA)

    def test_second_window_or_crc_mismatch_leaves_entire_input_untouched(self):
        for kind in ('context', 'instruction', 'crc'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                path, before, fw, data = self.fixture(folder)
                if kind == 'crc':
                    before = before[:1026] + b'00000000' + before[1034:]
                    path.write_bytes(before)
                else:
                    data['spans'][1]['source_context_sha256' if kind == 'context'
                                     else 'old_sha256'] = '0' * 64
                with patch.object(ntsc, 'spec_data', return_value=data):
                    with self.assertRaises(ValueError):
                        ntsc.patch_plain(path, fw)
                self.assertEqual(path.read_bytes(), before)

    def test_selected_manifest_rejects_ntsc_flag_or_proof_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / feature.sound.OUTPUT_NAME
            output.write_bytes(b'package')
            manifest = root / feature.MANIFEST_NAME
            report = {'format': 2, 'feature_ids': ['fl2_fl3', 'no_ntsc_notice_v2'],
                'audio_mode': 'none', 'disable_ntsc_warning': True,
                'source_official_sha256': feature.firmware.SOURCE_SHA,
                'package_version': '2.00', 'full_decrypt_verified': True,
                'output_size': 7, 'output_sha256': feature.firmware.sha_file(output),
                'base_package_sha256': feature.FL23_SHA,
                'ntsc_patch_spec_sha256': ntsc.SPEC_SHA,
                'sound_patch_spec_sha256': feature.sound.SPEC_SHA,
                'volume_percent': 100,
                'ntsc': {'spec_sha256': ntsc.SPEC_SHA, 'windows': 2}}
            with patch.object(feature.sound, 'PACKAGE_SIZE', 7):
                manifest.write_text(json.dumps(report))
                self.assertEqual(feature.selected(manifest)[0], output)
                for field, value in [('disable_ntsc_warning', False),
                                     ('disable_ntsc_warning', 'true'),
                                     ('ntsc_patch_spec_sha256', '0'*64),
                                     ('ntsc', {'windows': 1}),
                                     ('feature_ids', ['fl2_fl3'])]:
                    changed = copy.deepcopy(report)
                    changed[field] = value
                    manifest.write_text(json.dumps(changed))
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        feature.selected(manifest)


if __name__ == '__main__':
    unittest.main()
