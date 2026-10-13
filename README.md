# Dot Abyss 深渊识图脚本

[下载 Windows 免安装版](https://github.com/Lihua2023/dot-abyss-bot/releases/download/v0.1.0-beta.2/DotAbyss-0.1.0-beta.2-win-x64.zip) · [版本说明与全部下载文件](https://github.com/Lihua2023/dot-abyss-bot/releases/tag/v0.1.0-beta.2)

Windows / DMM 客户端的本地识图自动化工具，使用 OpenCV、RapidOCR 和 PyAutoGUI。
免费分享，禁止商用；见 [LICENSE](LICENSE)。源码可查看和非商业修改，第三方依赖适用各自许可。

## 下载与使用

普通用户请下载 `DotAbyss-0.1.0-beta.2-win-x64.zip`，完整解压后双击 `启动.cmd`。
不需要安装 Python 或 Codex。首次先执行 `自检.cmd`，再观察识别、监督短轮。
**F7 暂停/继续，F12 停止，鼠标移到主屏角落紧急停止。**

详细使用、资源消耗、数据位置和更新方式见 [用户说明](release/README-用户版.md)。
GitHub 页面自带的 Source code ZIP 是源码，普通用户应选 win-x64 发行包。

当前为 `0.1.0-beta.2`。本次封装仅进行离线验证，没有重新进行游戏内测试，
也未在独立电脑上实测。此前源码在作者本机 1920×1080 窗口模式完成过 30→80。
不同 DPI、分辨率、完整日文布局和游戏更新后的兼容性尚未验证。
不支持手机、模拟器、后台运行或最小化操作。

默认从 30F 推进 10 层、1 轮。设置可调整路线、颜色、检查点和轮数。
运行消耗游戏资源；失败会清理结算并重开，失败不计成功轮数。
数据保存在 `%LOCALAPPDATA%\DotAbyss`，截图可能含账号信息，不要整体上传运行目录。

## 开发与构建

要求 Windows x64、完整 CPython 3.12（含 Tcl/Tk）。在 PowerShell 中：

```powershell
py -3.12 -m venv .venv-release
.\.venv-release\Scripts\python.exe -m pip install --require-hashes -r requirements-build-win-x64.lock
.\.venv-release\Scripts\python.exe app.py self-test --gui-check
.\.venv-release\Scripts\python.exe verify_packaging.py
.\scripts\build-release.ps1 -SkipReplay
```

依赖锁包含所有传递依赖及官方 PyPI 发布哈希。构建使用 PyInstaller 6.22.3 onedir，
发行程序保留控制台。`release-output` 已有同名版本目录时不会静默覆盖；请增加版本，
或先将旧产物移动到项目内其他明确目录。

公开源码包不含个人游戏截图集。完整回放需作者本地 `samples`：

```powershell
.\.venv-release\Scripts\python.exe verify_offline.py
.\scripts\build-release.ps1
```

公开源码没有样本时使用 `-SkipReplay`，只代表跳过私有截图回放，仍执行 OCR、Tk
和封装回归；不能将其描述为完整游戏验证。源代码模式用 `app.py` 启动，默认读取
项目内配置；发行 EXE 使用 LocalAppData。可用 `--data-dir` 显式指定测试数据目录。

发行目录验收：

```powershell
.\scripts\verify-release.ps1 -Folder '.\release-output\DotAbyss-0.1.0-beta.2-win-x64'
```

该检查验证完整性、中文/空格路径、移除 Python 环境变量后的 EXE 自检、配置备份
及缺资源/坏配置处理，不操作游戏，也不等同于独立电脑验收。
构建元数据、模板与模型哈希写入 `release.json`，发行文件哈希在 `file-manifest.json`。

## 发布与反馈

发行资产为 Windows ZIP、源码 ZIP、`SHA256SUMS.txt`；发布说明模板见
[发布文案](release/发布文案.md)，验收范围见 [VALIDATION](release/VALIDATION.md)。
请将 GitHub Release 标为预发布，网盘上传相同 ZIP 和校验和。
问题反馈请提供版本、窗口尺寸、系统缩放、语言、最后日志及已遮挡账号的截图。
不要发送账号密码、整个账本或整个 runs 文件夹。

第三方许可与 OCR 模型归属见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES/README.md)。
本项目不包含游戏客户端、汉化 Mod 或私人截图；游戏模板的原始画面权利属于原权利人。
