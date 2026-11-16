#!/usr/bin/env python3
"""MobileCAD Recorder - local web GUI for adb/scrcpy/ffmpeg screen recording.

Run:  python3 app.py            (opens http://127.0.0.1:8765/?token=...)
      python3 app.py --no-browser --port 9000

Only the Python standard library is used. Every external command is optional:
if adb/scrcpy/ffmpeg is missing the GUI still starts and tells you what to install.
"""
import argparse
import collections
import json
import mimetypes
import os
import platform
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from recorder import core

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "recorder", "static")
TOKEN = os.environ.get("MCR_TOKEN") or secrets.token_urlsafe(18)
LOG_LINES = collections.deque(maxlen=3000)
LOG_LOCK = threading.Lock()


def log(msg):
    line = time.strftime("%H:%M:%S ") + str(msg)
    with LOG_LOCK:
        LOG_LINES.append(line)
    try:
        print(line, flush=True)
    except Exception:
        pass


def default_config_path():
    env = os.environ.get("MCR_CONFIG")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if platform.system() == "Darwin":
        base = os.path.expanduser("~/Library/Application Support/MobileCAD Recorder")
    else:
        base = os.path.expanduser("~/.mobilecad-recorder")
    return os.path.join(base, "config.json")


def fallback_config_path():
    import tempfile
    return os.path.join(tempfile.gettempdir(), "mobilecad-recorder", "config.json")


def default_recordings_dir():
    env = os.environ.get("MCR_RECORDINGS")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if platform.system() == "Darwin":
        return os.path.expanduser("~/Movies/MobileCAD Recorder")
    return os.path.expanduser("~/MobileCAD Recorder")


CONFIG_PATH = default_config_path()
CONFIG_LOCK = threading.Lock()
CONFIG = {
    "serial": "",
    "recordings_dir": default_recordings_dir(),
    "demo_dir": "",
    "size": 1920,
    "fps": 60,
    "bitrate": "16M",
    "touches": True,
    "mirror": False,
    "audio": "mic",
    "audio_device": "0",
}


def load_config():
    global CONFIG, CONFIG_PATH
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            CONFIG.update({k: v for k, v in data.items() if k in CONFIG})
    except FileNotFoundError:
        pass
    except Exception as e:
        log("配置读取失败，使用默认值：%s" % e)
    # 目录不可写时（只读安装、沙箱等）自动退到临时目录，绝不因此崩溃
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    except Exception as e:
        log("配置目录不可写（%s），改用临时目录" % e)
        CONFIG_PATH = fallback_config_path()
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        except Exception as e2:
            log("临时目录也不可用（%s），本次不保存配置" % e2)
    save_config()


def save_config():
    try:
        with CONFIG_LOCK:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(CONFIG, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_PATH)
    except Exception as e:
        log("配置保存失败：%s" % e)


RUNNER = core.Runner(log, CONFIG["recordings_dir"])


def json_response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def err(handler, message, status=400):
    json_response(handler, {"ok": False, "error": message}, status)


def list_outputs():
    out = []
    root = RUNNER.recordings_dir
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith((".mp4", ".wav", ".png", ".m4a")):
                continue
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            out.append({"path": path, "rel": os.path.relpath(path, root),
                        "size": st.st_size, "mtime": int(st.st_mtime)})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out[:200]


