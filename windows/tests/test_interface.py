import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
import a7c2_200_windows as workflow
import ui


class InterfaceTests(unittest.TestCase):
    def test_ntsc_skip_is_saved_with_feature_choice(self):
        console = ui.Console("en")
        with patch.object(ui, "key", side_effect=["1", "2"]), \
                patch.object(console, "_prompt"), \
                patch.object(console, "_clear_prompt"):
            plan = console.features()
        self.assertTrue(plan["disable_ntsc_warning"])
        self.assertTrue(plan["fl23"])
        self.assertEqual(plan["audio_mode"], "none")

    def test_background_step_does_not_ask_for_input(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "state.json"
            proof = Path(folder) / "proof.json"
            state = {"format": 1}
            events = []

            class Screen:
                def progress(self, step, current):
                    events.append((step, current.get(step)))

                def manual(self, *_):
                    raise AssertionError("background step requested input")

            def work():
                proof.write_text("{}", encoding="utf-8")

            with patch.object(workflow, "SCREEN", Screen()):
                workflow.step(state_path, state, "build", work, proof)

            self.assertEqual(events, [("build", None), ("build", "done")])
            self.assertEqual(json.loads(state_path.read_text())["build"], "done")

    def test_offline_build_can_resume_after_interruption(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state_path, proof = root / "state.json", root / "selected_package_200.json"
            state = {"format": 1, "build": "started"}
            class Screen:
                def progress(self, *_):
                    pass
            with patch.object(workflow, "SCREEN", Screen()):
                workflow.step(state_path, state, "build",
                              lambda: proof.write_text("{}", encoding="utf-8"),
                              proof)
            self.assertEqual(state["build"], "done")

    def test_manual_prompt_can_stop(self):
        console = ui.Console("en")
        with patch.object(ui, "key", return_value="q"):
            self.assertFalse(console.manual("COLD", ""))

    def test_update_prompt_matches_temporary_version_window(self):
        for message in ui.MANUAL["TARGET 2.00"]:
            self.assertIn("1.99", message)
            self.assertIn("2.00", message)
            self.assertNotIn("2.01 → 2.00", message)
            self.assertNotIn("2.01 -> 2.00", message)

    def test_sound_only_and_custom_volume_choices(self):
        console = ui.Console("en")
        with patch.object(ui, "key", side_effect=["2", "1", "1"]), \
                patch.object(console, "_prompt"), \
                patch.object(console, "_clear_prompt"):
            stock = console.features()
        self.assertEqual(stock, {"fl23": False, "audio_mode": "stock",
                                 "audio_path": None, "volume_percent": 100})
        with patch.object(ui, "key", side_effect=["3", "2", "1"]), \
                patch.object(console, "_prompt"), \
                patch.object(console, "_clear_prompt"), \
                patch.object(console, "_audio_path", return_value="shot.wav"), \
                patch.object(console, "_volume_percent", return_value=50):
            custom = console.features()
        self.assertEqual(custom, {"fl23": True, "audio_mode": "custom",
                                   "audio_path": "shot.wav", "volume_percent": 50})

    def test_bk4_already_persisted_never_starts_a_second_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot_dir = root / "snapshot"
            snapshot_dir.mkdir()
            receipt = {"serial": "D117802A6057",
                       "normal_mode_and_driver_verified_after_child_exit": True,
                       "results": {name: {"bk4_record_checksum_verified": True,
                                          "property_length": 8192,
                                          "property_attr": "0x8",
                                          "property_sha256": workflow.BK4_TARGET_SHA}
                                   for name in ("backup_bin", "backup_bak")}}
            (snapshot_dir / "windows-bk4-receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8")
            manifest = root / "p1_manifest.json"
            with patch.object(workflow, "run", side_effect=AssertionError("unexpected write")):
                workflow.resolve_bk4_after_ram(
                    receipt["serial"], snapshot_dir, root / "resolution.json",
                    manifest, root / "version.json", root / "before", root / "ram.json")
            result = json.loads((root / "resolution.json").read_text(encoding="utf-8"))
            self.assertEqual(result["mode"], "persisted_by_cp")

    def test_mixed_bk4_blocks_a_second_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot_dir = root / "snapshot"
            snapshot_dir.mkdir()
            receipt = {"serial": "D117802A6057",
                       "normal_mode_and_driver_verified_after_child_exit": True,
                       "results": {name: {"bk4_record_checksum_verified": True,
                                          "property_length": 8192,
                                          "property_attr": "0x8",
                                          "property_sha256": sha}
                                   for name, sha in (("backup_bin", workflow.BK4_TARGET_SHA),
                                                     ("backup_bak", workflow.BK4_SOURCE_SHA))}}
            (snapshot_dir / "windows-bk4-receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8")
            with patch.object(workflow, "run", side_effect=AssertionError("unexpected write")):
                with self.assertRaisesRegex(ValueError, "mixed"):
                    workflow.resolve_bk4_after_ram(
                        receipt["serial"], snapshot_dir, root / "resolution.json",
                        root / "p1_manifest.json", root / "version.json",
                        root / "before", root / "ram.json")
            self.assertFalse((root / "resolution.json").exists())

    def test_unmodified_bk4_uses_verified_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot_dir = root / "snapshot"
            snapshot_dir.mkdir()
            receipt = {"serial": "D117802A6057",
                       "normal_mode_and_driver_verified_after_child_exit": True,
                       "results": {name: {"bk4_record_checksum_verified": True,
                                          "property_length": 8192,
                                          "property_attr": "0x8",
                                          "property_sha256": workflow.BK4_SOURCE_SHA}
                                   for name in ("backup_bin", "backup_bak")}}
            (snapshot_dir / "windows-bk4-receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8")
            manifest = root / "p1_manifest.json"

            def commit(script, *args):
                self.assertEqual(script, "windows_bk4_commit_200.py")
                self.assertIn("--execute", args)
                (root / "windows_bk4_commit_200_after_ram_receipt.json").write_text(
                    "{}", encoding="utf-8")

            with patch.object(workflow, "run", side_effect=commit) as worker:
                workflow.resolve_bk4_after_ram(
                    receipt["serial"], snapshot_dir, root / "resolution.json",
                    manifest, root / "version.json", root / "before", root / "ram.json")
            self.assertEqual(worker.call_count, 1)
            result = json.loads((root / "resolution.json").read_text(encoding="utf-8"))
            self.assertEqual(result["mode"], "committed")


if __name__ == "__main__":
    unittest.main()
