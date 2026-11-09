"""Small bilingual console interface for the Windows workflow."""

import json
import msvcrt
from terminal_panel import Panel
from pathlib import Path


STEPS = (
    "build", "version_201", "bk4_201", "p1_capture", "p1_cleanup",
    "p1_build", "card", "p1_installed", "hold", "updated",
    "p1_restored", "bk4_before", "cp_before", "cp_ram", "bk4_after_ram", "bk4_commit",
    "bk4_after", "cold", "cp_cold", "bk4_cold", "version_cold",
    "sound_check", "storage",
)

LABELS = {
    "sound_check": ("试听电子快门音效", "Check electronic shutter sound"),
    "build": ("构建 2.00 固件", "Build 2.00 firmware"),
    "version_201": ("核对 2.01", "Verify 2.01"),
    "bk4_201": ("备份原始 BK4", "Back up original BK4"),
    "p1_capture": ("备份 p1", "Back up p1"),
    "p1_cleanup": ("清理临时读取文件", "Clean temporary read files"),
    "p1_build": ("生成专用 p1 补丁", "Build camera-specific p1 gate"),
    "card": ("写入照片卡", "Stage firmware on photo card"),
    "p1_installed": ("写入临时 p1 补丁", "Apply temporary p1 gate"),
    "hold": ("启动更新窗口", "Start update window"),
    "updated": ("机身执行固件更新", "Update firmware on camera"),
    "p1_restored": ("恢复原始 p1", "Restore original p1"),
    "bk4_before": ("备份更新后 BK4", "Back up post-update BK4"),
    "cp_before": ("检查 CP 颜色表", "Check CP color table"),
    "cp_ram": ("写入 CP 运行时颜色表", "Write live CP color table"),
    "bk4_after_ram": ("回查 CP 写入后的 BK4", "Check BK4 after the CP write"),
    "bk4_commit": ("确认 BK4 持久化", "Confirm persistent BK4 properties"),
    "bk4_after": ("回读 BK4", "Read back BK4"),
    "cold": ("机身冷启动", "Cold boot the camera"),
    "cp_cold": ("冷启动后检查 CP", "Check CP after cold boot"),
    "bk4_cold": ("冷启动后检查 BK4", "Check BK4 after cold boot"),
    "version_cold": ("冷启动后检查版本", "Check version after cold boot"),
    "storage": ("恢复照片卡连接", "Restore photo card connection"),
}

MANUAL = {
    "NTSC OK": (
        "请确认冷启动后原先出现的 NTSC 开机提示已跳过，拍摄和回放正常。",
        "After cold boot, confirm the previous NTSC startup notice is skipped and capture/playback work."),
    "SOUND OK": (
        "断开 USB，确认 MENU 为 2.00，拍摄试听电子快门音效；确认有声后重新连接 USB，按 Enter 继续。",
        "Disconnect USB, confirm MENU shows 2.00 and take a photo to check the electronic shutter sound. Reconnect USB and press Enter after hearing it."),
    "0E8A WINUSB": (
        "用 Zadig 将本机 054C:0E8A 绑定到 WinUSB。只选择 ILCE-7CM2。下载：https://zadig.akeo.ie/",
        "Use Zadig to bind this camera's 054C:0E8A to WinUSB. Select only ILCE-7CM2. Download: https://zadig.akeo.ie/"),
    "CARD": (
        "拔下 USB 约 10 秒后重新连接，等待相机显示海量存储且照片卡出现。",
        "Unplug USB for about 10 seconds, reconnect, and wait for Mass Storage and the photo card."),
    "TARGET 2.00": (
        "断开 USB，在 600 秒限时窗口内打开机身更新确认页。仅当显示 1.99 → 2.00 时，按电脑 Enter；随后立即在相机上执行。确认电池电量充足。",
        "Disconnect USB and open the camera's update confirmation within the 600-second window. Only if it shows 1.99 -> 2.00, press Enter here, then execute on the camera immediately. Check battery charge."),
    "UPDATED 2.00": (
        "在相机上执行更新，等待完成并重新连接 USB；确认 MENU 显示 2.00 后按 Enter。",
        "Execute on the camera, wait for completion and reconnect USB. Press Enter after MENU shows 2.00."),
    "COLD": (
        "断开 USB，关机并取出电池约 30 秒；装回、开机、重新连接 USB 后按 Enter。",
        "Disconnect USB, power off and remove the battery for about 30 seconds. Reinsert, power on, reconnect USB, then press Enter."),
}

