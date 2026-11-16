const TOKEN = new URLSearchParams(location.search).get("token") || "";
let STATE = null;
let logText = "";
let lastLogTail = "";
let audioRunning = false;

function $(id) { return document.getElementById(id); }

function toast(msg, isErr) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = "toast"; }, isErr ? 6000 : 3000);
}

async function api(path, body) {
  const opt = { headers: { "X-Token": TOKEN } };
  if (body !== undefined) {
    opt.method = "POST";
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  let res, data;
  try {
    res = await fetch(path, opt);
  } catch (e) {
    throw new Error("无法连接本地服务：" + e.message);
  }
  try { data = await res.json(); } catch (e) { data = { ok: res.ok }; }
  if (!res.ok || data.ok === false) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

function fmtSize(n) {
  if (!n && n !== 0) return "";
  if (n > 1 << 30) return (n / (1 << 30)).toFixed(2) + " GB";
  if (n > 1 << 20) return (n / (1 << 20)).toFixed(1) + " MB";
  return Math.round(n / 1024) + " KB";
}

function fmtTime(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const m = String(Math.floor(sec / 60)).padStart(2, "0");
  const s = String(sec % 60).padStart(2, "0");
  return m + ":" + s;
}

function render(state) {
  STATE = state;
  const dev = (state.devices || []).find(d => d.serial === state.device);
  const online = dev && dev.state === "device";
  $("deviceDot").className = "dot " + (online ? "on" : "off");
  $("deviceText").textContent = online
    ? (state.info.model || dev.model || "设备") + " · " + dev.serial
    : "未连接设备";

  const info = state.info || {};
  $("deviceInfo").innerHTML = [
    ["型号", info.model || "—"], ["Android", info.android || "—"],
    ["分辨率", info.resolution || "—"], ["电量", info.battery || "—"],
    ["存储可用", info.storage || "—"], ["设备序列号", state.device || "—"],
  ].map(([k, v]) => `<span>${k}：<b>${v}</b></span>`).join("");

  const vers = state.versions || {};
  $("versions").innerHTML = Object.entries(vers).map(([k, v]) =>
    `<span class="pill ${v.ok ? "ok" : "bad"}">${k} ${v.ok ? "✓" : "缺失"}</span>`).join("");

  const runner = state.runner || {};
  const running = !!runner.running;
  const recBtn = $("recBtn");
  recBtn.disabled = false;
  if (running && runner.kind === "record") {
    recBtn.textContent = "停止录制";
    recBtn.className = "btn primary big stop";
    $("timer").textContent = fmtTime(runner.elapsed);
  } else if (running) {
    recBtn.textContent = "有其他任务运行中";
    recBtn.className = "btn primary big";
    recBtn.disabled = true;
    $("timer").textContent = fmtTime(runner.elapsed);
  } else {
    recBtn.textContent = "开始录制";
    recBtn.className = "btn primary big";
    $("timer").textContent = "00:00";
  }
  if (runner.output) $("recOut").textContent = "当前/最近输出：" + runner.output;

  const audio = running && runner.kind === "audio";
  $("audioBtn").textContent = audio ? "停止录音" : "开始录音";
  $("audioBtn").className = "btn" + (audio ? " primary stop" : "");
  audioRunning = audio;

  const c = state.config || {};
  if (document.activeElement !== $("name")) $("name").value = c.serial ? $("name").value : $("name").value;
  $("size").value = String(c.size || 1920);
  $("fps").value = String(c.fps || 60);
  $("bitrate").value = c.bitrate || "16M";
  $("audio").value = c.audio || "mic";
  $("touches").checked = !!c.touches;
  $("mirror").checked = !!c.mirror;
  $("recDir").value = c.recordings_dir || "";
  $("demoDir").value = c.demo_dir || "";
  $("configPath").textContent = "配置：" + (state.config_path || "");
  $("pushHint").textContent = c.demo_dir
    ? "将推送到 /sdcard/Download/MobileCAD-demo"
    : "先填写「目录设置 → 演示工程目录」再推送";

  const outs = state.outputs || [];
  const videos = outs.filter(o => o.path.endsWith(".mp4"));
  const audios = outs.filter(o => /\.(wav|m4a)$/i.test(o.path));
  fillSelect("muxVideo", videos.map(o => [o.path, o.rel + " (" + fmtSize(o.size) + ")"]));
  fillSelect("muxAudio", audios.map(o => [o.path, o.rel + " (" + fmtSize(o.size) + ")"]));

  $("outputs").innerHTML = outs.slice(0, 12).map(o =>
    `<li><b>${o.rel}</b><span>${fmtSize(o.size)}</span></li>`).join("") ||
    `<li><span>还没有录制文件</span></li>`;

  renderLog((state.log || []).join("\n"));
}

function fillSelect(id, items) {
  const sel = $(id);
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = items.map(([v, label]) => `<option value="${v}">${label}</option>`).join("");
  if (items.some(([v]) => v === current)) sel.value = current;
}

function renderLog(text) {
  const el = $("log");
  if (text === lastLogTail) return;
  lastLogTail = text;
  const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
  el.textContent = text;
  if (atBottom) el.scrollTop = el.scrollHeight;
}

async function refresh(showToast) {
  try {
    const s = await api("/api/state");
    render(s);
    if (showToast) toast("已刷新");
  } catch (e) {
    toast(e.message, true);
  }
}

async function toggleRecord() {
  if (!STATE) return;
  const running = STATE.runner && STATE.runner.running;
  try {
    if (running && STATE.runner.kind === "record") {
      await api("/api/record/stop", {});
      toast("已停止，文件正在收尾…");
    } else {
      const body = {
        name: $("name").value.trim() || "recording",
        audio: $("audio").value,
        size: Number($("size").value),
        fps: Number($("fps").value),
        bitrate: $("bitrate").value.trim(),
        touches: $("touches").checked,
        mirror: $("mirror").checked,
      };
      const r = await api("/api/record/start", body);
      toast("开始录制 → " + r.output);
    }
    setTimeout(() => refresh(false), 600);
  } catch (e) {
    toast(e.message, true);
    setTimeout(() => refresh(false), 300);
  }
}

async function toggleAudio() {
  try {
    if (audioRunning) {
      await api("/api/audio/stop", {});
      toast("录音已停止");
    } else {
      const r = await api("/api/audio/start", {
        device: $("audioDev").value,
        name: $("audioName").value.trim() || "narration",
      });
      toast("开始录音 → " + r.output);
    }
    setTimeout(() => refresh(false), 500);
  } catch (e) {
    toast(e.message, true);
  }
}

async function refreshAudioDevices() {
  try {
    const r = await api("/api/audio_devices");
    const sel = $("audioDev");
    sel.innerHTML = (r.devices || []).map(d =>
      `<option value="${d.index}">${d.index} · ${d.name}</option>`).join("") ||
      `<option value="0">0（默认）</option>`;
    toast(`找到 ${(r.devices || []).length} 个输入设备`);
  } catch (e) {
    toast(e.message, true);
  }
}

async function screenshot() {
  try {
    const r = await api("/api/screenshot", { name: $("name").value.trim() || "shot" });
    toast("已截图 → " + r.output);
    refresh(false);
  } catch (e) { toast(e.message, true); }
}

async function pushDemos() {
  try {
    const r = await api("/api/push_demos", { demo_dir: $("demoDir").value.trim() });
    toast(`已推送 ${r.pushed} 个文件到 ${r.dest}`);
  } catch (e) { toast(e.message, true); }
}

async function mux() {
  try {
    const r = await api("/api/mux", { video: $("muxVideo").value, audio: $("muxAudio").value, name: "muxed" });
    toast("正在合成 → " + r.output);
    setTimeout(() => refresh(false), 1000);
  } catch (e) { toast(e.message, true); }
}

async function saveSettings() {
  try {
    await api("/api/config", {
      recordings_dir: $("recDir").value.trim(),
      demo_dir: $("demoDir").value.trim(),
    });
    toast("设置已保存");
    refresh(false);
  } catch (e) { toast(e.message, true); }
}

async function openFolder() {
  try {
    await api("/api/open_folder", { path: $("recDir").value.trim() });
  } catch (e) { toast(e.message, true); }
}

function clearLog() {
  $("log").textContent = "";
  lastLogTail = "";
}

refresh(false);
setInterval(() => refresh(false), 2000);