class Handler(BaseHTTPRequestHandler):
    server_version = "MobileCADRecorder/1.0"

    def log_message(self, fmt, *args):  # keep the console clean
        pass

    def _authorised(self):
        if self.path.startswith("/api/"):
            return self.headers.get("X-Token") == TOKEN
        return True

    def _static(self, path):
        if path in ("/", "/index.html"):
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            return self._api_get(parsed)
        return self._static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body.decode("utf-8") or "{}")
        except Exception as e:
            return err(self, "请求体不是合法 JSON：%s" % e)
        try:
            return self._api_post(parsed.path, data)
        except core.JobError as e:
            return err(self, str(e), 409)
        except Exception as e:
            log("API 异常 %s: %s" % (parsed.path, e))
            return err(self, "内部错误：%s" % e, 500)

    # ------------------------------------------------------------------
    def _api_get(self, parsed):
        if not self._authorised():
            return err(self, "token 无效", 403)
        path = parsed.path
        if path == "/api/state":
            dev = core.devices()
            current = CONFIG.get("serial") or (dev[0]["serial"] if dev else "")
            return json_response(self, {
                "ok": True,
                "config": CONFIG,
                "config_path": CONFIG_PATH,
                "devices": dev,
                "device": current,
                "info": core.device_info(current) if current else {},
                "versions": core.versions(),
                "runner": RUNNER.status(),
                "outputs": list_outputs(),
                "log": list(LOG_LINES)[-400:],
                "platform": platform.platform(),
            })
        if path == "/api/audio_devices":
            return json_response(self, {"ok": True, "devices": core.ffmpeg_audio_devices()})
        return err(self, "未知接口", 404)

    def _api_post(self, path, data):
        if not self._authorised():
            return err(self, "token 无效", 403)
        if path == "/api/config":
            for key in ("serial", "recordings_dir", "demo_dir", "size", "fps",
                        "bitrate", "touches", "mirror", "audio", "audio_device"):
                if key in data:
                    CONFIG[key] = data[key]
            if data.get("recordings_dir"):
                RUNNER.recordings_dir = CONFIG["recordings_dir"]
            save_config()
            return json_response(self, {"ok": True, "config": CONFIG})
        if path == "/api/record/start":
            serial = data.get("serial") or CONFIG.get("serial")
            devs = [d for d in core.devices() if d["state"] == "device"]
            if not devs:
                return err(self, "没有可用的 adb 设备（USB 调试打开了吗？）", 409)
            serial = serial or devs[0]["serial"]
            if not any(d["serial"] == serial for d in devs):
                return err(self, "设备 %s 不在线" % serial, 409)
            CONFIG["serial"] = serial
            AUDIO_CHOICES = {"mic", "playback", "none"}
            audio = data.get("audio", CONFIG["audio"])
            if audio not in AUDIO_CHOICES:
                return err(self, "录音来源不合法")
            size = int(data.get("size", CONFIG["size"]))
            fps = int(data.get("fps", CONFIG["fps"]))
            if size < 320 or size > 4096:
                return err(self, "分辨率不合法")
            if fps not in (15, 24, 30, 60, 90, 120):
                return err(self, "帧率不合法")
            bitrate = str(data.get("bitrate", CONFIG["bitrate"]))
            if not any(bitrate.endswith(s) for s in ("k", "K", "m", "M")):
                return err(self, "码率格式应为 8M / 4M 之类")
            CONFIG.update({"size": size, "fps": fps, "bitrate": bitrate, "audio": audio})
            CONFIG["touches"] = bool(data.get("touches", CONFIG["touches"]))
            CONFIG["mirror"] = bool(data.get("mirror", CONFIG["mirror"]))
            save_config()
            res = RUNNER.start_record(serial, data.get("name", "recording"), audio, size, fps,
                                      bitrate, CONFIG["touches"], CONFIG["mirror"])
            return json_response(self, {"ok": True, "runner": RUNNER.status(), "output": res["output"]})
        if path == "/api/record/stop":
            return json_response(self, {"ok": True, "result": RUNNER.stop(), "runner": RUNNER.status()})
        if path == "/api/audio/start":
            dev = str(data.get("device", CONFIG["audio_device"]))
            res = RUNNER.start_audio(dev, data.get("name", "narration"))
            CONFIG["audio_device"] = dev
            save_config()
            return json_response(self, {"ok": True, "runner": RUNNER.status(), "output": res["output"]})
        if path == "/api/audio/stop":
            return json_response(self, {"ok": True, "result": RUNNER.stop(), "runner": RUNNER.status()})
        if path == "/api/mux":
            video = data.get("video") or ""
            audio = data.get("audio") or ""
            if not os.path.isfile(video) or not os.path.isfile(audio):
                return err(self, "请选择存在的视频和音频文件")
            res = RUNNER.mux(video, audio, data.get("name", "muxed"))
            return json_response(self, {"ok": True, "runner": RUNNER.status(), "output": res["output"]})
        if path == "/api/screenshot":
            name = core.safe_name(data.get("name", "shot"))
            outdir = os.path.join(RUNNER.recordings_dir, "stills")
            os.makedirs(outdir, exist_ok=True)
            out = os.path.join(outdir, "%s-%s.png" % (name, time.strftime("%Y%m%d-%H%M%S")))
            serial = data.get("serial") or CONFIG.get("serial")
            cmd = [core.ADB] + (["-s", serial] if serial else []) + ["exec-out", "screencap", "-p"]
            try:
                p = __import__("subprocess").run(cmd, stdout=__import__("subprocess").PIPE, timeout=30)
                if p.returncode != 0 or not p.stdout:
                    return err(self, "截图失败：%s" % (p.stdout[:200] if p.stdout else "无输出"))
                with open(out, "wb") as f:
                    f.write(p.stdout)
                return json_response(self, {"ok": True, "output": out})
            except Exception as e:
                return err(self, "截图失败：%s" % e)
        if path == "/api/push_demos":
            src = data.get("demo_dir") or CONFIG.get("demo_dir")
            if not src or not os.path.isdir(src):
                return err(self, "演示工程目录不存在，请先在设置里填写 demo 目录")
            dest = data.get("dest") or "/sdcard/Download/MobileCAD-demo"
            serial = data.get("serial") or CONFIG.get("serial")
            cmd = [core.ADB] + (["-s", serial] if serial else []) + ["shell", "mkdir", "-p", dest]
            code, text = core.run(cmd, timeout=20)
            if code != 0:
                return err(self, "创建目录失败：%s" % text[:200])
            files = sorted(f for f in os.listdir(src) if f.lower().endswith((".fcstd", ".stl", ".step", ".ifc", ".txt")))
            if not files:
                return err(self, "目录里没有可推送的工程文件")
            pushed = 0
            for f in files:
                code, text = core.run([core.ADB] + (["-s", serial] if serial else []) +
                                      ["push", os.path.join(src, f), dest + "/"], timeout=120)
                if code != 0:
                    return err(self, "推送 %s 失败：%s" % (f, text[:200]))
                pushed += 1
            return json_response(self, {"ok": True, "pushed": pushed, "dest": dest})
        if path == "/api/open_folder":
            target = data.get("path") or RUNNER.recordings_dir
            if not os.path.isdir(target):
                return err(self, "目录不存在：%s" % target)
            try:
                if platform.system() == "Darwin":
                    __import__("subprocess").Popen(["open", target])
                elif platform.system() == "Windows":
                    os.startfile(target)  # type: ignore[attr-defined]
                else:
                    __import__("subprocess").Popen(["xdg-open", target])
                return json_response(self, {"ok": True})
            except Exception as e:
                return err(self, "打开目录失败：%s" % e)
        return err(self, "未知接口", 404)


