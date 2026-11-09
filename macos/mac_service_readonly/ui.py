"""Bilingual terminal interface for the macOS installer."""

import json
import subprocess
import sys
from terminal_panel import Panel


STEPS = (
    "new", "preflight_complete", "p1_ready", "card_staged", "p1_installed",
    "menu_window_active", "camera_updated_200", "p1_restored",
    "cp_old_verified", "cp_ram_applied", "cp_target_verified", "bk4_verified",
    "coldboot_requested", "cold_cp_verified", "coldboot_verified", "complete",
)

LABELS = {
    "new": ("准备只读检查", "Preparing read-only checks"),
    "preflight_complete": ("BK4 和 p1 备份完成", "BK4 and p1 backups complete"),
    "p1_ready": ("机身专用 p1 补丁已生成", "Camera-specific p1 gate ready"),
    "card_staged": ("2.00 固件已写入照片卡", "2.00 package staged on the card"),
    "p1_installed": ("临时 p1 门控已安装", "Temporary p1 gate installed"),
    "menu_window_active": ("等待机身更新", "Waiting for camera update"),
    "camera_updated_200": ("机身更新完成", "Camera update complete"),
    "p1_restored": ("原始 p1 已恢复", "Original p1 restored"),
    "cp_old_verified": ("CP 原始颜色表已核对", "Original CP table verified"),
    "cp_ram_applied": ("CP 运行时颜色表已写入", "Live CP table applied"),
    "cp_target_verified": ("CP 目标颜色表已回读", "Target CP table read back"),
    "bk4_verified": ("BK4 持久化已核对", "Persistent BK4 verified"),
    "coldboot_requested": ("等待机身冷启动", "Waiting for cold boot"),
    "cold_cp_verified": ("冷启动后 CP 已核对", "CP verified after cold boot"),
    "coldboot_verified": ("冷启动后 BK4 已核对", "BK4 verified after cold boot"),
    "sound_cold_verified": ("冷启动后连接已核对", "Connection verified after cold boot"),
    "complete": ("安装完成", "Installation complete"),
}

ACTIONS = {
    "READ": ("只读保存两份 BK4 与完整 p1", "Reading both BK4 files and full p1"),
    "BUILD": ("构建并写入 2.00 固件", "Building and staging 2.00 firmware"),
    "RETRY CARD": ("核对并继续照片卡复制", "Checking and resuming the card copy"),
    "P1": ("写入临时 p1 门控", "Applying the temporary p1 gate"),
    "RAM": ("启动更新确认窗口", "Starting the update window"),
    "RESTORE": ("恢复原始 p1", "Restoring the original p1"),
    "CP READ": ("只读检查 CP 颜色表", "Reading the CP color table"),
    "CP WRITE": ("写入 CP 运行时颜色表", "Writing the live CP color table"),
    "CP VERIFY": ("回读 CP 颜色表", "Reading back the CP color table"),
    "CP REFRESH": ("刷新 CP 只读检查", "Refreshing the CP read-only check"),
    "BK4 WRITE": ("核对并持久化 BK4", "Checking and persisting BK4"),
    "COLD CP": ("冷启动后检查 CP", "Checking CP after cold boot"),
}

MANUAL = {
    "NTSC OK": (
        "请确认冷启动后原先出现的 NTSC 开机提示已跳过，拍摄和回放正常。",
        "After cold boot, confirm the previous NTSC startup notice is skipped and capture/playback work."),
    "SOUND OK": (
        "断开 USB，确认 MENU 版本 2.00；若启用了 FL2/FL3 也确认可选。拍摄并试听电子快门音效，重新连接 USB 后按 Enter。",
        "Disconnect USB and confirm version 2.00. If FL2/FL3 was selected, check those modes too. Take a photo, check the shutter sound, reconnect USB and press Enter."),
    "COLD": (
        "断开 USB、关机，取出电池约 30 秒；装回电池、开机并重新连接 USB。完成后按 Enter。",
        "Disconnect USB, power off and remove the battery for about 30 seconds. Reinsert it, power on and reconnect USB, then press Enter."),
    "FL2 FL3 OK": (
        "在相机菜单确认版本 2.00、FL2/FL3 可选，并各拍一张 JPEG 检查效果。完成后按 Enter。",
        "Check camera version 2.00 and selectable FL2/FL3; take a JPEG with each mode. Press Enter when done."),
}


