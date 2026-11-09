#!/usr/bin/env python3
"""Interactive, resumable A7C II 2.01 to FL2/FL3 2.00 workflow."""

import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time

import ui

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
LOGS = RUNS / "logs"
SCREEN = ui.Console("zh")
RUN_COUNT = 0
sys.path.insert(0, str(ROOT))
import build_p1_gate_200 as builder
import mac_probe_fl23 as probe
import feature_package_200 as feature_package
import p1_gate_generic_200 as gate
import run_backup_snapshot_ro as identity


class Stopped(Exception):
    pass


def require(ok, message):
    if not ok:
        raise ValueError(message)


def private_dir(path):
    if path.exists() or path.is_symlink():
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
                "private run directory identity or mode differs: " + str(path))
    else:
        path.mkdir(mode=0o700)


def private_json(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.with_name(path.name + ".writing-" + secrets.token_hex(4))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    temporary.replace(path)


def run_file(path, *args, sudo=False):
    global RUN_COUNT
    if sudo or path.name == "cp_color_runtime_200.py":
        SCREEN.authenticate()
    command = (["sudo", "-n"] if sudo else []) + [sys.executable, str(path), *map(str, args)]
    private_dir(RUNS)
    private_dir(LOGS)
    RUN_COUNT += 1
    log_path = LOGS / (datetime.now().strftime("%Y%m%dT%H%M%S%f") +
                       f"-{RUN_COUNT:02d}-{path.stem}.log")
    SCREEN.child_start(path.name, heartbeat=not sudo and
                       path.name != "cp_color_runtime_200.py")
    tail = []
    try:
        with log_path.open("x", encoding="utf-8") as log:
            child = subprocess.Popen(command, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1)
            for line in child.stdout:
                log.write(line)
                tail = (tail + [line.rstrip()])[-8:]
                SCREEN.child_line(line)
            code = child.wait()
    finally:
        SCREEN.child_done()
    if code:
        SCREEN.failure(path.name, log_path, tail)
    require(code == 0, path.name + " failed; log: " + str(log_path))


def confirm(label, message):
    if label in ui.MANUAL:
        if not SCREEN.manual(label):
            raise Stopped("stopped by user; progress was saved")
    else:
        SCREEN.action(label)


def probe_camera(expected_serial=None):
    private_dir(RUNS)
    settle_until = None
    while True:
        temporary = RUNS / ("probe-" + secrets.token_hex(8) + ".json")
        report = None
        try:
            run_file(ROOT / "mac_probe_fl23.py", "--out", temporary)
            report = json.loads(temporary.read_text(encoding="utf-8"))
            camera, card, pmhome = identity.report_identity(report)
            identity.wait_for_camera_volumes(camera, card, pmhome)
            serial = camera["serial_num"]
            require(re.fullmatch(r"[A-Za-z0-9_-]{1,40}", serial) is not None,
                    "相机 USB 序列号格式不符合预期")
            require(expected_serial is None or serial == expected_serial,
                    "连接的不是本次运行的相机")
            run_dir = RUNS / serial
            private_dir(run_dir)
            destination = run_dir / ("probe-" + secrets.token_hex(8) + ".json")
            temporary.replace(destination)
            SCREEN.camera(serial)
            return destination, camera, run_dir
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            if temporary.exists():
                temporary.unlink()
            if report is not None:
                sony = [item for item in report.get("usb", {}).get("sony_devices", [])
                        if item.get("source") == "ioreg" and
                        item.get("vendor_id", "").lower() == "0x054c" and
                        item.get("product_id", "").lower() == "0x0e8a" and
                        item.get("name") == "ILCE-7CM2" and
                        (expected_serial is None or
                         item.get("serial_num") == expected_serial)]
                disks = report.get("volumes", {}).get("external_disks", [])
                if len(sony) == 1 and len(disks) < 2:
                    if settle_until is None:
                        settle_until = time.monotonic() + 30
                    if time.monotonic() < settle_until:
                        time.sleep(2)
                        continue
            settle_until = None
            if not SCREEN.wait_connection(exc):
                raise Stopped("等待相机连接时停止")


def load_state(run_dir, serial):
    path = run_dir / "workflow_200.json"
    if not path.exists() and not path.is_symlink():
        return path, {"format": 1, "camera_usb_serial": serial, "status": "new"}
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600,
            "运行状态文件身份或权限异常")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(value.get("format") == 1 and value.get("camera_usb_serial") == serial and
            isinstance(value.get("status"), str),
            "运行状态属于另一台相机或格式不正确")
    return path, value