def main():
    parser = argparse.ArgumentParser(description="MobileCAD Recorder GUI")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        load_config()
    except Exception as e:
        log("加载配置失败，继续用默认值：%s" % e)
    RUNNER.recordings_dir = CONFIG["recordings_dir"]
    try:
        os.makedirs(RUNNER.recordings_dir, exist_ok=True)
    except Exception as e:
        import tempfile
        RUNNER.recordings_dir = os.path.join(tempfile.gettempdir(), "mobilecad-recorder", "recordings")
        CONFIG["recordings_dir"] = RUNNER.recordings_dir
        os.makedirs(RUNNER.recordings_dir, exist_ok=True)
        log("录制目录不可写（%s），改用 %s" % (e, RUNNER.recordings_dir))

    server = None
    port = args.port
    for candidate in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        print("端口 %d-%d 都被占用，无法启动。" % (args.port, args.port + 19), file=sys.stderr)
        return 1
    url = "http://127.0.0.1:%d/?token=%s" % (port, TOKEN)
    print("=" * 62, flush=True)
    print(" MobileCAD Recorder 已启动", flush=True)
    print(" 地址：%s" % url, flush=True)
    print(" 配置：%s" % CONFIG_PATH, flush=True)
    print(" 录制：%s" % CONFIG["recordings_dir"], flush=True)
    print(" 关闭窗口或按 Ctrl+C 结束", flush=True)
    print("=" * 62, flush=True)
    try:
        with open(os.path.join(os.path.dirname(CONFIG_PATH), "last-url.txt"), "w", encoding="utf-8") as f:
            f.write(url + "\n")
    except Exception:
        pass
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在退出…")
    finally:
        RUNNER.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