ACTIVE_PANEL = None


def raw_key():
    if not sys.stdin.isatty():
        return input().strip()
    import termios
    import tty
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        value = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
    if value == "\x03":
        raise KeyboardInterrupt
    return value


def key():
    return raw_key().lower()


class Console:
    def __init__(self, language):
        self.language = language
        self.column = 0 if language == "zh" else 1
        self.last_event = None
        self.steps = STEPS
        self.panel = ACTIVE_PANEL
        if self.panel and self.panel.active:
            self.panel.set_language("中文" if language == "zh" else "English")

    def text(self, pair):
        return pair[self.column]

    def note(self, message):
        if self.panel and self.panel.active:
            self.panel.event(message)
        else:
            print(message, flush=True)

    def note_pair(self, pair):
        self.note(self.text(pair))

    def authenticate(self):
        if self.panel and self.panel.active:
            self.panel.pause()
        try:
            subprocess.run(["sudo", "-v"], check=True)
        finally:
            if self.panel and self.panel.active:
                self.panel.resume()

    def _prompt(self, message):
        if self.panel and self.panel.active:
            self.panel.set_prompt(message)
        else:
            print("\n" + message, flush=True)

    def _clear_prompt(self):
        if self.panel and self.panel.active:
            self.panel.set_prompt("")

    def menu(self):
        self._prompt("\n".join((
            self.text(("选择操作", "Choose an action")),
            self.text(("非官方固件有无法开机和影响保修的风险。开始前请确认官方 2.01、电量充足、USB 为海量存储、LUN 为多个。",
                       "Unofficial firmware can prevent booting and affect warranty. Start from official 2.01 with a charged battery, USB Mass Storage and LUN Multi.")),
            self.text(("把原始 2.01 DAT 放在 run.command 同目录；启动后会核对哈希。",
                       "Place the unmodified official 2.01 DAT beside run.command; its hash is checked first.")),
            self.text(("[1] 安装或继续  [2] 仅恢复原始 p1  [3] 切换语言  [4] 退出",
                       "[1] Install or resume  [2] Restore original p1 only  [3] Language  [4] Exit")))))

    def _audio_path(self):
        label = self.text(("输入 MP3/WAV 文件完整路径（最长 2 秒）：",
                           "Enter the full MP3/WAV path (up to 2 seconds):"))
        if not (self.panel and self.panel.active):
            return input("\n" + label + " ").strip().strip('"')
        chars = []
        while True:
            self._prompt(label + "\n" + "".join(chars[-100:]) + "\n" +
                         self.text(("[Enter] 确认  [Esc] 返回", "[Enter] Confirm  [Esc] Back")))
            pressed = raw_key()
            if pressed in ("\r", "\n"):
                self._clear_prompt()
                return "".join(chars).strip().strip('"')
            if pressed == "\x1b":
                self._clear_prompt()
                return None
            if pressed in ("\b", "\x7f"):
                if chars:
                    chars.pop()
            elif pressed.isprintable():
                chars.append(pressed)

    def features(self):
        while True:
            self._prompt(self.text((
                "选择功能：\n[1] FL2/FL3  [2] 仅电子快门音效  [3] FL2/FL3 + 电子快门音效",
                "Select features:\n[1] FL2/FL3  [2] Sound only  [3] FL2/FL3 + sound")))
            choice = key()
            if choice == "1":
                self._clear_prompt()
                plan = {"fl23": True, "audio_mode": "none",
                        "audio_path": None, "volume_percent": 100}
                self._ntsc_choice(plan)
                self.selected_features(plan)
                return plan
            if choice not in ("2", "3"):
                continue
            self._prompt(self.text((
                "选择音效：\n[1] 机内原厂声音（原响度）  [2] 上传 MP3/WAV",
                "Choose sound:\n[1] Built-in camera sound (original level)  [2] MP3/WAV file")))
            sound = key()
            if sound == "1":
                plan = {"fl23": choice == "3", "audio_mode": "stock",
                        "audio_path": None, "volume_percent": 100}
            elif sound == "2":
                path = self._audio_path()
                if path is None:
                    continue
                volume = self._volume_percent()
                if volume is None:
                    continue
                plan = {"fl23": choice == "3", "audio_mode": "custom",
                        "audio_path": path, "volume_percent": volume}
            else:
                continue
            self._clear_prompt()
            self._ntsc_choice(plan)
            self.selected_features(plan)
            return plan

    def _ntsc_choice(self, plan):
        self._prompt(self.text((
            "NTSC 开机提示：\n[1] 保留（默认）  [2] 跳过提示",
            "NTSC startup notice:\n[1] Keep (default)  [2] Skip notice")))
        while True:
            pressed = key()
            if pressed in ("1", "\r", "2"):
                if pressed == "2":
                    plan["disable_ntsc_warning"] = True
                self._clear_prompt()
                return

    def _volume_percent(self):
        chars = []
        while True:
            self._prompt(self.text((
                "音效响度 1–100%（100% 使用 FAH 实测编码参数；直接 Enter 使用 100%）：",
                "Sound level 1–100% (100% uses the verified FAH encoding level; Enter uses 100%):"))
                + "\n" + "".join(chars) + "\n" +
                self.text(("[Enter] 确认  [Esc] 返回", "[Enter] Confirm  [Esc] Back")))
            pressed = raw_key()
            if pressed in ("\r", "\n"):
                value = int("".join(chars) or "100")
                if 1 <= value <= 100:
                    self._clear_prompt()
                    return value
            elif pressed == "\x1b":
                self._clear_prompt()
                return None
            elif pressed in ("\b", "\x7f"):
                if chars:
                    chars.pop()
            elif pressed.isdigit() and len(chars) < 3:
                chars.append(pressed)

    def camera(self, serial):
        if self.panel and self.panel.active:
            self.panel.set_camera("ILCE-7CM2  " + serial)
        else:
            print(f"\nILCE-7CM2  |  {serial}", flush=True)

    def selected_features(self, plan):
        self.steps = STEPS if plan["fl23"] else tuple(
            step for step in STEPS if step not in (
                "cp_old_verified", "cp_ram_applied", "cp_target_verified",
                "bk4_verified", "cold_cp_verified", "coldboot_verified"))[:-1] + (
                    "sound_cold_verified", "complete")
        label = "FL2/FL3" if plan["fl23"] else "Sound"
        if plan["fl23"] and plan["audio_mode"] != "none":
            label += " + sound"
        if plan["audio_mode"] == "custom":
            label += f" {plan['volume_percent']}%"
        if plan.get("disable_ntsc_warning", False):
            label += " + skip NTSC notice"
        if self.panel and self.panel.active:
            self.panel.set_features(label)

    def progress(self, status):
        if status not in LABELS:
            return
        if status not in self.steps:
            return
        done = self.steps.index(status)
        label = self.text(LABELS[status])
        if self.panel and self.panel.active:
            self.panel.set_progress(done, len(self.steps) - 1, label)
        else:
            bar = ("#" * (done * 24 // (len(self.steps) - 1))).ljust(24, ".")
            print(f"\n[{done:02d}/{len(self.steps) - 1}] [{bar}] {label}", flush=True)

    def action(self, label):
        if label in ACTIONS:
            message = self.text(ACTIONS[label])
            if self.panel and self.panel.active:
                self.panel.set_status(message)
            else:
                print("  " + message, flush=True)

    def manual(self, label):
        self._prompt(self.text(MANUAL[label]) + "\n" +
                     self.text(("[Enter] 已完成  [Q] 停止", "[Enter] Done  [Q] Stop")))
        return self.manual_key()

    def manual_key(self):
        while True:
            pressed = key()
            if pressed in ("\r", "\n", ""):
                self._clear_prompt()
                return True
            if pressed == "q":
                self._clear_prompt()
                return False

    def wait_connection(self, error):
        self._prompt(self.text(("相机尚未以海量存储正常连接：",
                                "Camera is not connected in Mass Storage mode: ")) +
                     str(error) + "\n" +
                     self.text(("连接相机后按 Enter 重试，或 Q 停止。",
                                "Connect the camera and press Enter to retry, or Q to stop.")))
        return self.manual_key()

    def update_choice(self):
        self._prompt("\n".join((
            self.text(("断开 USB，打开机身更新确认页。只有显示 1.99 → 2.00 才能执行。",
                       "Disconnect USB and open the camera update confirmation. Execute only if it shows 1.99 -> 2.00.")),
            self.text(("[1] 已看到 1.99 → 2.00  [2] 已更新并重新连接  [3] 取消并恢复 p1  [Q] 停止",
                       "[1] Shows 1.99 -> 2.00  [2] Already updated and reconnected  [3] Cancel and restore p1  [Q] Stop")))))
        while (pressed := key()) not in ("1", "2", "3", "q"):
            pass
        self._clear_prompt()
        return pressed

    def update_complete(self):
        self._prompt(self.text((
            "请在相机上执行更新；完成并重新连接 USB 后，仅在 MENU 显示 2.00 时按 Enter；按 C 取消。",
            "Execute the update on the camera. After it completes and USB reconnects, press Enter only if MENU shows 2.00; press C to cancel.")))
        while True:
            pressed = key()
            if pressed in ("\r", "\n", ""):
                self._clear_prompt()
                return True
            if pressed == "c":
                self._clear_prompt()
                return False
            if pressed == "q":
                self._clear_prompt()
                return None

    def child_start(self, name, heartbeat=True):
        label = self.text(("正在运行：", "Running: ")) + name
        if self.panel and self.panel.active:
            self.panel.start_task(label, heartbeat)
        else:
            print("  " + label, flush=True)

    def child_done(self):
        if self.panel and self.panel.active:
            self.panel.end_task()

    def child_line(self, line):
        trimmed = line.rstrip()
        try:
            item = json.loads(trimmed)
        except json.JSONDecodeError:
            if trimmed.startswith(("Verified package:", "Verified existing output:",
                                   "card_bodydata_200_verified:",
                                   "bk4_already_target_verified:",
                                   "bk4_commit_verified:", "bk4_target_verified:")):
                self.note("  " + trimmed[:240])
            return
        event = item.get("event")
        if event == "sound_package_200_built":
            self.note_pair(("自定义音效固件已完整校验", "Custom sound package fully verified"))
            return
        labels = {"owner_window_saved": ("p1 读取窗口", "p1 capture window"),
                  "normal_mode_verified": ("USB 已恢复", "USB mode restored")}
        if event in labels and not (event == self.last_event == "normal_mode_verified"):
            self.note("  " + self.text(labels[event]))
        self.last_event = event

    def failure(self, name, log, tail):
        self.child_done()
        if self.panel and self.panel.active:
            self.panel.set_status(self.text(("失败：", "Failed: ")) + name)
        self.note(self.text(("步骤失败，日志：", "Step failed. Log: ")) + str(log))
        for line in tail[-4:]:
            if line:
                self.note("  " + line[:300])


def launch():
    global ACTIVE_PANEL
    panel = Panel("macOS")
    panel.open()
    ACTIVE_PANEL = panel
    try:
        if panel.active:
            panel.set_prompt("[1] 中文  [2] English")
        else:
            print("\nA7C II Camera Tools  |  macOS\n[1] 中文  [2] English", flush=True)
        while (choice := key()) not in ("1", "2"):
            pass
        console = Console("zh" if choice == "1" else "en")
        while True:
            console.menu()
            action = key()
            console._clear_prompt()
            if action == "4":
                return 0
            if action == "3":
                console = Console("en" if console.language == "zh" else "zh")
                continue
            if action not in ("1", "2"):
                continue
            if action == "1":
                try:
                    from mac_build_and_stage_200 import official_source
                    official_source(None)
                except Exception as exc:
                    console.note(console.text(("固件源文件检查失败：",
                                               "Official DAT check failed: ")) + str(exc))
                    continue
            import a7c2_200_oneclick as workflow
            try:
                workflow.main("run" if action == "1" else "restore-only",
                              screen=console)
            except workflow.Stopped:
                console.note_pair(("已停止；运行记录已保留。", "Stopped; progress was saved."))
            except Exception as exc:
                console.note(console.text(("失败：", "Failed: ")) +
                             f"{type(exc).__name__}: {exc}")
    finally:
        ACTIVE_PANEL = None
        panel.close()


if __name__ == "__main__":
    raise SystemExit(launch())
