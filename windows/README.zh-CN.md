# A7C II Windows 相机工具

[English](README.md)

首次运行可选择「FL2/FL3」「仅电子快门音效」或两者组合。音效可直接使用机内原厂样本，保持原响度，无需上传文件。自定义音效支持不超过 2 秒的 MP3/WAV，并可设 **1–100%** 响度。生成的 DAT 和清单保存在 `runtime/runs/<序列号>/`。

功能选择后还可选择**跳过 NTSC 开机提示**（默认保留），可与上述任一功能组合，并随本机计划保存。仅跳过两处已选中的 NTSC 提示路径，不改变 PAL/NTSC 设置；已有工作目录继续使用原选择。本次 DAT 移植已通过离线验证；2026-11-08，一位 A7C II 用户在 QA 后反馈改装正常工作。详细实机测试覆盖范围和恢复能力仍未验证。详见 [NTSC 补丁说明](../native/NTSC.md)。

本工具从未经修改的 ILCE-7CM2 官方 2.01 `BODYDATA.DAT` 构建版本号为 2.00 的所选固件包。流程会备份当前机身的 p1 和 BK4，将固件放入照片卡，临时写入更新门控，并提示在机身菜单执行更新。更新后恢复原始 p1。选择 FL2/FL3 时还会写入运行中的 CP 颜色表，并检查、必要时写入两份 BK4；仅选音效时不修改这些颜色属性。

底层流程已在 Windows 10、Windows 11 和 macOS 上测试，机身覆盖国行与日版。研究机上的本地 p1 补丁已完成六步应用、六步恢复及完整 p1 回读。冷启动后，ST、FL、FL2、FL3 的回放图标与 JPEG/ARW ColorMode 值均已核对，对应数值为 `0`、`18`、`22`、`23`。生成的 2.00 DAT 已通过整包离线解密和逐字节校验。独立的 macOS 安装程序位于 [`../macos/`](../macos/)。

## 准备

- Windows 10/11 x64、管理员权限、Python 3.10 或更新版本。首次运行安装 Python 依赖时需要联网。
- **先将 ILCE-7CM2 升级到未修改的官方 2.01**。准备充足电量的 exFAT 照片卡（容量大于 32 GiB，剩余至少 2.4 GiB）。相机 USB 连接方式设为**海量存储（MSC）**，[USB LUN 设为多个](https://helpguide.sony.net/ilc/2360/v1/zh-cn/contents/0601_usb_lun_setting.html)，使 Windows 能识别照片卡和 `PMHOME` 两卷。
- 从[索尼 ILCE-7CM2 支持页](https://www.sony.com/electronics/support/product/ilce-7cm2/downloads)下载官方 2.01 固件，提取 DAT 并放在 `run.bat` 同目录，命名为 `ILCE-7CM2-v2.01-BODYDATA.DAT`。工具会核对 SHA-256；仓库不包含官方 DAT 或生成的 DAT。
- 首次运行前需要配置 WinUSB，从 [Zadig 官网](https://zadig.akeo.ie/)下载并启动，选择 **Device → Load Preset Device**，加载 [`runtime/tools/a7c2_service_0336.cfg`](runtime/tools/a7c2_service_0336.cfg)，核对 VID `054C`、PID `0336`、MI 留空、目标驱动为 **WinUSB** 后再安装。重新连接相机并重跑。更改驱动前核对 USB ID。该文件格式见 [Zadig 官方说明](https://github.com/pbatard/libwdi/wiki/Zadig#example-of-a-zadig-preset-device-config-file)。

Windows 将相机绑定到 WinUSB 时，机身显示**“请检查所连接的设备”**属于服务访问过程中的正常现象。流程恢复 USB 海量存储并重新连接后，照片卡应再次出现。

## 运行

双击 `run.bat`，选择中文或英文，再选择**安装或继续**。首次运行会创建 `.venv` 并安装依赖。界面显示当前步骤和进度；后台步骤自动执行，只有需要处理 USB、操作相机或安装驱动时才等待按键。机身实际已安装版本从 **2.01** 开始，但限时版本门控会让更新确认页在最多 600 秒内显示 **1.99 → 2.00**。只有确认页明确显示 **1.99 → 2.00** 才执行。

按机身序列号保存的原始备份、回执和日志位于 `runtime/runs/<序列号>/`。在冷启动验证完成前，保留这个目录及官方 DAT。若中断后报告状态不匹配，先查看对应日志。临时 p1 补丁已写入、但无法继续更新时，可从主菜单选择**仅恢复原始 p1**。

## 风险

本工具使用非官方固件，会临时修改机身内部 p1 分区并安装修改过的固件；选择 FL2/FL3 时还会修改颜色属性。更新失败、数据不匹配或中途断电可能导致相机无法启动，甚至需要硬件维修；[索尼也提示更新中断可能导致相机无法正常工作](https://www.sony.com/electronics/support/downloads/W0010781)。未经授权的修改可能影响保修；具体以所在地区的保修条款为准（[美国保修条款示例](https://www.sony.com/articleimage/servlet/servlet.FileDownload?file=0155F000007dHdmQAE)）。请保留本机原始备份并确保电池电量充足。

如果没有独立验证与恢复相机的相关知识和工具，不要自行修改，也不要让 AI 随意修改相机内存、固件、偏移、哈希或写入脚本。

## 目录

| 路径 | 内容 |
| --- | --- |
| `run.bat`、`runtime/ui.py` | 启动与中英双语界面 |
| `runtime/a7c2_200_windows.py` | 可继续运行的 Windows 主流程 |
| `runtime/windows_*.py` | 相机通信、步骤核验及照片卡处理 |
| `runtime/release/` | 离线固件构建与精确补丁清单 |
| `runtime/core/` | 服务协议、p1 与 BK4 工作程序、PMCA USB 代码 |
| `runtime/cp_color_200/` | CP 工作程序模板及清单 |
| `runtime/tools/` | 驱动 INF/CAT 与 0336 Zadig 预设；Zadig 需单独下载 |
| `../native/` | 可修改的 AArch64 工作程序源码和私有头文件生成器 |

项目原创代码采用 [GPL-3.0-only](../LICENSE)。`runtime/core/pmca/` 中的 PMCA 衍生代码保留其 [MIT 许可证](runtime/core/PMCA_LICENSE.txt)；其他文件见[许可与来源说明](../THIRD_PARTY_NOTICES.md)。仓库不包含索尼官方 DAT 或任何机身专属备份。
