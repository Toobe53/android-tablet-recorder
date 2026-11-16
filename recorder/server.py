"""HTTP API + static file server used by the desktop window (and the browser fallback)."""
import collections
import json
import mimetypes
import os
import platform
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import core

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir():
    """Static assets live next to the code, or inside the PyInstaller bundle."""
    base = getattr(__import__("sys"), "_MEIPASS", None)
    if base:
        return os.path.join(base, "recorder", "static")
    return os.path.join(APP_DIR, "recorder", "static")


class Api:
    def __init__(self, config, token=None, log=None):
        self.config = config
        self.token = token or os.environ.get("MCR_TOKEN") or secrets.token_urlsafe(18)
        self.logs = collections.deque(maxlen=4000)
        self._log_lock = threading.Lock()
        self._log = log or (lambda line: None)
        self.tools = self._tools()
        self.runner = core.Runner(self.tools, self.log, config.get("recordings_dir"))
        self._cache = {}
        self._cache_lock = threading.Lock()

    # -- logging -------------------------------------------------------
    def log(self, message):
        line = time.strftime("%H:%M:%S ") + str(message)
        with self._log_lock:
            self.logs.append(line)
        try:
            self._log(line)
        except Exception:
            pass

    # -- helpers -------------------------------------------------------
    def _tools(self):
        return core.Tools({
            "adb_path": self.config.get("adb_path"),
            "scrcpy_path": self.config.get("scrcpy_path"),
            "ffmpeg_path": self.config.get("ffmpeg_path"),
            "ffprobe_path": self.config.get("ffprobe_path"),
        })

    def _cached(self, key, ttl, producer):
        now = time.time()
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = producer()
        with self._cache_lock:
            self._cache[key] = (now, value)
        return value

    def reload_tools(self):
        self.tools = self._tools()
        self.runner.set_tools(self.tools)
        self.runner.recordings_dir = self.config.get("recordings_dir")
        with self._cache_lock:
            self._cache.clear()

    def outputs(self):
        root = self.runner.recordings_dir
        found = []

        def scan():
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    if not name.lower().endswith((".mp4", ".wav", ".png", ".m4a")):
                        continue
                    path = os.path.join(dirpath, name)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    found.append({"path": path, "rel": os.path.relpath(path, root),
                                  "size": st.st_size, "mtime": int(st.st_mtime)})
            found.sort(key=lambda x: x["mtime"], reverse=True)
            return found[:200]

        return self._cached("outputs", 2.0, scan)

    def current_serial(self):
        devs = [d for d in self._cached("devices", 2.0, lambda: core.devices(self.tools)) if d["state"] == "device"]
        wanted = self.config.get("serial")
        if wanted and any(d["serial"] == wanted for d in devs):
            return wanted
        return devs[0]["serial"] if devs else ""

    def state(self):
        serial = self.current_serial()
        devs = self._cached("devices", 2.0, lambda: core.devices(self.tools))
        info = self._cached("info:" + serial, 5.0,
                            lambda: core.device_info(self.tools, serial) if serial else {})
        return {
            "ok": True,
            "config": self.config.as_dict(),
            "config_path": self.config.path,
            "devices": devs,
            "device": serial,
            "info": info,
            "versions": self._cached("versions", 60.0, lambda: core.versions(self.tools)),
            "tools": self.tools.as_dict(),
            "runner": self.runner.status(),
            "outputs": self.outputs(),
            "log": list(self.logs)[-400:],
            "platform": platform.platform(),
            "desktop": bool(getattr(__import__("sys"), "frozen", False)),
        }


