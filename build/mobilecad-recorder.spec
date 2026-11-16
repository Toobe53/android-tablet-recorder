# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = os.path.dirname(SPECPATH)
if os.path.basename(ROOT) in ("build", "dist"):
    ROOT = os.path.dirname(ROOT)

datas = [(os.path.join(ROOT, "recorder", "static"), "recorder/static")]
datas += collect_data_files("webview")
hidden = collect_submodules("webview")

a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TabletRecorder",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "build", "icon.ico") if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TabletRecorder",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="安卓平板录屏助手.app",
        icon=os.path.join(ROOT, "build", "icon.icns"),
        bundle_identifier="com.toobe53.tabletrecorder",
        version="3.0.0",
        info_plist={
            "NSMicrophoneUsageDescription": "录课时需要访问麦克风来录制讲解声音。",
            "NSLocalNetworkUsageDescription": "在本机 127.0.0.1 上启动预览服务，用于显示控制界面。",
            "CFBundleDisplayName": "安卓平板录屏助手",
            "CFBundleName": "安卓平板录屏助手",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.15",
        },
    )
