"""Core helpers: device discovery, command running, recording jobs.

Everything here is deliberately small and dependency-free (stdlib only) so the
tool stays easy to audit and hard to crash. All external calls go through
run()/spawn(), which never raise: they return (code, output).
"""
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid

ADB = shutil.which("adb") or "adb"
SCRCPY = shutil.which("scrcpy") or "scrcpy"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

NAME_RE = re.compile(r"[^\w.\-\u4e00-\u9fff]+", re.UNICODE)


def safe_name(name, default="recording"):
    name = (name or "").strip()
    name = NAME_RE.sub("-", name)
    name = name.strip("-._") or default
    return name[:80]


def run(args, timeout=30, input_bytes=None):
    """Run a command, capture output, never raise."""
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, input=input_bytes)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except FileNotFoundError:
        return 127, "not found: %s" % args[0]
    except subprocess.TimeoutExpired:
        return 124, "timeout after %ss: %s" % (timeout, " ".join(args))
    except Exception as e:  # pragma: no cover - defensive
        return 1, "%s: %s" % (type(e).__name__, e)


def versions():
    out = {}
    for key, cmd in (("adb", [ADB, "version"]), ("scrcpy", [SCRCPY, "--version"]),
                     ("ffmpeg", [FFMPEG, "-version"]), ("ffprobe", [FFPROBE, "-version"])):
        code, text = run(cmd, timeout=10)
        first = text.strip().splitlines()[0] if text.strip() else ""
        out[key] = {"ok": code == 0, "version": first}
    return out


def devices():
    code, text = run([ADB, "devices", "-l"], timeout=10)
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
        serial, state = parts[0], parts[1]
        model = ""
        for p in parts[2:]:
            if p.startswith("model:"):
                model = p.split(":", 1)[1]
        found.append({"serial": serial, "state": state, "model": model})
    return found


def device_info(serial=None):
    def adb(*args):
        cmd = [ADB] + (["-s", serial] if serial else []) + list(args)
        return run(cmd, timeout=15)

    info = {"serial": serial or "", "model": "", "android": "", "resolution": "",
            "battery": "", "storage": ""}
    code, out = adb("shell", "getprop", "ro.product.model")
    info["model"] = out.strip() if code == 0 else ""
    code, out = adb("shell", "getprop", "ro.build.version.release")
    info["android"] = out.strip() if code == 0 else ""
    code, out = adb("shell", "wm", "size")
    if code == 0:
        m = re.search(r"(\d+x\d+)", out)
        info["resolution"] = m.group(1) if m else out.strip()
    code, out = adb("shell", "dumpsys", "battery")
    if code == 0:
        m = re.search(r"level:\s*(\d+)", out)
        if m:
            info["battery"] = m.group(1) + "%"
    code, out = adb("shell", "df", "-h", "/sdcard")
    if code == 0:
        lines = [l for l in out.splitlines() if l.strip()]
        if lines:
            info["storage"] = lines[-1].split()[-2] if len(lines[-1].split()) >= 4 else ""
    return info


def ffmpeg_audio_devices():
    """Parse `ffmpeg -f avfoundation -list_devices true` for audio inputs."""
    code, text = run([FFMPEG, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""], timeout=20)
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


def probe(path):
    code, text = run([FFPROBE, "-v", "error", "-show_entries",
                      "stream=codec_type,codec_name,width,height,sample_rate",
                      "-show_entries", "format=duration,size",
                      "-of", "json", path], timeout=30)
    if code != 0:
        return {"ok": False, "error": text.strip()[:300]}
    try:
        data = json.loads(text)
    except Exception:
        return {"ok": False, "error": "ffprobe output not JSON"}
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    return {"ok": True, "streams": streams,
            "duration": float(fmt.get("duration", 0) or 0),
            "size": int(fmt.get("size", 0) or 0)}


class JobError(Exception):
    pass


class Runner:
    """One long-running external process at a time. Thread-safe, never raises out."""

    def __init__(self, log, recordings_dir):
        self._lock = threading.Lock()
        self._proc = None
        self._kind = None
        self._name = None
        self._out = None
        self._started = None
        self._thread = None
        self._log = log
        self.recordings_dir = recordings_dir

    # -- state ---------------------------------------------------------
    def status(self):
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            elapsed = (time.time() - self._started) if running and self._started else 0
            return {"running": running, "kind": self._kind, "name": self._name,
                    "output": self._out, "elapsed": round(elapsed, 1),
                    "pid": self._proc.pid if running else None}

    def busy(self):
        return self.status()["running"]

    # -- spawning ------------------------------------------------------
    def _spawn(self, args, kind, name, out, on_done=None):
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise JobError("已有任务在运行：%s" % self._kind)
            self._log("$ " + " ".join(args))
            try:
                proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, bufsize=1, start_new_session=True)
            except FileNotFoundError:
                raise JobError("找不到命令：%s（请先安装）" % args[0])
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
                    self._log("回调失败：%s" % e)

        self._thread = threading.Thread(target=pump, daemon=True)
        self._thread.start()
        return {"output": out}

    # -- public jobs ---------------------------------------------------
    def start_record(self, serial, name, audio, size, fps, bitrate, touches, mirror, extra=None):
        name = safe_name(name)
        os.makedirs(self.recordings_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = os.path.join(self.recordings_dir, "%s-%s.mp4" % (name, stamp))
        args = [SCRCPY]
        if serial:
            args += ["--serial", serial]
        if not mirror:
            args.append("--no-window")
        if touches:
            args.append("--show-touches")
        args += ["--stay-awake", "--max-size=%d" % int(size),
                 "--max-fps=%d" % int(fps), "--video-bit-rate=%s" % bitrate]
        if audio in ("mic", "playback"):
            args += ["--audio-source=%s" % audio, "--audio-codec=aac", "--audio-bit-rate=192k"]
        args += ["--record", out, "--record-format=mp4"]
        if extra:
            args += extra

        def done(code):
            info = probe(out) if os.path.exists(out) else {"ok": False, "error": "文件不存在"}
            self._log("录制结果：%s" % json.dumps(info, ensure_ascii=False)[:400])

        return self._spawn(args, "record", name, out, done)

    def start_audio(self, device_index, name):
        name = safe_name(name, "audio")
        outdir = os.path.join(self.recordings_dir, "audio")
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, "%s-%s.wav" % (name, time.strftime("%Y%m%d-%H%M%S")))
        args = [FFMPEG, "-y", "-hide_banner", "-f", "avfoundation",
                "-i", ":%s" % device_index, "-ac", "2", "-ar", "48000",
                "-c:a", "pcm_s16le", out]
        return self._spawn(args, "audio", name, out)

    def mux(self, video, audio, name):
        name = safe_name(name, "muxed")
        out = os.path.join(self.recordings_dir, "%s-%s.mp4" % (name, time.strftime("%Y%m%d-%H%M%S")))
        args = [FFMPEG, "-y", "-hide_banner", "-i", video, "-i", audio,
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out]
        return self._spawn(args, "mux", name, out)

    def stop(self, timeout=12):
        with self._lock:
            proc = self._proc
        if not proc or proc.poll() is not None:
            return {"stopped": False, "reason": "没有正在运行的任务"}
        # SIGTERM first: scrcpy finalises the mp4 container on SIGTERM (verified
        # on macOS 26 + scrcpy 3.3.3; SIGINT only works when a tty/窗口 is attached).
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