def make_handler(api):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MobileCADRecorder/2.0"

        def log_message(self, fmt, *args):
            pass

        def _authorised(self):
            if not self.path.startswith("/api/"):
                return True
            if self.headers.get("X-Token") == api.token:
                return True
            cookie = self.headers.get("Cookie") or ""
            return ("mcr_token=" + api.token) in cookie

        def _json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _err(self, message, status=400):
            self._json({"ok": False, "error": message}, status)

        def _static(self, path):
            if path in ("/", "/index.html"):
                path = "/index.html"
            root = resource_dir()
            full = os.path.normpath(os.path.join(root, path.lstrip("/")))
            if not full.startswith(root) or not os.path.isfile(full):
                self.send_error(404)
                return
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                body = f.read()
            self.send_response(200)
            if path == "/index.html":
                # 本地 WebView 有时会丢掉 query，用 cookie 兜底
                self.send_header("Set-Cookie", "mcr_token=%s; Path=/; SameSite=Strict" % api.token)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or "javascript" in ctype else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                return self._static(parsed.path)
            if not self._authorised():
                api.log("拒绝未授权请求：%s" % parsed.path)
                return self._err("token 无效", 403)
            try:
                if parsed.path == "/api/state":
                    return self._json(api.state())
                if parsed.path == "/api/audio_devices":
                    return self._json({"ok": True, "devices": api._cached("audio_devices", 30.0,
                                                                        lambda: core.ffmpeg_audio_devices(api.tools))})
                return self._err("未知接口", 404)
            except Exception as e:
                api.log("GET %s 失败：%s" % (parsed.path, e))
                return self._err("内部错误：%s" % e, 500)

        def do_POST(self):
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                return self.send_error(404)
            if not self._authorised():
                return self._err("token 无效", 403)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
            except Exception as e:
                return self._err("请求体不是合法 JSON：%s" % e)
            try:
                return self._post(parsed.path, data)
            except core.JobError as e:
                return self._err(str(e), 409)
            except Exception as e:
                api.log("POST %s 异常：%s" % (parsed.path, e))
                return self._err("内部错误：%s" % e, 500)

        # -- routes ----------------------------------------------------
        def _post(self, path, data):
            cfg = api.config
            if path == "/api/config":
                ok, err = cfg.update(data)
                if not ok:
                    return self._err(err)
                api.reload_tools()
                return self._json({"ok": True, "config": cfg.as_dict()})
            if path == "/api/record/start":
                running = api.runner.status()
                if running["running"]:
                    return self._err("已有任务在运行：%s" % running["kind"], 409)
                serial = api.current_serial()
                if not serial:
                    return self._err("没有可用的 adb 设备（USB 调试打开了吗？）", 409)
                res = api.runner.start_record(cfg.as_dict(), serial, data.get("name", "recording"))
                return self._json({"ok": True, "runner": api.runner.status(), "output": res["output"]})
            if path == "/api/record/stop":
                result = api.runner.stop()
                if cfg.get("screenshot_on_stop"):
                    serial = api.current_serial()
                    if serial:
                        out = os.path.join(api.runner.recordings_dir, "stills",
                                           "stop-%s.png" % time.strftime("%Y%m%d-%H%M%S"))
                        core.screenshot(api.tools, serial, out)
                if cfg.get("open_folder_after_record"):
                    self._reveal(api.runner.recordings_dir)
                return self._json({"ok": True, "result": result, "runner": api.runner.status()})
            if path == "/api/audio/start":
                res = api.runner.start_audio(data.get("device", cfg.get("audio_device", "0")),
                                             data.get("name", "narration"),
                                             cfg.get("audio_rate", 48000), cfg.get("audio_channels", 2))
                return self._json({"ok": True, "runner": api.runner.status(), "output": res["output"]})
            if path == "/api/audio/stop":
                return self._json({"ok": True, "result": api.runner.stop(), "runner": api.runner.status()})
            if path == "/api/mux":
                video, audio = data.get("video") or "", data.get("audio") or ""
                if not os.path.isfile(video) or not os.path.isfile(audio):
                    return self._err("请选择存在的视频和音频文件")
                res = api.runner.mux(video, audio, data.get("name", "muxed"))
                return self._json({"ok": True, "runner": api.runner.status(), "output": res["output"]})
            if path == "/api/screenshot":
                serial = api.current_serial()
                if not serial:
                    return self._err("没有可用的 adb 设备", 409)
                out = os.path.join(api.runner.recordings_dir, "stills",
                                   "%s-%s.png" % (core.safe_name(data.get("name", "shot")),
                                                  time.strftime("%Y%m%d-%H%M%S")))
                ok, message = core.screenshot(api.tools, serial, out)
                return self._json({"ok": True, "output": message}) if ok else self._err(message)
            if path == "/api/push_demos":
                serial = api.current_serial()
                if not serial:
                    return self._err("没有可用的 adb 设备", 409)
                src = data.get("demo_dir") or cfg.get("demo_dir")
                if not src or not os.path.isdir(src):
                    return self._err("演示工程目录不存在，请在设置里填写")
                count, err = core.push_demos(api.tools, serial, src, cfg.get("push_dest", "/sdcard/Download/MobileCAD-demo"))
                if err:
                    return self._err(err)
                return self._json({"ok": True, "pushed": count, "dest": cfg.get("push_dest")})
            if path == "/api/open_folder":
                target = data.get("path") or api.runner.recordings_dir
                if not os.path.isdir(target):
                    return self._err("目录不存在：%s" % target)
                self._reveal(target)
                return self._json({"ok": True})
            return self._err("未知接口", 404)

        def _reveal(self, target):
            try:
                if platform.system() == "Darwin":
                    __import__("subprocess").Popen(["open", target])
                elif platform.system() == "Windows":
                    os.startfile(target)  # type: ignore[attr-defined]
                else:
                    __import__("subprocess").Popen(["xdg-open", target])
            except Exception as e:
                api.log("打开目录失败：%s" % e)

    return Handler


class ServerHandle:
    def __init__(self, config, log=None, port=0):
        self.api = Api(config, log=log)
        self.httpd = None
        self.port = 0
        self._thread = None
        self._wanted_port = port

    def start(self, host="127.0.0.1"):
        handler = make_handler(self.api)
        last = None
        for candidate in ([self._wanted_port] if self._wanted_port else []) + list(range(8765, 8795)):
            try:
                self.httpd = ThreadingHTTPServer((host, candidate), handler)
                self.port = candidate
                break
            except OSError as e:
                last = e
                continue
        if self.httpd is None:
            raise RuntimeError("没有可用端口：%s" % last)
        self.httpd.daemon_threads = True
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        self.api.log("服务已启动 http://%s:%d" % (host, self.port))
        return self

    @property
    def url(self):
        return "http://127.0.0.1:%d/?token=%s" % (self.port, self.api.token)

    def stop(self):
        try:
            self.api.runner.stop()
        except Exception:
            pass
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
