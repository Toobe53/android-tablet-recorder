const TOKEN = new URLSearchParams(location.search).get("token") || "";
let STATE = null, lastLog = "", audioRunning = false, previewTimer = null, meterTimer = null;

const $ = id => document.getElementById(id);
const fmtSize = n => !n && n !== 0 ? "" :
  n > 1 << 30 ? (n / (1 << 30)).toFixed(2) + " GB" :
  n > 1 << 20 ? (n / (1 << 20)).toFixed(1) + " MB" : Math.round(n / 1024) + " KB";
const fmtTime = s => { s = Math.max(0, Math.round(s || 0)); return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0"); };
const setVal = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v; };
const setCheck = (id, v) => { const el = $(id); if (el) el.checked = !!v; };

function toast(msg, isErr) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.className = "toast", isErr ? 6000 : 3000);
}

async function api(path, body) {
  const opt = { headers: { "X-Token": TOKEN } };
  if (body !== undefined) {
    opt.method = "POST";
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  let res, data;
  try { res = await fetch(path, opt); } catch (e) { throw new Error("无法连接本地服务：" + e.message); }
  try { data = await res.json(); } catch { data = { ok: res.ok }; }
  if (!res.ok || data.ok === false) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

function collectSettings() {
  return {
    recordings_dir: $("recDir").value.trim(), demo_dir: $("demoDir").value.trim(),
    push_dest: $("pushDest").value.trim(), serial: $("serial").value.trim(),
    adb_path: $("adbPath").value.trim(), scrcpy_path: $("scrcpyPath").value.trim(),
    ffmpeg_path: $("ffmpegPath").value.trim(), ffprobe_path: $("ffprobePath").value.trim(),
    audio_codec: $("audioCodec").value, audio_bitrate: $("audioBitrate").value.trim(),
    audio_rate: Number($("audioRate").value), audio_channels: Number($("audioChannels").value),
    preview_fps: Number($("previewFps").value), preview_width: Number($("previewWidth").value),
    preview_quality: Number($("previewQuality").value),
    auto_preview: $("autoPreview").checked,
    open_folder_after_record: $("openAfter").checked, screenshot_on_stop: $("shotOnStop").checked,
  };
}

function collectRecord() {
  return {
    size: Number($("size").value), fps: Number($("fps").value), bitrate: $("bitrate").value.trim(),
    codec: $("codec").value, video_buffer_ms: Number($("buffer").value || 0),
    max_duration_s: Number($("maxdur").value || 0), audio: $("audio").value,
    touches: $("touches").checked, mirror: $("mirror").checked, stay_awake: $("awake").checked,
    sync_offset_ms: Number($("syncOffset").value || 0), sync_audio_device: $("audioDev").value,
    container: $("container").value, filename_template: $("filenameTemplate").value.trim() || "{name}-{date}-{time}",
    transcode: $("transcode").checked, tc_codec: $("tcCodec").value, tc_crf: Number($("tcCrf").value),
    tc_preset: $("tcPreset").value, tc_scale: $("tcScale").value, tc_fps: Number($("tcFps").value || 0),
    tc_audio_codec: $("tcAudioCodec").value, keep_original: $("keepOriginal").checked,
  };
}

function render(state) {
  STATE = state;
  const dev = (state.devices || []).find(d => d.serial === state.device);
  const online = dev && dev.state === "device";
  $("deviceDot").className = "dot " + (online ? "on" : "off");
  $("deviceText").textContent = online ? ((state.info.model || dev.model || "设备") + " · " + dev.serial) : "未连接设备";
  const info = state.info || {};
  $("deviceInfo").innerHTML = [
    ["型号", info.model || "—"], ["Android", info.android || "—"],
    ["分辨率", info.resolution || "—"], ["电量", info.battery || "—"],
    ["存储可用", info.storage || "—"], ["序列号", state.device || "—"],
  ].map(([k, v]) => `<span>${k}：<b>${v}</b></span>`).join("");
  $("versions").innerHTML = Object.entries(state.versions || {}).map(([k, v]) =>
    `<span class="pill ${v.ok ? "ok" : "bad"}" title="${v.path || ""}">${k} ${v.ok ? "✓" : "缺失"}</span>`).join("");

  const c = state.config || {};
  setVal("size", String(c.size)); setVal("fps", String(c.fps)); setVal("bitrate", c.bitrate);
  setVal("codec", c.codec); setVal("buffer", String(c.video_buffer_ms)); setVal("maxdur", String(c.max_duration_s));
  setVal("audio", c.audio); setCheck("touches", c.touches); setCheck("mirror", c.mirror); setCheck("awake", c.stay_awake);
  setVal("recDir", c.recordings_dir); setVal("demoDir", c.demo_dir); setVal("pushDest", c.push_dest);
  setVal("serial", c.serial); setVal("adbPath", c.adb_path); setVal("scrcpyPath", c.scrcpy_path);
  setVal("ffmpegPath", c.ffmpeg_path); setVal("ffprobePath", c.ffprobe_path);
  setVal("audioCodec", c.audio_codec); setVal("audioBitrate", c.audio_bitrate);
  setVal("audioRate", String(c.audio_rate)); setVal("audioChannels", String(c.audio_channels));
  setVal("previewFps", String(c.preview_fps)); setVal("previewWidth", String(c.preview_width));
  setVal("previewQuality", String(c.preview_quality));
  setVal("syncOffset", String(c.sync_offset_ms));
  setVal("container", c.container); setVal("filenameTemplate", c.filename_template);
  setCheck("transcode", c.transcode); setVal("tcCodec", c.tc_codec); setVal("tcCrf", String(c.tc_crf));
  setVal("tcPreset", c.tc_preset); setVal("tcScale", c.tc_scale); setVal("tcFps", String(c.tc_fps));
  setVal("tcAudioCodec", c.tc_audio_codec); setCheck("keepOriginal", c.keep_original);
  setCheck("autoPreview", c.auto_preview);
  setCheck("openAfter", c.open_folder_after_record); setCheck("shotOnStop", c.screenshot_on_stop);
  $("configPath").textContent = "配置：" + (state.config_path || "");
  $("pushHint").textContent = c.demo_dir ? "推送到 " + c.push_dest : "先填写「设置 → 演示工程目录」";

  const r = state.runner || {};
  const running = !!r.running;
  const btn = $("recBtn");
  btn.disabled = running && r.kind !== "record";
  if (running && r.kind === "record") { btn.textContent = "停止录制"; btn.className = "btn primary big stop"; }
  else if (running && r.kind === "transcode") { btn.textContent = "转码中…"; btn.className = "btn primary big"; btn.disabled = true; }
  else { btn.textContent = "开始录制"; btn.className = "btn primary big"; }
  $("timer").textContent = running ? fmtTime(r.elapsed) : "00:00";
  if (r.output) $("recOut").textContent = "输出：" + r.output;
  audioRunning = running && r.kind === "audio";
  $("audioBtn").textContent = audioRunning ? "停止录音" : "开始录音";
  $("audioBtn").className = "btn" + (audioRunning ? " primary stop" : "");

  const pv = state.preview || {};
  $("prevBtn").textContent = pv.running ? "关闭预览" : "开启预览";
  $("preview").hidden = !pv.running;
  $("previewEmpty").hidden = !!pv.running;
  if (pv.running) startPreviewLoop(); else stopPreviewLoop();

  const mt = state.meter || {};
  $("monBtn").textContent = mt.running ? "停止电平" : "麦克风电平";
  if (mt.running) startMeterLoop(); else stopMeterLoop();

  const outs = state.outputs || [];
  fillSelect("muxVideo", outs.filter(o => /\.(mp4|mkv)$/.test(o.path)).map(o => [o.path, `${o.rel} (${fmtSize(o.size)})`]));
  fillSelect("muxAudio", outs.filter(o => /\.(wav|m4a)$/i.test(o.path)).map(o => [o.path, `${o.rel} (${fmtSize(o.size)})`]));
  $("outputs").innerHTML = outs.slice(0, 12).map(o => `<li><b>${o.rel}</b><span>${fmtSize(o.size)}</span></li>`).join("") || "<li><span>还没有录制文件</span></li>";
  renderLog((state.log || []).join("\n"));
}

function fillSelect(id, items) {
  const sel = $(id), cur = sel.value;
  sel.innerHTML = items.map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
  if (items.some(([v]) => v === cur)) sel.value = cur;
}

function renderLog(text) {
  if (text === lastLog) return;
  lastLog = text;
  const el = $("log"), bottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
  el.textContent = text;
  if (bottom) el.scrollTop = el.scrollHeight;
}

async function refresh(showToast) {
  try { render(await api("/api/state")); if (showToast) toast("已刷新"); }
  catch (e) { toast(e.message, true); }
}

/* ---------- preview ---------- */
let previewBusy = false;
function startPreviewLoop() {
  if (previewTimer) return;
  const fps = Math.max(1, Math.min(15, (STATE.config.preview_fps || 4)));
  const tick = () => {
    if (previewBusy) return;
    previewBusy = true;
    const img = $("preview");
    img.onload = () => { previewBusy = false; };
    img.onerror = () => { previewBusy = false; };
    img.src = `/api/preview.jpg?token=${encodeURIComponent(TOKEN)}&t=${Date.now()}`;
  };
  previewTimer = setInterval(tick, Math.round(1000 / fps));
  tick();
}
function stopPreviewLoop() { if (previewTimer) { clearInterval(previewTimer); previewTimer = null; } }

async function togglePreview() {
  try {
    if (STATE.preview && STATE.preview.running) { await api("/api/preview/stop", {}); toast("预览已关闭"); }
    else {
      const r = await api("/api/preview/start", {
        preview_fps: Number($("previewFps").value), preview_width: Number($("previewWidth").value),
        preview_quality: Number($("previewQuality").value),
      });
      toast("预览已开启");
    }
    setTimeout(() => refresh(false), 400);
  } catch (e) { toast(e.message, true); }
}

/* ---------- meter ---------- */
function startMeterLoop() {
  if (meterTimer) return;
  meterTimer = setInterval(async () => {
    try {
      const r = await api("/api/level");
      const m = r.meter || {};
      const rms = Number(m.rms ?? -90);
      const pct = Math.max(0, Math.min(100, (rms + 60) / 60 * 100));
      $("meterFill").style.width = pct.toFixed(0) + "%";
      $("meterVal").textContent = rms <= -89 ? "−∞ dB" : rms.toFixed(1) + " dB";
    } catch { /* keep quiet */ }
  }, 150);
}
function stopMeterLoop() {
  if (meterTimer) { clearInterval(meterTimer); meterTimer = null; }
  $("meterFill").style.width = "0%";
  $("meterVal").textContent = "−∞ dB";
}
async function toggleMonitor() {
  try {
    if (STATE.meter && STATE.meter.running) { await api("/api/monitor/stop", {}); toast("电平监听已停止"); }
    else { await api("/api/monitor/start", { device: $("audioDev").value }); toast("电平监听已开启（Mac 麦克风）"); }
    setTimeout(() => refresh(false), 300);
  } catch (e) { toast(e.message, true); }
}

/* ---------- actions ---------- */
async function saveSettings() {
  try { await api("/api/config", { ...collectSettings(), ...collectRecord() }); toast("设置已保存"); refresh(false); }
  catch (e) { toast(e.message, true); }
}

async function resetSettings() {
  if (!confirm("恢复为默认设置？")) return;
  try {
    await api("/api/config", {
      recordings_dir: "", demo_dir: "", push_dest: "/sdcard/Download/MobileCAD-demo", serial: "",
      adb_path: "", scrcpy_path: "", ffmpeg_path: "", ffprobe_path: "",
      size: 1920, fps: 60, bitrate: "16M", codec: "h264", video_buffer_ms: 0, max_duration_s: 0,
      audio: "mic", audio_codec: "aac", audio_bitrate: "192k", audio_rate: 48000, audio_channels: 2,
      preview_fps: 4, preview_width: 720, preview_quality: 70,
      touches: true, mirror: false, stay_awake: true,
      container: "mp4", filename_template: "{name}-{date}-{time}", transcode: false, tc_codec: "h264",
      tc_crf: 23, tc_preset: "medium", tc_scale: "original", tc_fps: 0, tc_audio_codec: "aac",
      tc_audio_bitrate: "192k", keep_original: true,
      auto_preview: false, open_folder_after_record: false, screenshot_on_stop: false,
    });
    toast("已恢复默认"); refresh(false);
  } catch (e) { toast(e.message, true); }
}

function toggleSettings() { $("settings").hidden = !$("settings").hidden; }
function toggleLog() {
  $("logDrawer").classList.toggle("open");
  document.body.classList.toggle("log-open", $("logDrawer").classList.contains("open"));
}

async function toggleRecord() {
  try {
    if (STATE.runner && STATE.runner.running && STATE.runner.kind === "record") {
      await api("/api/record/stop", {});
      toast("已停止，正在收尾/转码…");
    } else {
      await api("/api/config", { ...collectRecord(), ...collectSettings() });
      const r = await api("/api/record/start", { name: $("name").value.trim() || "recording",
        sync: $("syncMic").checked });
      toast("开始录制 → " + r.output);
      stopPreviewLoop();
    }
    setTimeout(() => refresh(false), 800);
  } catch (e) { toast(e.message, true); setTimeout(() => refresh(false), 300); }
}

async function toggleAudio() {
  try {
    if (audioRunning) { await api("/api/audio/stop", {}); toast("录音已停止"); }
    else { const r = await api("/api/audio/start", { device: $("audioDev").value, name: $("audioName").value.trim() || "narration" }); toast("开始录音 → " + r.output); }
    setTimeout(() => refresh(false), 500);
  } catch (e) { toast(e.message, true); }
}

async function refreshAudioDevices() {
  try {
    const r = await api("/api/audio_devices");
    $("audioDev").innerHTML = (r.devices || []).map(d => `<option value="${d.index}">${d.index} · ${d.name}</option>`).join("") || `<option value="0">0（默认）</option>`;
    toast(`找到 ${(r.devices || []).length} 个输入设备`);
  } catch (e) { toast(e.message, true); }
}

async function screenshot() {
  try { const r = await api("/api/screenshot", { name: $("name").value.trim() || "shot" }); toast("已截图 → " + r.output); refresh(false); }
  catch (e) { toast(e.message, true); }
}
async function pushDemos() {
  try { const r = await api("/api/push_demos", { demo_dir: $("demoDir").value.trim() }); toast(`已推送 ${r.pushed} 个文件到 ${r.dest}`); }
  catch (e) { toast(e.message, true); }
}
async function mux() {
  try { const r = await api("/api/mux", { video: $("muxVideo").value, audio: $("muxAudio").value, name: "muxed" }); toast("正在合成 → " + r.output); setTimeout(() => refresh(false), 1200); }
  catch (e) { toast(e.message, true); }
}
async function openFolder() { try { await api("/api/open_folder", { path: $("recDir").value.trim() }); } catch (e) { toast(e.message, true); } }
function clearLog() { $("log").textContent = ""; lastLog = ""; }

function applyPreset() {
  const p = $("preset").value;
  const presets = {
    high: { size: 2560, fps: 60, bitrate: "24M", buffer: 0, codec: "h264" },
    balanced: { size: 1920, fps: 60, bitrate: "16M", buffer: 0, codec: "h264" },
    lite: { size: 1600, fps: 30, bitrate: "8M", buffer: 200, codec: "h264" },
  };
  if (!presets[p]) return;
  const x = presets[p];
  $("size").value = String(x.size); $("fps").value = String(x.fps);
  $("bitrate").value = x.bitrate; $("buffer").value = String(x.buffer); $("codec").value = x.codec;
  $("preset").value = "";
  toast("已应用预设，开始录制时自动保存");
}

window.scrollTo(0, 0);
refresh(false);
setInterval(() => refresh(false), 2000);
