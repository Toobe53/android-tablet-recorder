#!/usr/bin/env python3
"""MobileCAD Recorder - standalone desktop app for adb/scrcpy/ffmpeg recording.

Usage:
    python3 app.py                # native window (pywebview)
    python3 app.py --browser      # browser fallback (no pywebview needed)
    python3 app.py --port 9000    # fixed port
"""
import argparse
import os
import sys
import time
import webbrowser


def bootstrap_path():
    """GUI apps inherit a minimal PATH (Finder/Explorer/desktop launchers).

    Prepend the usual tool locations so scrcpy/ffmpeg/adb are found without the
    user having to configure absolute paths.
    """
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

from recorder.config import Config
from recorder import desktop, server


def main():
    parser = argparse.ArgumentParser(description="MobileCAD Recorder")
    parser.add_argument("--browser", action="store_true", help="用浏览器打开，不开原生窗口")
    parser.add_argument("--port", type=int, default=0, help="固定端口（默认自动）")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    if args.version:
        print("MobileCAD Recorder 2.0")
        return 0
    config = Config()
    if args.port:
        config.data["port"] = args.port
    try:
        if not args.browser and desktop.available():
            error = desktop.run(config)
            if error:
                print(error, file=sys.stderr)
            else:
                return 0
        return browser_mode(config)
    except KeyboardInterrupt:
        return 0


def browser_mode(config):
    handle = server.ServerHandle(config, log=lambda line: print(line, flush=True),
                                 port=int(config.get("port") or 0)).start()
    url = handle.url
    print("=" * 60, flush=True)
    print(" MobileCAD Recorder（浏览器模式）", flush=True)
    print(" " + url, flush=True)
    print(" Ctrl+C 退出", flush=True)
    print("=" * 60, flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n正在退出…", flush=True)
    finally:
        handle.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
