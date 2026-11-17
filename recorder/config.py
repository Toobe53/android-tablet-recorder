"""Configuration with validation and atomic persistence."""
import json
import os
import platform
import tempfile
import threading

DEFAULTS = {
    # device
    "serial": "",
    "adb_path": "",
    "scrcpy_path": "",
    "ffmpeg_path": "",
    "ffprobe_path": "",
    # files
    "recordings_dir": "",
    "demo_dir": "",
    "push_dest": "/sdcard/Download/MobileCAD-demo",
    # video (performance-relevant)
    "size": 1920,
    "fps": 60,
    "bitrate": "16M",
    "codec": "h264",          # h264 | h265 | av1
    "video_buffer_ms": 0,     # 0 = scrcpy 默认；>0 增加缓冲，抗卡顿
    "max_duration_s": 0,      # 0 = 不限时
    "touch_mode": "record",
    "touches": True,
    "mirror": False,
    "stay_awake": True,
    # audio
    "audio": "mic",           # mic | playback | none
    "audio_codec": "aac",     # aac | opus
    "audio_bitrate": "192k",
    "audio_device": "0",
    "audio_rate": 48000,
    "audio_channels": 2,
    "denoise_mode": "medium",
    "denoise_nr": 12,
    "denoise_nf": -40,
    "denoise_hp": 90,
    "denoise_gate": False,
    "denoise_loudnorm": False,
    "tablet_denoise": True,
    # live preview / level meter
    "preview_fps": 4,
    "preview_width": 720,
    "preview_quality": 70,
    "monitor_level": False,
    "sync_offset_ms": 0,
    "sync_audio_device": "0",
    "auto_preview": False,
    # output / post-processing
    "container": "mp4",
    "filename_template": "{name}-{date}-{time}",
    "transcode": False,
    "tc_codec": "h264",
    "tc_crf": 23,
    "tc_preset": "medium",
    "tc_scale": "original",
    "tc_fps": 0,
    "tc_audio_codec": "aac",
    "tc_audio_bitrate": "192k",
    "keep_original": True,
    # after recording
    "open_folder_after_record": False,
    "screenshot_on_stop": False,
    # ui
    "theme": "dark",
    "port": 0,
}

CHOICES = {
    "codec": {"h264", "h265", "av1"},
    "audio": {"mic", "playback", "none"},
    "audio_codec": {"aac", "opus"},
    "theme": {"dark", "light"},
    "touch_mode": {"off", "record", "persistent"},
    "denoise_mode": {"off", "light", "medium", "strong", "custom"},
    "container": {"mp4", "mkv"},
    "tc_codec": {"h264", "h265"},
    "tc_preset": {"ultrafast", "fast", "medium", "slow"},
    "tc_scale": {"original", "1080", "720"},
    "tc_audio_codec": {"aac", "opus", "copy"},
}
INTS = {
    "size": (0, 4096), "fps": (15, 120), "video_buffer_ms": (0, 2000),
    "max_duration_s": (0, 6 * 3600), "audio_rate": (8000, 192000),
    "audio_channels": (1, 2), "port": (0, 65535),
    "preview_fps": (1, 15), "preview_width": (320, 1920), "preview_quality": (30, 95),
    "tc_crf": (0, 51), "tc_fps": (0, 120), "sync_offset_ms": (-3000, 3000),
    "denoise_nr": (0, 40), "denoise_nf": (-80, -20), "denoise_hp": (0, 300),
}
BOOLS = {"touches", "mirror", "stay_awake", "open_folder_after_record", "screenshot_on_stop",
         "monitor_level", "transcode", "keep_original", "auto_preview",
         "denoise_gate", "denoise_loudnorm", "tablet_denoise"}


def _platform_dirs():
    if platform.system() == "Darwin":
        cfg = os.path.expanduser("~/Library/Application Support/MobileCAD Recorder")
        rec = os.path.expanduser("~/Movies/MobileCAD Recorder")
    elif platform.system() == "Windows":
        cfg = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MobileCAD Recorder")
        rec = os.path.join(os.path.expanduser("~"), "Videos", "MobileCAD Recorder")
    else:
        cfg = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "mobilecad-recorder")
        rec = os.path.join(os.path.expanduser("~"), "Videos", "MobileCAD Recorder")
    return cfg, rec


class Config:
    def __init__(self, path=None):
        cfg_dir, rec_dir = _platform_dirs()
        self.path = os.path.abspath(os.path.expanduser(
            os.environ.get("MCR_CONFIG") or path or os.path.join(cfg_dir, "config.json")))
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        self.data["recordings_dir"] = os.environ.get("MCR_RECORDINGS") or rec_dir
        self.load()

    # -- io ------------------------------------------------------------
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if key in DEFAULTS:
                        self.data[key] = value
        except FileNotFoundError:
            pass
        except Exception as e:
            print("config read failed: %s" % e, flush=True)
        self._repair_paths()
        self.save()

    def _repair_paths(self):
        if not self.data.get("recordings_dir"):
            self.data["recordings_dir"] = _platform_dirs()[1]
        if not self.data.get("demo_dir"):
            candidate = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "video-course", "demo")
            candidate = os.path.normpath(candidate)
            if os.path.isdir(candidate):
                self.data["demo_dir"] = candidate

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with self._lock:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            return True, ""
        except Exception as e:
            return False, str(e)

    # -- access --------------------------------------------------------
    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def as_dict(self):
        return dict(self.data)

    def update(self, patch):
        """Validate and apply a patch. Returns (ok, error_message)."""
        clean = {}
        for key, value in (patch or {}).items():
            if key not in DEFAULTS:
                continue
            if key in CHOICES and value not in CHOICES[key]:
                return False, "参数 %s 只能是 %s" % (key, "/".join(sorted(CHOICES[key])))
            if key in INTS:
                try:
                    value = int(value)
                except Exception:
                    return False, "参数 %s 需要整数" % key
                lo, hi = INTS[key]
                if not lo <= value <= hi:
                    return False, "参数 %s 超出范围 %s–%s" % (key, lo, hi)
            if key in BOOLS:
                value = bool(value)
            if key in ("bitrate", "audio_bitrate", "tc_audio_bitrate"):
                value = str(value).strip()
                if not value or not value[-1] in "kKmM":
                    return False, "%s 应写成 8M / 192k" % key
            if key in ("adb_path", "scrcpy_path", "ffmpeg_path", "ffprobe_path",
                       "recordings_dir", "demo_dir", "push_dest", "serial", "filename_template",
                       "sync_audio_device"):
                value = str(value).strip()
            clean[key] = value
        self.data.update(clean)
        ok, err = self.save()
        if not ok:
            return False, "保存配置失败：%s" % err
        return True, ""