EVENTS = {
    "sound_package_200_built": ("自定义音效固件已完整校验", "Custom sound package fully verified"),
    "owner_window_saved": ("p1 读取窗口", "p1 capture window"),
    "windows_p1_step_verified": ("p1 阶段已核对", "p1 stage verified"),
    "package_200_card_staged": ("卡内固件已回读", "Card firmware readback complete"),
    "update_hold200_verified": ("更新窗口已启动", "Update window started"),
    "windows_cp_color_ram_verified": ("CP 颜色表已核对", "CP color table verified"),
    "windows_bk4_commit_verified": ("BK4 写入已核对", "BK4 write verified"),
    "normal_mode_verified": ("USB 已恢复", "USB mode restored"),
}


ACTIVE_PANEL = None


def key():
    while True:
        value = msvcrt.getwch()
        if value in ("\x00", "\xe0"):
            msvcrt.getwch()
            continue
        return value


class Console:
    def __init__(self, language):
        self.language = language
        self.index = 0 if language == "zh" else 1
        self.last_event = None
        self.panel = ACTIVE_PANEL
        if self.panel and self.panel.active:
            self.panel.set_language("中文" if language == "zh" else "English")

    def text(self, pair):
        return pair[self.index]

    def note(self, message):
        if self.panel and self.panel.active:
            self.panel.event(message)
        else:
            print(message, flush=True)

    def note_pair(self, pair):
        self.note(self.text(pair))

    def _prompt(self, message):
        if self.panel and self.panel.active:
            self.panel.set_prompt(message)
        else:
            print("\n" + message, flush=True)

    def _clear_prompt(self):
        if self.panel and self.panel.active:
            self.panel.set_prompt("")

    def menu(self):
        message = "\n".join((
            self.text(("选择操作", "Choose an action")),
            self.text(("非官方固件有失保和无法开机的风险；请先确认机身版本、电量和备份。",
                       "Unofficial firmware can affect warranty and booting. Check the camera version, battery and backups first.")),
            self.text(("[1] 安装或继续  [2] 仅恢复原始 p1  [3] 切换语言  [4] 退出",
                       "[1] Install or resume  [2] Restore original p1 only  [3] Language  [4] Exit"))))
        self._prompt(message)

    def _audio_path(self):
        label = self.text(("输入 MP3/WAV 文件完整路径（最长 2 秒）：",
                           "Enter the full MP3/WAV path (up to 2 seconds):"))
        if not (self.panel and self.panel.active):
            return input("\n" + label + " ").strip().strip('"')
        chars = []
        while True:
            shown = "".join(chars[-100:])
            self._prompt(label + "\n" + shown + "\n" +
                         self.text(("[Enter] 确认  [Esc] 返回", "[Enter] Confirm  [Esc] Back")))
            pressed = key()
            if pressed == "\r":
                self._clear_prompt()
                return "".join(chars).strip().strip('"')
            if pressed == "\x1b":
                self._clear_prompt()
                return None
            if pressed == "\b":
                if chars:
                    chars.pop()
            elif pressed.isprintable():
                chars.append(pressed)

    def features(self):
        while True:
            self._prompt(self.text((
                "选择功能：\n[1] FL2/FL3  [2] 仅电子快门音效  [3] FL2/FL3 + 电子快门音效",
                "Select features:\n[1] FL2/FL3  [2] Electronic shutter sound only  [3] FL2/FL3 + sound")))
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
            pressed = key()
            if pressed == "\r":
                value = int("".join(chars) or "100")
                if 1 <= value <= 100:
                    self._clear_prompt()
                    return value
            elif pressed == "\x1b":
                self._clear_prompt()
                return None
            elif pressed == "\b":
                if chars:
                    chars.pop()
            elif pressed.isdigit() and len(chars) < 3:
                chars.append(pressed)

    def selected_features(self, plan):
        label = "FL2/FL3" if plan["fl23"] else "Sound"
        if plan["audio_mode"] != "none" and plan["fl23"]:
            label += " + sound"
        if plan["audio_mode"] == "custom":
            label += f" {plan['volume_percent']}%"
        if plan.get("disable_ntsc_warning", False):
            label += " + skip NTSC notice"
        if self.panel and self.panel.active:
            self.panel.set_features(label)

    def camera(self, serial):
        if self.panel and self.panel.active:
            self.panel.set_camera("ILCE-7CM2  " + serial)
        else:
            print(f"\nILCE-7CM2  |  {serial}", flush=True)

    def progress(self, step, state):
        plan = state.get("feature_plan") or {"fl23": True, "audio_mode": "none"}
        relevant = tuple(name for name in STEPS if
                         (plan["fl23"] or name not in (
                             "bk4_before", "cp_before", "cp_ram", "bk4_after_ram",
                             "bk4_commit", "bk4_after", "cp_cold", "bk4_cold")) and
                         (not plan["fl23"] or name != "version_cold") and
                         (plan["audio_mode"] != "none" or name != "sound_check"))
        done = sum(state.get(name) == "done" for name in relevant)
        if step == "storage" and state.get("complete"):
            done = len(relevant)
        label = self.text(LABELS[step])
        if self.panel and self.panel.active:
            self.panel.set_progress(done, len(relevant), label)
        else:
            width = 24
            bar = ("#" * (done * width // len(relevant))).ljust(width, ".")
            print(f"\n[{done:02d}/{len(relevant)}] [{bar}] {label}", flush=True)

    def manual(self, code, fallback):
        message = self.text(MANUAL[code]) if code in MANUAL else fallback
        self._prompt(message + "\n" +
                     self.text(("[Enter] 已完成 / [Q] 停止", "[Enter] Done / [Q] Stop")))
        while True:
            pressed = key()
            if pressed == "\r":
                self._clear_prompt()
                return True
            if pressed.lower() == "q":
                self._clear_prompt()
                return False

    def child_start(self, script, heartbeat=True):
        label = self.text(("正在运行：", "Running: ")) + script
        if self.panel and self.panel.active:
            self.panel.start_task(label, heartbeat)
        else:
            print("  " + label, flush=True)

    def child_done(self):
        if self.panel and self.panel.active:
            self.panel.end_task()

    def child_line(self, line):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            if line.startswith(("Verified package:", "Verified existing output:",
                                "SHA-256:")):
                self.note("  " + line.rstrip())
            return
        event = item.get("event")
        if event not in EVENTS:
            return
        label = self.text(EVENTS[event])
        if event in ("owner_window_saved", "windows_p1_step_verified"):
            label += f"  {item.get('completed', '?')}/{item.get('total', '?')}"
        if event == "normal_mode_verified" and self.last_event == event:
            return
        self.last_event = event
        self.note("  " + label)

    def failure(self, script, log_path, tail):
        self.child_done()
        message = self.text(("步骤失败，日志：", "Step failed. Log: ")) + str(log_path)
        if self.panel and self.panel.active:
            self.panel.set_status(self.text(("失败：", "Failed: ")) + script)
        self.note(message)
        for line in tail[-4:]:
            if line:
                self.note("  " + line[:300])

    def finished(self, receipt, sound=False, fl23=True):
        message = self.text((
            ("完成：2.00、原始 p1 已恢复，CP 和 BK4 冷启动校验通过。" if fl23 else
             "完成：2.00、原始 p1 已恢复，冷启动后版本已核对。"),
            ("Complete: 2.00 installed, original p1 restored, CP and BK4 verified after cold boot." if fl23 else
             "Complete: 2.00 installed, original p1 restored, version verified after cold boot.")))
        if self.panel and self.panel.active:
            self.panel.set_status(message)
        self.note(message)
        self.note(receipt)
        if sound:
            self.note_pair(("电子快门音效已由用户在机身试听确认。",
                            "Electronic shutter sound confirmed by camera playback."))


def launch():
    global ACTIVE_PANEL
    panel = Panel("Windows")
    panel.open()
    ACTIVE_PANEL = panel
    try:
        if panel.active:
            panel.set_prompt("[1] 中文  [2] English")
        else:
            print("\nA7C II Camera Tools  |  Windows\n[1] 中文  [2] English")
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
            import a7c2_200_windows as workflow
            try:
                workflow.main("run" if action == "1" else "restore-only",
                              console.language, screen=console)
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
