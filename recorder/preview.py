"""Live preview (screencap -> JPEG) and microphone level meter."""
import io
import re
import subprocess
import threading
import time

try:
    from PIL import Image
except Exception:  # pragma: no cover - preview disabled without Pillow
    Image = None


class Preview:
    """Periodically grabs a screenshot and keeps the latest JPEG frame.

    The UI polls /api/preview.jpg at preview_fps; this keeps the HTTP side
    stateless and avoids multipart quirks in embedded webviews.
    """

    def __init__(self, tools, log):
        self.tools = tools
        self.log = log
        self._lock = threading.Lock()
        self._frame = None
        self._seq = 0
        self._running = False
        self._thread = None
        self._error = ""

    def start(self, serial, fps=4, width=720, quality=70):
        self.stop()
        if Image is None:
            self._error = "缺少 Pillow，无法生成预览"
            return False, self._error
        self._running = True
        self._error = ""
        self._thread = threading.Thread(target=self._loop, args=(serial, fps, width, quality), daemon=True)
        self._thread.start()
        return True, ""

    def _loop(self, serial, fps, width, quality):
        interval = 1.0 / max(1, min(15, fps))
        fails = 0
        while self._running:
            started = time.time()
            cmd = [self.tools.adb] + (["-s", serial] if serial else []) + ["exec-out", "screencap", "-p"]
            try:
                p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
                if p.returncode == 0 and p.stdout:
                    img = Image.open(io.BytesIO(p.stdout)).convert("RGB")
                    if img.width > width:
                        img.thumbnail((width, 10000))
                    buf = io.BytesIO()
                    img.save(buf, "JPEG", quality=int(quality))
                    with self._lock:
                        self._frame = buf.getvalue()
                        self._seq += 1
                    fails = 0
                else:
                    fails += 1
            except Exception as e:
                fails += 1
                self._error = str(e)
            if fails == 3:
                self.log("预览连续失败：%s" % (self._error or "screencap 无输出"))
            time.sleep(max(0.02, interval - (time.time() - started)))

    def stop(self):
        self._running = False
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2)
        self._thread = None

    def frame(self):
        with self._lock:
            return self._frame, self._seq

    def status(self):
        frame, seq = self.frame()
        return {"running": self._running, "seq": seq, "bytes": len(frame) if frame else 0, "error": self._error}


class LevelMeter:
    """Reads RMS/peak levels from ffmpeg's astats on the Mac microphone."""

    RMS_RE = re.compile(r"RMS_level=(-?\d+(?:\.\d+)?)")
    PEAK_RE = re.compile(r"Peak_level=(-?\d+(?:\.\d+)?)")

    def __init__(self, tools, log):
        self.tools = tools
        self.log = log
        self._proc = None
        self._thread = None
        self._lock = threading.Lock()
        self._rms = -90.0
        self._peak = -90.0
        self._error = ""

    def start(self, device="0"):
        self.stop()
        cmd = [self.tools.ffmpeg, "-hide_banner", "-loglevel", "error",
               "-f", "avfoundation", "-i", ":%s" % device,
               "-af", "astats=metadata=1:reset=1,ametadata=mode=print:file=-",
               "-f", "null", "-"]
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          text=True, bufsize=1)
        except Exception as e:
            self._error = str(e)
            return False, self._error
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        return True, ""

    def _read(self):
        proc = self._proc
        if not proc:
            return
        try:
            for line in proc.stdout:
                m = self.RMS_RE.search(line)
                if m:
                    with self._lock:
                        self._rms = float(m.group(1))
                    continue
                m = self.PEAK_RE.search(line)
                if m:
                    with self._lock:
                        self._peak = float(m.group(1))
        except Exception:
            pass

    def stop(self):
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=4)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def status(self):
        running = bool(self._proc and self._proc.poll() is None)
        with self._lock:
            return {"running": running, "rms": self._rms, "peak": self._peak, "error": self._error}
