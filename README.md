# MobileCAD Recorder 2.1

面向 Android 平板的**独立桌面录课工具**：实时预览、录屏、录音、电平表、截图、推工程，一条龙。
底层是三个成熟的开源工具 —— **adb / scrcpy / ffmpeg** —— 界面是原生窗口（macOS / Windows / Linux），
不用浏览器标签页，也没有 Electron 的体积。

![GUI](screenshots/gui.png)

## 下载

到 [Releases](https://github.com/Toobe53/mobilecad-recorder/releases) 下载对应平台：

| 平台 | 文件 | 说明 |
|---|---|---|
| macOS（Apple 芯片 arm64） | `MobileCAD-Recorder-macOS.zip` | 解压得到 `.app`。未签名：第一次右键 →「打开」；首次启动会请求「本地网络」权限（本机预览服务），点允许即可 |
| Windows 10/11 | `MobileCAD-Recorder-Windows.zip` | 解压后运行 `MobileCAD Recorder.exe`。需要系统自带/已安装 WebView2 运行时（Win11 默认有） |
| Linux | `MobileCAD-Recorder-Linux.tar.gz` | 解压运行 `MobileCAD-Recorder/MobileCAD-Recorder`；需要 `libwebkit2gtk-4.1-0`（`sudo apt install libwebkit2gtk-4.1-0`） |

> Intel Mac 或其它架构：按下方「从源码运行 / 构建」在本机打包即可（命令相同）。

外部依赖仍需本机安装：`adb`、`scrcpy`、`ffmpeg`。程序启动时会自动把 Homebrew / `/usr/local/bin` / 同目录 `bin`
加进 PATH；找不到也可以在「设置」里手填绝对路径。

```bash
# macOS
brew install scrcpy ffmpeg
brew install --cask android-platform-tools
```

## 功能

- **设备自检**：型号、Android、分辨率、电量、存储；adb/scrcpy/ffmpeg/ffprobe 是否就绪（含实际路径）。
- **实时画面**：应用内预览（2–8 fps，可调分辨率/质量/帧率），不需要切换窗口；录制时自动关闭以释放设备采集（需要 60fps 时勾选「镜像窗口」）。
- **音频可视化**：Mac 麦克风电平条（RMS/峰值），录讲解时可以看着电平说话；可开关。
- **输出可选**：MP4/MKV 容器；录完可自动转码（H.264/H.265、CRF、preset、缩放、帧率、音频编码、保留原片），文件名模板可改。
- **独立日志面板**：日志从主界面移到底部抽屉，随时展开/收起，不占录制界面。
- **录制**：分辨率 1280–2560、30/60fps、H.264/H.265/AV1、码率、视频缓冲、限时；音频可选平板麦克风 / 设备内部声音 / 无声；
  显示手指触点、镜像窗口、录制时常亮。
- **截图**、**推送演示工程** 到平板 `下载/MobileCAD-demo`。
- **配音**：用 Mac 麦克风单独录 WAV（采样率/声道可选），再与无声画面 **合成** 一条 MP4（画面不重编码）。
- **性能预设**：高画质 / 平衡 / 低开销，一键切换分辨率、帧率、码率与缓冲。
- **日志抽屉**：底部一整块运行日志，可收起；主界面只留操作区。
- **完整设置**：路径、端口、推送到设备的目录、录完自动开目录 / 自动截图，全部持久化。

## 设置项一览

| 分组 | 设置 | 默认 |
|---|---|---|
| 文件 | 录制目录 | `~/Movies/MobileCAD Recorder`（Win/Linux 为 `Videos/…`） |
| | 演示工程目录 | 空（填 `video-course/demo` 之类） |
| | 推送到设备 | `/sdcard/Download/MobileCAD-demo` |
| 设备 | 指定序列号 | 空 = 第一台 |
| | adb / scrcpy / ffmpeg / ffprobe 路径 | 空 = 走 PATH |
| 视频 | 分辨率 / 帧率 / 码率 | 1920 / 60 / 16M |
| | 编码 | h264（兼容最好）/ h265 / av1 |
| | 视频缓冲（ms） | 0（>0 抗卡顿） |
| | 限时（秒） | 0 = 不限 |
| 开关 | 手指触点 / 镜像窗口 / 录制常亮 | 开 / 关 / 开 |
| 预览 | 帧率 / 宽度 / 质量 | 4 / 720 / 70 |
| | 启动时自动预览 | 关 |
| 输出 | 容器 / 文件名模板 | mp4 / `{name}-{date}-{time}` |
| | 录完自动转码 | 关 |
| | 转码编码 / CRF / preset / 缩放 / 帧率 | h264 / 23 / medium / original / 0 |
| | 转码音频 / 保留原片 | aac / 开 |
| 音频 | 来源 | mic / playback / none |
| | 编码 / 码率 | aac / 192k |
| | 麦克风设备 / 采样率 / 声道 | 0 / 48000 / 2 |
| 收尾 | 录完自动开目录 / 停止时截图 | 关 / 关 |

## 性能建议

- **优先用 USB 3 口和好线**；掉帧时先把帧率降到 30，再把长边降到 1600。
- 长时间录（30 分钟以上）：`H.264 + 16M + 60fps` 约 3.6 GB；想小一点用 `H.265 + 10M`。
- 平板编码器吃力时，把「视频缓冲」设为 200 ms，画面更稳，代价是延迟。
- 界面本身开销很小：状态每 2 秒轮询、版本信息缓存 60 秒、设备信息缓存 5 秒，不重复起进程。
- **实时预览**走「截图→JPEG」，默认 4 fps、720px 宽，CPU 占用低；需要 60fps 实时监看时用「镜像窗口」。
- 预览开启时不能开始录制（自动关闭预览），避免两个采集会话抢设备。

## 从源码运行 / 构建

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install pywebview pyinstaller

python3 app.py                 # 直接跑（原生窗口）
python3 app.py --browser       # 浏览器模式（无 pywebview 时自动回退）

pyinstaller build/mobilecad-recorder.spec --noconfirm   # 打包
```

- macOS 产物：`dist/MobileCAD Recorder.app`
- Windows：`dist/MobileCAD Recorder/`（整个目录分发）
- Linux：`dist/MobileCAD Recorder/`（整个目录分发）

CI（`.github/workflows/release.yml`）在三平台各自构建并上传产物；打 tag（`v*`）时自动创建 Release。

## 稳定性设计

- 单任务锁：录制中不会再启动第二个 scrcpy；
- 停止先 `SIGTERM` 到进程组，等 12 秒再 `SIGKILL`——scrcpy 只在 `SIGTERM`/正常退出时写 MP4 的 moov；
- 配置原子写入；配置/录制目录不可写时自动回退临时目录；
- 服务只绑 `127.0.0.1`，API 需要一次性 token（query 丢失时用 cookie 兜底）；
- 每个外部命令失败都进日志并在界面提示，进程不会因为一次失败退出；
- 录完自动 `ffprobe` 校验时长/编码。

## 目录

```
app.py                    入口（原生窗口 / 浏览器回退、PATH 引导）
recorder/config.py        设置：校验、持久化、平台默认目录
recorder/core.py          设备、进程管理、录制/录音/合成/截图/推送
recorder/server.py        HTTP API + 静态资源（含缓存）
recorder/desktop.py       pywebview 原生窗口
recorder/static/          界面（HTML/CSS/JS）
build/mobilecad-recorder.spec  PyInstaller 打包配置（含 .app、图标、权限说明）
```

## 常见问题

- **macOS 提示「无法验证开发者」**：右键 App →「打开」，或 `xattr -dr com.apple.quarantine "MobileCAD Recorder.app"`。
- **首次启动弹「本地网络」权限**：允许即可，它只用于 `127.0.0.1` 上的界面服务。
- **没有声音**：Android 11 以下不支持音频转发；确认平板没静音；试试「设备内部声音」。
- **电平表不动**：电平表读的是 **Mac 麦克风**（用于配音/监听），不读平板音频；首次使用需给应用麦克风权限。
- **预览很卡/很慢**：预览是截图循环，不是视频流；调低宽度或帧率，或直接用镜像窗口。
- **Windows 打不开窗口**：安装 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。
- **Linux 缺少 webkit**：`sudo apt install libwebkit2gtk-4.1-0`，或用 `--browser` 模式。

## License

MIT。adb（Apache-2.0）、scrcpy（Apache-2.0）、ffmpeg（LGPL/GPL，按你的构建）遵循各自许可证。