def save_state(path, state, status, **fields):
    state.update(fields)
    state["status"] = status
    private_json(path, state)
    SCREEN.progress(status)


def full_preflight(path, serial):
    report = json.loads(path.read_text(encoding="utf-8"))
    source = Path((report.get("p1") or {}).get("path", ""))
    builder.verify_source_report(path, source)
    require(report.get("camera_usb_serial") == serial and
            report.get("p1_all_windows_verified") is True and
            report.get("final_tmpfs_window_cleanup_pending") is False,
            "完整只读采集未完成或属于另一台相机")
    return report


def discover_partial_capture(snapshots):
    found = []
    for path in snapshots.glob("cnflasha1-*-manifest.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        capture = item.get("capture_id")
        if (item.get("source") == "cnflasha1" and item.get("complete") is False and
                isinstance(capture, str) and
                re.fullmatch(r"[0-9a-f]{32}", capture)):
            found.append(capture)
    require(len(found) <= 1, "发现多个未完成的 p1 采集，需先检查")
    return found[0] if found else None


def ensure_preflight(state_path, state, run_dir, probe_path, serial, supplied):
    existing = state.get("full_preflight_json")
    if existing:
        path = Path(existing)
        full_preflight(path, serial)
        return path
    snapshots = run_dir / "snapshots"
    if supplied is not None:
        path = supplied.resolve()
        full_preflight(path, serial)
        save_state(state_path, state, "preflight_complete",
                   full_preflight_json=str(path))
        return path
    reports = []
    if snapshots.exists():
        reports = [path for path in snapshots.glob("full-preflight-*.json")
                   if json.loads(path.read_text(encoding="utf-8")).get(
                       "camera_usb_serial") == serial]
    require(len(reports) <= 1, "本机身有多个完整采集报告，需先检查")
    if reports:
        path = reports[0]
        full_preflight(path, serial)
        save_state(state_path, state, "preflight_complete",
                   full_preflight_json=str(path))
        return path
    confirm("READ", "将只读保存这台相机的两份 BK4 和完整 p1；USB 会暂时切换服务模式。")
    if not snapshots.exists():
        run_file(ROOT / "run_backup_snapshot_ro.py", "--probe-json", probe_path,
                 "--out-dir", snapshots, "--execute", sudo=True)
    else:
        require(len(list(snapshots.glob("a7c2-readonly-backup_bin-*.bin"))) == 1 and
                len(list(snapshots.glob("a7c2-readonly-backup_bak-*.bin"))) == 1,
                "已有快照目录不完整，停止以免混用不同机身数据")
    arguments = ["--probe-json", probe_path, "--snapshots-dir", snapshots, "--execute"]
    capture = discover_partial_capture(snapshots)
    if capture:
        arguments += ["--resume", capture]
    run_file(ROOT / "run_full_preflight_201.py", *arguments, sudo=True)
    reports = list(snapshots.glob("full-preflight-*.json"))
    require(len(reports) == 1, "完整 p1 只读采集报告未生成")
    path = reports[0]
    full_preflight(path, serial)
    save_state(state_path, state, "preflight_complete",
               full_preflight_json=str(path))
    return path


def ensure_p1_manifest(state_path, state, run_dir, full_path, camera):
    existing = state.get("p1_manifest")
    if existing:
        path = Path(existing)
        gate.load_manifest(path, full_path, camera)
        return path
    source = Path(full_preflight(full_path, camera["serial_num"])["p1"]["path"])
    candidates = []
    for path in run_dir.glob("p1_gate_200_*/p1_gate_200_manifest.json"):
        try:
            gate.load_manifest(path, full_path, camera)
            candidates.append(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    require(len(candidates) <= 1, "存在多个有效 p1 补丁构建，需先检查")
    if candidates:
        path = candidates[0]
    else:
        output = run_dir / ("p1_gate_200_" + secrets.token_hex(8))
        run_file(ROOT / "build_p1_gate_200.py", "--full-preflight-json", full_path,
                 "--source-p1", source, "--out-dir", output)
        path = output / "p1_gate_200_manifest.json"
        gate.load_manifest(path, full_path, camera)
    save_state(state_path, state, "p1_ready", p1_manifest=str(path))
    return path


def restore_p1(state_path, state, serial, full_path, manifest_path, *, cancelled):
    probe_path, camera, _ = probe_camera(serial)
    confirm("RESTORE", "将按本机原件恢复 p1，并逐阶段回读。")
    save_state(state_path, state, "p1_restore_started")
    run_file(ROOT / "p1_gate_generic_200.py", "--probe-json", probe_path,
             "--full-preflight-json", full_path, "--p1-manifest", manifest_path,
             "--action", "restore", "--execute", sudo=True)
    save_state(state_path, state, "restored_without_update" if cancelled else "p1_restored",
               restore_probe_json=str(probe_path))


def first_restore_attempt_stopped_before_write(state_path, state):
    require(state.get("status") == "p1_restore_started" and
            state.get("user_confirmed_body_version") == "2.00" and
            state.get("first_restore_retry_count", 0) == 0,
            "p1 restore state is not eligible for a first-step retry")
    candidates = []
    for path in LOGS.glob("*-p1_gate_generic_200.log"):
        if path.is_symlink():
            continue
        info = path.stat()
        if (stat.S_ISREG(info.st_mode) and info.st_size <= 16_384 and
                info.st_mtime_ns >= state_path.stat().st_mtime_ns):
            lines = path.read_text(encoding="utf-8").splitlines()
            steps = [line for line in lines if line.startswith("p1_step: ")]
            if (steps == ["p1_step: 1/6 triple:verify_patch"] and
                    lines and lines[-1] ==
                    "error: p1 phase failed or normal USB recovery unverified"):
                candidates.append(path)
    require(len(candidates) == 1,
            "p1 restore log does not prove that no write step began")
    return candidates[0]


def cp_runtime_action(serial, full_path, manifest_path, out, action,
                      read_receipt=None):
    fresh_probe, _, _ = probe_camera(serial)
    arguments = ["--action", action, "--probe-json", fresh_probe,
                 "--full-preflight-json", full_path,
                 "--p1-manifest", manifest_path, "--out", out, "--execute"]
    if read_receipt is not None:
        arguments += ["--read-receipt", read_receipt]
    run_file(ROOT / "cp_color_runtime_200.py", *arguments)
    result = json.loads(out.read_text(encoding="utf-8"))
    require(result.get("serial") == serial and result.get("action") == action and
            result.get("verified") is True and
            result.get("normal_mode_and_driver_verified") is True,
            "CP runtime receipt incomplete")
    return result


def existing_cp_receipt(out, serial, action, state):
    result = json.loads(out.read_text(encoding="utf-8"))
    require(result.get("serial") == serial and result.get("action") == action and
            result.get("property_state") == state and
            result.get("verified") is True and
            result.get("normal_mode_and_driver_verified") is True and
            result.get("marker", {}).get("complete") is True,
            "saved CP receipt incomplete")
    return result


def cp_receipt_age_seconds(receipt):
    stamp = datetime.fromisoformat(receipt["observed_utc"])
    return (datetime.now(timezone.utc) - stamp).total_seconds()


def existing_bk4_receipt(out, serial, cp_path):
    result = json.loads(out.read_text(encoding="utf-8"))
    require(result.get("format") == 1 and
            result.get("camera_serial") == serial and
            result.get("action") == "verify" and
            result.get("cp_runtime_receipt") == str(cp_path) and
            result.get("bk4_property_sha256") ==
            "1035933d52e7198f9656181dc2e8242fa90fc95018eba3823a102c669e02f6f2" and
            result.get("both_bk4_verified") is True and
            set(result.get("backup_sha256", {})) == {"backup_bin", "backup_bak"},
            "saved cold BK4 verification receipt incomplete")
    return result


def resume_run(args):
    probe_path, camera, run_dir = probe_camera()
    serial = camera["serial_num"]
    state_path, state = load_state(run_dir, serial)
    if "feature_plan" in state:
        SCREEN.selected_features(state["feature_plan"])
    status = state["status"]
    if status == "complete":
        SCREEN.progress(status)
        require(state.get("sound_cold_verified") is True if not state["feature_plan"]["fl23"]
                else state.get("cp_cold_verified") is True,
                "冷启动后的验证记录不完整")
        SCREEN.note_pair(("本机身流程已完成。记录：" + str(state_path),
                          "This camera's workflow is complete: " + str(state_path)))
        return
    if status == "restored_without_update":
        SCREEN.progress(status)
        SCREEN.note_pair(("先前已撤销临时 p1 补丁，未继续安装；记录：" + str(state_path),
                          "Temporary p1 gate was restored without installation: " + str(state_path)))
        return
    if status == "p1_restore_started":
        previous_log = first_restore_attempt_stopped_before_write(state_path, state)
        SCREEN.note_pair(("上次 p1 恢复只到第一个只读验证；将重新核对后续跑：" + str(previous_log),
                          "Previous p1 restore stopped at its first read-only verification; retrying after a fresh check: " + str(previous_log)))
    require(status not in ("p1_install_started",
                           "bk4_commit_started", "ram_start_started",
                           "cp_ram_write_started"),
            "上次在写入阶段中断；为避免误判机身状态，停止自动重试并请检查上次输出")
    if "feature_plan" not in state:
        plan = SCREEN.features()
        feature_package.features(plan["fl23"], plan["audio_mode"],
                                 plan.get("disable_ntsc_warning", False))
        if plan["audio_mode"] == "custom":
            selected_audio = Path(plan["audio_path"]).expanduser().resolve()
            require(selected_audio.is_file() and not selected_audio.is_symlink() and
                    selected_audio.suffix.lower() in (".mp3", ".wav") and
                    0 < selected_audio.stat().st_size <= 50_000_000,
                    "select an MP3/WAV audio file no larger than 50 MB")
            feature_package.sound.encode_audio(
                selected_audio, feature_package.sound.spec_data()["audio"],
                plan["volume_percent"])
            plan["audio_path"] = str(selected_audio)
            plan["audio_sha256"] = hashlib.sha256(selected_audio.read_bytes()).hexdigest()
        state["feature_plan"] = plan
        private_json(state_path, state)
    plan = state["feature_plan"]
    SCREEN.selected_features(plan)
    SCREEN.progress(status)
    audio = Path(plan["audio_path"]) if plan["audio_mode"] == "custom" else None
    if audio is not None:
        require(audio.is_file() and not audio.is_symlink() and
                hashlib.sha256(audio.read_bytes()).hexdigest() ==
                plan.get("audio_sha256"), "selected custom audio changed")
    package_manifest = run_dir / "selected_package_200.json"
    package_args = ["--package-manifest", package_manifest]
    if args.official is not None:
        state["official_path"] = str(args.official.resolve())
    build_args = ["--probe-json", probe_path, "--execute", "--out-dir", run_dir,
                  "--audio-mode", plan["audio_mode"], "--volume",
                  plan["volume_percent"]]
    if plan["fl23"]:
        build_args.append("--fl23")
    if plan.get("disable_ntsc_warning", False):
        build_args.append("--disable-ntsc-warning")
    if audio is not None:
        build_args += ["--audio", audio]
    if state.get("official_path"):
        build_args += ["--official", state["official_path"]]
    if status in ("new", "preflight_complete", "p1_ready"):
        full_path = ensure_preflight(state_path, state, run_dir, probe_path, serial,
                                     args.full_preflight_json)
        manifest_path = ensure_p1_manifest(state_path, state, run_dir, full_path, camera)
        if state["status"] == "p1_ready":
            confirm("BUILD", "将从同目录的官方 2.01 DAT 构建 2.00，并复制到已识别的照片卡。")
            save_state(state_path, state, "card_stage_started")
            run_file(ROOT / "mac_build_and_stage_200.py", *build_args)
            save_state(state_path, state, "card_staged")
    else:
        full_path = Path(state["full_preflight_json"])
        manifest_path = Path(state["p1_manifest"])
        gate.load_manifest(manifest_path, full_path, camera)
    status = state["status"]
    if status == "card_stage_started":
        confirm("RETRY CARD", "上次卡复制阶段中断。脚本会先检查已有文件，再决定是否重试复制。")
        run_file(ROOT / "mac_build_and_stage_200.py", *build_args)
        save_state(state_path, state, "card_staged")
    if state["status"] in ("card_staged", "p1_installed"):
        feature_package.check_plan(package_manifest, plan)
    if state["status"] == "card_staged":
        confirm("P1", "将只在这台相机的 p1 中暂时写入验签和降级门控；每阶段会校验与回读。")
        save_state(state_path, state, "p1_install_started")
        run_file(ROOT / "p1_gate_generic_200.py", "--probe-json", probe_path,
                 "--full-preflight-json", full_path, "--p1-manifest", manifest_path,
                 "--action", "install", *package_args,
                 "--execute", sudo=True)
        save_state(state_path, state, "p1_installed")
    if state["status"] == "p1_installed":
        confirm("RAM", "将启动 600 秒临时版本比较窗口；随后需尽快在相机 MENU 确认目标 2.00。")
        save_state(state_path, state, "ram_start_started")
        started = time.time()
        run_file(ROOT / "start_update_code_hold_generic_200.py", "--probe-json", probe_path,
                 "--full-preflight-json", full_path, "--p1-manifest", manifest_path,
                 *package_args,
                 "--execute", sudo=True)
        save_state(state_path, state, "menu_window_active", window_started_utc=started)
    if state["status"] == "menu_window_active":
        choice = SCREEN.update_choice()
        if choice == "q":
            raise Stopped("update window paused; p1 still requires recovery or completion")
        if choice == "1":
            elapsed = time.time() - state.get("window_started_utc", 0)
            require(0 <= elapsed < 540,
                    "临时版本窗口可能已过期；不要执行更新，重新连接后恢复 p1")
            result = SCREEN.update_complete()
            if result is None:
                raise Stopped("update window paused; p1 still requires recovery or completion")
            if result is False:
                choice = "3"
        if choice == "3":
            restore_p1(state_path, state, serial, full_path, manifest_path, cancelled=True)
            return
        post_probe, _, _ = probe_camera(serial)
        save_state(state_path, state, "camera_updated_200",
                   post_update_probe_json=str(post_probe),
                   user_confirmed_body_version="2.00")
    if state["status"] == "camera_updated_200":
        restore_p1(state_path, state, serial, full_path, manifest_path, cancelled=False)
    if state["status"] == "p1_restore_started":
        state["first_restore_retry_count"] = 1
        private_json(state_path, state)
        restore_p1(state_path, state, serial, full_path, manifest_path, cancelled=False)
    if not plan["fl23"]:
        if state["status"] == "p1_restored":
            confirm("COLD", "请断开 USB、关机、取出电池约 30 秒，再装回开机并重新连接 USB。")
            save_state(state_path, state, "coldboot_requested")
        if state["status"] == "coldboot_requested":
            cold_probe, _, _ = probe_camera(serial)
            save_state(state_path, state, "sound_cold_verified",
                       sound_cold_verified=True,
                       coldboot_probe_json=str(cold_probe))
        if state["status"] == "sound_cold_verified":
            confirm("SOUND OK", "确认 MENU 为 2.00 且电子快门拍摄声音正确。")
            if plan.get("disable_ntsc_warning", False):
                confirm("NTSC OK", "Check NTSC startup notice after cold boot.")
                state["user_confirmed_ntsc_after_coldboot"] = True
            save_state(state_path, state, "complete",
                       sound_cold_verified=True,
                       user_confirmed_sound_after_coldboot=True)
            SCREEN.note_pair(("完成：p1 已恢复，机身冷启动后版本与音效已确认。",
                              "Complete: p1 restored; version and sound confirmed after cold boot."))
        return
    cp_old = run_dir / "cp_live_before_200.json"
    cp_ram = run_dir / "cp_live_ram_apply_200.json"
    cp_target = Path(state.get("cp_target_receipt") or
                     run_dir / "cp_live_target_200.json")
    cp_cold = Path(state.get("cp_cold_receipt") or
                   run_dir / "cp_live_after_cold_200.json")
    if state["status"] == "bk4_verified" and not cp_target.is_file():
        raise ValueError("旧流程缺少 CP 运行时补丁；请使用单独的颜色补齐脚本")
    if state["status"] in ("p1_restored", "cp_read_started"):
        confirm("CP READ", "将只读核对 2.00 相机当前 CP 颜色表，确认仍为原始状态。")
        save_state(state_path, state, "cp_read_started")
        if cp_old.is_file():
            existing_cp_receipt(cp_old, serial, "read-old", "old")
        else:
            cp_runtime_action(serial, full_path, manifest_path, cp_old, "read-old")
        save_state(state_path, state, "cp_old_verified", cp_before_receipt=str(cp_old))
    if state["status"] == "cp_old_verified":
        existing_cp_receipt(cp_old, serial, "read-old", "old")
        confirm("CP WRITE", "将先写入运行中的 CP FL2/FL3 颜色表，并检查内存写入标记。")
        save_state(state_path, state, "cp_ram_write_started")
        cp_runtime_action(serial, full_path, manifest_path, cp_ram, "apply", cp_old)
        save_state(state_path, state, "cp_ram_applied", cp_ram_receipt=str(cp_ram))
    if state["status"] in ("cp_ram_applied", "cp_target_read_started"):
        confirm("CP VERIFY", "将独立只读回读 CP 运行时颜色表。")
        save_state(state_path, state, "cp_target_read_started")
        if cp_target.is_file():
            existing_cp_receipt(cp_target, serial, "read-target", "target")
        else:
            cp_runtime_action(serial, full_path, manifest_path, cp_target,
                              "read-target")
        save_state(state_path, state, "cp_target_verified",
                   cp_target_receipt=str(cp_target))
    if state["status"] == "cp_target_verified":
        current = existing_cp_receipt(cp_target, serial, "read-target", "target")
        if cp_receipt_age_seconds(current) >= 900:
            confirm("CP REFRESH", "CP 回读记录已过期，将重新只读核对当前运行时颜色表。")
            cp_target = run_dir / ("cp_live_target_refresh_" +
                                   secrets.token_hex(4) + ".json")
            cp_runtime_action(serial, full_path, manifest_path, cp_target,
                              "read-target")
            save_state(state_path, state, "cp_target_verified",
                       cp_target_receipt=str(cp_target))
        confirm("BK4 WRITE", "CP 运行时颜色表已验证；现在提交并回读两份 BK4。")
        bk4_probe, _, _ = probe_camera(serial)
        save_state(state_path, state, "bk4_commit_started")
        run_file(ROOT / "commit_bk4_generic_200.py", "--probe-json", bk4_probe,
                 "--full-preflight-json", full_path, "--p1-manifest", manifest_path,
                 "--cp-runtime-receipt", cp_target,
                 "--action", "commit", "--execute", sudo=True)
        save_state(state_path, state, "bk4_verified", bk4_probe_json=str(bk4_probe))
    if state["status"] == "bk4_verified":
        confirm("COLD", "请断开 USB、关机、取出电池约 30 秒，再装回开机并重新连接 USB。")
        save_state(state_path, state, "coldboot_requested")
    if state["status"] in ("coldboot_requested", "cold_cp_read_started"):
        confirm("COLD CP", "将只读核对断电后的 CP 运行时颜色表。")
        save_state(state_path, state, "cold_cp_read_started")
        if cp_cold.is_file():
            existing_cp_receipt(cp_cold, serial, "read-target", "target")
        else:
            cp_runtime_action(serial, full_path, manifest_path, cp_cold,
                              "read-target")
        save_state(state_path, state, "cold_cp_verified",
                   cp_cold_receipt=str(cp_cold))
    if state["status"] == "cold_cp_verified":
        current = existing_cp_receipt(cp_cold, serial, "read-target", "target")
        if cp_receipt_age_seconds(current) >= 900:
            confirm("CP REFRESH", "断电后 CP 回读记录已过期，将重新只读核对。")
            cp_cold = run_dir / ("cp_live_cold_refresh_" +
                                 secrets.token_hex(4) + ".json")
            cp_runtime_action(serial, full_path, manifest_path, cp_cold,
                              "read-target")
            save_state(state_path, state, "cold_cp_verified",
                       cp_cold_receipt=str(cp_cold))
        bk4_cold_receipt = Path(state.get("bk4_cold_receipt") or
                                run_dir / "bk4_after_cold_200.json")
        if bk4_cold_receipt.is_file():
            previous = json.loads(bk4_cold_receipt.read_text(encoding="utf-8"))
            if previous.get("cp_runtime_receipt") != str(cp_cold):
                bk4_cold_receipt = run_dir / ("bk4_after_cold_refresh_" +
                                              secrets.token_hex(4) + ".json")
        if bk4_cold_receipt.is_file():
            existing_bk4_receipt(bk4_cold_receipt, serial, cp_cold)
            cold_probe = state.get("coldboot_probe_json")
        else:
            cold_probe, _, _ = probe_camera(serial)
            run_file(ROOT / "commit_bk4_generic_200.py", "--probe-json", cold_probe,
                     "--full-preflight-json", full_path,
                     "--p1-manifest", manifest_path,
                     "--cp-runtime-receipt", cp_cold,
                     "--receipt-out", bk4_cold_receipt,
                     "--action", "verify", "--execute", sudo=True)
            existing_bk4_receipt(bk4_cold_receipt, serial, cp_cold)
        save_state(state_path, state, "coldboot_verified",
                   coldboot_probe_json=str(cold_probe) if cold_probe else None,
                   cp_cold_verified=True,
                   bk4_cold_receipt=str(bk4_cold_receipt))
    if state["status"] == "coldboot_verified":
        if plan["audio_mode"] != "none":
            confirm("SOUND OK", "Check sound and FL2/FL3 on camera.")
        else:
            confirm("FL2 FL3 OK", "请在机身菜单确认 2.00、FL2/FL3 可选，并各拍一张 JPEG 检查效果。")
        if plan.get("disable_ntsc_warning", False):
            confirm("NTSC OK", "Check NTSC startup notice after cold boot.")
            state["user_confirmed_ntsc_after_coldboot"] = True
        save_state(state_path, state, "complete",
                   cp_cold_verified=True, user_confirmed_fl23_after_coldboot=True)
        SCREEN.note_pair(("完成：p1 已恢复，CP 和两份 BK4 在断电后均通过回读。",
                          "Complete: p1 restored; CP and both BK4 files verified after cold boot."))


def restore_only():
    probe_path, camera, run_dir = probe_camera()
    state_path, state = load_state(run_dir, camera["serial_num"])
    require(state["status"] in ("p1_installed", "ram_start_started",
                                 "menu_window_active", "camera_updated_200"),
            "当前状态不适合自动恢复 p1；如在写入阶段中断，请先检查日志")
    full_path = Path(state["full_preflight_json"])
    manifest_path = Path(state["p1_manifest"])
    gate.load_manifest(manifest_path, full_path, camera)
    restore_p1(state_path, state, camera["serial_num"], full_path,
               manifest_path, cancelled=state["status"] != "camera_updated_200")


def main(action="run", official=None, full_preflight_json=None, screen=None):
    global SCREEN
    if screen is not None:
        SCREEN = screen
    require(sys.platform == "darwin", "macOS required")
    args = argparse.Namespace(official=official,
                              full_preflight_json=full_preflight_json)
    if action == "restore-only":
        restore_only()
    else:
        resume_run(args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("run", "restore-only"),
                        default="run")
    parser.add_argument("--official", type=Path)
    parser.add_argument("--full-preflight-json", type=Path)
    args = parser.parse_args()
    try:
        main(args.action, args.official, args.full_preflight_json)
    except Stopped as exc:
        print("已停止：" + str(exc), file=sys.stderr)
        raise SystemExit(2)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("error:", exc, file=sys.stderr)
        raise SystemExit(1)
