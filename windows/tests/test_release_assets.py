import hashlib
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows" / "runtime" / "core"))
import color_property_200 as color


class ReleaseAssetTests(unittest.TestCase):
    def test_color_workers_have_no_embedded_property(self):
        workers = {
            "bk4": ("windows/runtime/core/p1_gate_200/"
                    "libcodex_cp_fl23_bk4_files_200.so",
                    "macos/mac_service_readonly/p1_gate_200/"
                    "libcodex_cp_fl23_bk4_files_200.so"),
            "ram": ("windows/runtime/cp_color_200/"
                    "libcodex_cp_fl23_color_ram_apply200.so",
                    "macos/mac_service_readonly/cp_color_200/"
                    "libcodex_cp_fl23_color_ram_apply200.so"),
        }
        for kind, paths in workers.items():
            source_at, target_at, blank_sha, _ = color.WORKERS[kind]
            for name in paths:
                raw = (ROOT / name).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), blank_sha)
                self.assertEqual(raw[source_at:source_at + 8192], bytes(8192))
                self.assertEqual(raw[target_at:target_at + 8192], bytes(8192))

    def test_firmware_manifest_uses_hashes_for_original_bytes(self):
        windows = (ROOT / "windows/runtime/release/patches_fl23.json").read_bytes()
        macos = (ROOT / "macos/mac_service_readonly/patches_fl23.json").read_bytes()
        self.assertEqual(windows, macos)
        data = json.loads(windows)
        for span in data["app"]["spans"] + data["cp"]["spans"]:
            self.assertNotIn("old", span)
            self.assertEqual(len(span["old_sha256"]), 64)
        for span in data["app"]["spans"]:
            self.assertNotIn("source_context", span)
            self.assertEqual(len(span["source_context_sha256"]), 64)
            self.assertGreaterEqual(span["source_context_size"], 128)

    def test_sound_builders_match_between_platforms(self):
        for name in ("sound_package_200.py", "feature_package_200.py",
                     "sound_patch_200.json", "ntsc_package_200.py",
                     "ntsc_patch_200.json"):
            self.assertEqual(
                (ROOT / "windows/runtime/release" / name).read_bytes(),
                (ROOT / "macos/mac_service_readonly" / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
