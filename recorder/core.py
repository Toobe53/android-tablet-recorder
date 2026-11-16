"""Device, recording and file helpers. Standard library only.

Every external command goes through run()/Runner, which never raise: failures
come back as (code, text) or as structured job errors with the log line that
explains them.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time

NAME_RE = re.compile(r"[^\w.\-\u4e00-\u9fff]+", re.UNICODE)


def safe_name(name, default="recording"):
    name = NAME_RE.sub("-", (name or "").strip())
    return (name.strip("-._") or default)[:80]


def which(name):
    return shutil.which(name) or name


class Tools:
    """Resolved tool paths; overrides win, PATH is the fallback."""

    def __init__(self, overrides=None):
        o = overrides or {}
        self.adb = o.get("adb_path") or which("adb")
        self.scrcpy = o.get("scrcpy_path") or which("scrcpy")
        self.ffmpeg = o.get("ffmpeg_path") or which("ffmpeg")
        self.ffprobe = o.get("ffprobe_path") or which("ffprobe")

    def as_dict(self):
        return {"adb": self.adb, "scrcpy": self.scrcpy, "ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe}


def run(args, timeout=30):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except FileNotFoundError:
        return 127, "not found: %s" % args[0]
    except subprocess.TimeoutExpired:
        return 124, "timeout after %ss: %s" % (timeout, " ".join(args))
    except Exception as e:  # pragma: no cover
        return 1, "%s: %s" % (type(e).__name__, e)


def versions(tools):
    out = {}
    for key, args in (("adb", [tools.adb, "version"]), ("scrcpy", [tools.scrcpy, "--version"]),
                      ("ffmpeg", [tools.ffmpeg, "-version"]), ("ffprobe", [tools.ffprobe, "-version"])):
        code, text = run(args, timeout=10)
        first = text.strip().splitlines()[0] if text.strip() else ""
        out[key] = {"ok": code == 0, "version": first, "path": args[0]}
    return out


def devices(tools):
    code, text = run([tools.adb, "devices", "-l"], timeout=10)
    if code != 0:
        return []
    found = []
    for line in text.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        model = ""
        for p in parts[2:]:
            if p.startswith("model:"):
                model = p.split(":", 1)[1]
        found.append({"serial": parts[0], "state": parts[1], "model": model})
    return found


def _adb(tools, serial, *args, timeout=20):
    cmd = [tools.adb] + (["-s", serial] if serial else []) + list(args)
    return run(cmd, timeout=timeout)


def device_info(tools, serial=None):
    info = {"serial": serial or "", "model": "", "android": "", "resolution": "",
            "battery": "", "storage": ""}
    code, out = _adb(tools, serial, "shell", "getprop", "ro.product.model")
    info["model"] = out.strip() if code == 0 else ""
    code, out = _adb(tools, serial, "shell", "getprop", "ro.build.version.release")
    info["android"] = out.strip() if code == 0 else ""
    code, out = _adb(tools, serial, "shell", "wm", "size")
    if code == 0:
        m = re.search(r"(\d+x\d+)", out)
        info["resolution"] = m.group(1) if m else out.strip()
    code, out = _adb(tools, serial, "shell", "dumpsys", "battery")
    if code == 0:
        m = re.search(r"level:\s*(\d+)", out)
        if m:
            info["battery"] = m.group(1) + "%"
    code, out = _adb(tools, serial, "shell", "df", "-h", "/sdcard")
    if code == 0:
        lines = [l for l in out.splitlines() if l.strip()]
        if lines and len(lines[-1].split()) >= 4:
            info["storage"] = lines[-1].split()[-2]
    return info


def ffmpeg_audio_devices(tools):
    code, text = run([tools.ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""], timeout=20)
    out, in_audio = [], False
    for line in text.splitlines():
        if "AVFoundation audio devices" in line:
            in_audio = True
            continue
        if in_audio:
            m = re.search(r"\[(\d+)\]\s+(.+)$", line)
            if m:
                out.append({"index": m.group(1), "name": m.group(2).strip()})
            elif line.strip() and not line.startswith("["):
                break
    return out


def probe(tools, path):
    code, text = run([tools.ffprobe, "-v", "error",
                      "-show_entries", "stream=codec_type,codec_name,width,height,sample_rate",
                      "-show_entries", "format=duration,size", "-of", "json", path], timeout=30)
    if code != 0:
        return {"ok": False, "error": text.strip()[:300]}
    try:
        data = json.loads(text)
    except Exception:
        return {"ok": False, "error": "ffprobe output is not JSON"}
    fmt = data.get("format", {})
    return {"ok": True, "streams": data.get("streams", []),
            "duration": float(fmt.get("duration", 0) or 0),
            "size": int(fmt.get("size", 0) or 0)}


def push_demos(tools, serial, src, dest, patterns=(".fcstd", ".stl", ".step", ".ifc", ".txt")):
    code, text = _adb(tools, serial, "shell", "mkdir", "-p", dest)
    if code != 0:
        return 0, "创建目录失败：%s" % text[:200]
    files = sorted(f for f in os.listdir(src) if f.lower().endswith(patterns))
    if not files:
        return 0, "目录里没有可推送的工程文件"
    for name in files:
        code, text = _adb(tools, serial, "push", os.path.join(src, name), dest + "/", timeout=180)
        if code != 0:
            return 0, "推送 %s 失败：%s" % (name, text[:200])
    return len(files), ""


def screenshot(tools, serial, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    code, text = _adb(tools, serial, "exec-out", "screencap", "-p", timeout=30)
    if code != 0:
        return False, "截图命令失败：%s" % text[:200]
    p = subprocess.run([tools.adb] + (["-s", serial] if serial else []) + ["exec-out", "screencap", "-p"],
                       stdout=subprocess.PIPE, timeout=30)
    if p.returncode != 0 or not p.stdout:
        return False, "截图无输出"
    with open(out, "wb") as f:
        f.write(p.stdout)
    return True, out


class JobError(Exception):
    pass


class Runner:
    """One long-running external process at a time; thread-safe and defensive."""

    def __init__(self, tools, log, recordings_dir):
        self._lock = threading.Lock()
        self._proc = None
        self._kind = None
        self._name = None
        self._out = None
        self._started = None
        self.tools = tools
        self._log = log
        self.recordings_dir = recordings_dir

    def set_tools(self, tools):
        self.tools = tools

    def status(self):
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            return {"running": running, "kind": self._kind, "name": self._name,
                    "output": self._out, "elapsed": round(time.time() - self._started, 1) if running and self._started else 0,
                    "pid": self._proc.pid if running else None}

    def busy(self):
        return self.status()["running"]

    def _spawn(self, args, kind, name, out, on_done=None):
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise JobError("已有任务在运行：%s" % self._kind)
            self._log("$ " + " ".join(args))
            try:
                proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, bufsize=1, start_new_session=True)
            except FileNotFoundError:
                raise JobError("找不到命令：%s（请检查设置里的路径）" % args[0])
            except Exception as e:
                raise JobError("启动失败：%s" % e)
            self._proc, self._kind, self._name, self._out = proc, kind, name, out
            self._started = time.time()

        def pump():
            try:
                for line in proc.stdout:
                    self._log(line.rstrip())
            except Exception:
                pass
            code = proc.wait()
            self._log("[%s 结束，退出码 %s]" % (kind, code))
            with self._lock:
                self._proc = None
                self._kind = None
                self._started = None
            if on_done:
                try:
                    on_done(code)
                except Exception as e:
                    self._log("收尾失败：%s" % e)

        threading.Thread(target=pump, daemon=True).start()
        return {"output": out}

    # -- jobs ----------------------------------------------------------
    def start_record(self, cfg, serial, name):
        name = safe_name(name)
        os.makedirs(self.recordings_dir, exist_ok=True)
        out = os.path.join(self.recordings_dir, "%s-%s.mp4" % (name, time.strftime("%Y%m%d-%H%M%S")))
        args = [self.tools.scrcpy]
        if serial:
            args += ["--serial", serial]
        if not cfg.get("mirror"):
            args.append("--no-window")
        if cfg.get("touches"):
            args.append("--show-touches")
        if cfg.get("stay_awake"):
            args.append("--stay-awake")
        args += ["--video-codec=%s" % cfg.get("codec", "h264"),
                 "--max-size=%d" % int(cfg.get("size", 1920)),
                 "--max-fps=%d" % int(cfg.get("fps", 60)),
                 "--video-bit-rate=%s" % cfg.get("bitrate", "16M")]
        if int(cfg.get("video_buffer_ms", 0)) > 0:
            args.append("--video-buffer=%d" % int(cfg["video_buffer_ms"]))
        if int(cfg.get("max_duration_s", 0)) > 0:
            args.append("--time-limit=%d" % int(cfg["max_duration_s"]))
        audio = cfg.get("audio", "mic")
        if audio == "none":
            args.append("--no-audio")
        elif audio in ("mic", "playback"):
            args += ["--audio-source=%s" % audio,
                     "--audio-codec=%s" % cfg.get("audio_codec", "aac"),
                     "--audio-bit-rate=%s" % cfg.get("audio_bitrate", "192k")]
        args += ["--record", out, "--record-format=mp4"]

        def done(code):
            info = probe(self.tools, out) if os.path.exists(out) else {"ok": False, "error": "文件不存在"}
            self._log("录制结果：%s" % json.dumps(info, ensure_ascii=False)[:400])

        return self._spawn(args, "record", name, out, done)

    def start_audio(self, device_index, name, rate=48000, channels=2):
        name = safe_name(name, "audio")
        outdir = os.path.join(self.recordings_dir, "audio")
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, "%s-%s.wav" % (name, time.strftime("%Y%m%d-%H%M%S")))
        args = [self.tools.ffmpeg, "-y", "-hide_banner", "-f", "avfoundation",
                "-i", ":%s" % device_index, "-ac", str(int(channels)), "-ar", str(int(rate)),
                "-c:a", "pcm_s16le", out]
        return self._spawn(args, "audio", name, out)

    def mux(self, video, audio, name):
        name = safe_name(name, "muxed")
        out = os.path.join(self.recordings_dir, "%s-%s.mp4" % (name, time.strftime("%Y%m%d-%H%M%S")))
        args = [self.tools.ffmpeg, "-y", "-hide_banner", "-i", video, "-i", audio,
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out]
        return self._spawn(args, "mux", name, out)

    def stop(self, timeout=12):
        with self._lock:
            proc = self._proc
        if not proc or proc.poll() is not None:
            return {"stopped": False, "reason": "没有正在运行的任务"}
        # SIGTERM lets scrcpy finalise the MP4 (SIGINT only works with a tty/window).
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.send_signal(signal.SIGTERM)
            except Exception:
                pass
        deadline = time.time() + timeout
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.2)
        if proc.poll() is None:
            self._log("[强制结束进程组]")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        return {"stopped": True}
