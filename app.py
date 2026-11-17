#!/usr/bin/env python3
"""安卓平板录屏助手 - standalone desktop client (adb/scrcpy/ffmpeg).

Only the desktop client is supported. The local bridge on 127.0.0.1 is an
implementation detail of the native window and stops with it.
"""
import argparse
import atexit
import os
import signal
import sys
import time

from recorder.config import Config
from recorder import desktop, server

_HANDLES = []


def bootstrap_path():
    """GUI apps inherit a minimal PATH (Finder/Explorer/desktop launchers)."""
    candidates = []
    if sys.platform == "darwin":
        candidates += ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/bin"]
    elif sys.platform == "win32":
        candidates += [os.path.join(os.path.dirname(sys.executable), "bin"),
                       os.path.expandvars(r"%ProgramFiles%\scrcpy"),
                       os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin"),
                       os.path.expanduser(r"~\scoop\shims")]
    else:
        candidates += ["/usr/local/bin", "/usr/bin", "/snap/bin", os.path.expanduser("~/.local/bin")]
    candidates.append(os.path.dirname(os.path.abspath(sys.executable)))
    candidates.append(os.getcwd())
    current = os.environ.get("PATH", "").split(os.pathsep)
    extra = [p for p in candidates if p and os.path.isdir(p) and p not in current]
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra + current)


bootstrap_path()


def _cleanup(*_args):
    for handle in _HANDLES:
        try:
            handle.stop()
        except Exception:
            pass


def _native_message(message):
    import subprocess
    try:
        if sys.platform == "darwin":
            script = 'display dialog "%s" buttons {"好"} default button 1 with icon caution' % message.replace('"', '\\"')
            subprocess.Popen(["osascript", "-e", script])
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "安卓平板录屏助手", 0x10)
        else:
            subprocess.Popen(["zenity", "--error", "--text=" + message])
    except Exception:
        pass


def headless_mode(config):
    """Internal only: run the bridge without a window (CI smoke tests)."""
    handle = server.ServerHandle(config, log=lambda line: print(line, flush=True),
                                 port=int(config.get("port") or 0)).start()
    _HANDLES.append(handle)
    print("headless bridge on %d" % handle.port, flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        handle.stop()
    return 0


def main():
    parser = argparse.ArgumentParser(description="安卓平板录屏助手")
    parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help="内部端口（默认自动）")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    if args.version:
        print("安卓平板录屏助手 3.2")
        return 0
    config = Config()
    if args.port:
        config.data["port"] = args.port
    atexit.register(_cleanup)
    try:
        signal.signal(signal.SIGTERM, lambda *_: (_cleanup(), sys.exit(0)))
        signal.signal(signal.SIGINT, lambda *_: (_cleanup(), sys.exit(0)))
    except Exception:
        pass
    if args.headless:
        return headless_mode(config)
    if not desktop.available():
        message = ("缺少 pywebview 运行库，无法启动桌面客户端。\n"
                   "请从 Releases 下载安装包，或在本机执行：pip install pywebview pillow")
        print(message, file=sys.stderr)
        _native_message(message)
        return 2
    error = desktop.run(config, on_handle=lambda h: _HANDLES.append(h))
    if error:
        print(error, file=sys.stderr)
        _native_message(error)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
