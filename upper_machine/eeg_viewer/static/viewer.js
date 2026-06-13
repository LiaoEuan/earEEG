/* earEEG Acquisition Console – viewer.js */

const CHANNELS = 16;
const MIC_SAMPLE_RATE = 16000;
const EEG_GAIN = 24;
const EEG_VOLTS_PER_COUNT = 4.5 / EEG_GAIN / ((1 << 23) - 1);
const DRAW_INTERVAL_MS = 200; // 5 Hz max canvas refresh
const COLORS = [
  "#5eead4", "#60a5fa", "#c084fc", "#f472b6",
  "#fb7185", "#fb923c", "#facc15", "#a3e635",
  "#4ade80", "#2dd4bf", "#22d3ee", "#818cf8",
  "#a78bfa", "#e879f9", "#f87171", "#fbbf24",
];
const BAND_KEYS = ["delta", "theta", "alpha", "beta", "gamma"];

/* ===== State ===== */
let latest = Array.from({ length: CHANNELS }, () => []);
let latestMic = [];
let paused = false;
let selectedAudioPath = "";
let selectedAudioName = "";
let micMonitorEnabled = false;
let micAudioContext = null;
let micPlayTime = 0;
const micMonitorLeadSeconds = 0.08;
let electrodeSelection = Array.from({ length: CHANNELS }, () => true);
let electrodeConfig = null; // loaded from JSON

/* Display state (frontend only, not sent to backend) */
const display = {
  timeScale: 5,       // seconds
  vertScale: 100,     // uV, or "auto"
  channels: "selected", // "selected" | "all"
};
const filter = {
  highPass: 1,
  lowPass: 45,
  notch: 50,
};

/* FPS tracking */
let frameCount = 0;
let lastFpsTime = performance.now();

/* ===== DOM refs ===== */
const eegCanvas = document.getElementById("eegCanvas");
const micCanvas = document.getElementById("micCanvas");

/* ===== Utility ===== */
function setBadge(id, text, ok) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = `badge ${ok ? "ok" : "warning"}`;
}

function convertEeg(raw) {
  return raw * EEG_VOLTS_PER_COUNT * 1e6; // -> uV
}

function fmtUv(v) {
  if (Math.abs(v) >= 100) return `${v.toFixed(0)} uV`;
  if (Math.abs(v) >= 10) return `${v.toFixed(1)} uV`;
  return `${v.toFixed(2)} uV`;
}

/* ===== API helpers ===== */
async function postControl(path) {
  try {
    const r = await fetch(path, { method: "POST" });
    const p = await r.json();
    if (!r.ok || p.ok === false) {
      document.getElementById("detail").textContent = p.error || `Failed: ${r.status}`;
      return;
    }
    document.getElementById("detail").textContent = "OK";
    await refreshProxyStatus();
  } catch (e) {
    document.getElementById("detail").textContent = `Error: ${e.message}`;
  }
}

async function postJson(path, body) {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const p = await r.json();
    if (!r.ok || p.ok === false) {
      document.getElementById("detail").textContent = p.error || `Failed: ${r.status}`;
      return p;
    }
    await refreshProxyStatus();
    return p;
  } catch (e) {
    document.getElementById("detail").textContent = `Error: ${e.message}`;
    return { ok: false, error: e.message };
  }
}

async function uploadAudio(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".wav")) {
    document.getElementById("detail").textContent = "Only WAV files are supported";
    return;
  }
  document.getElementById("detail").textContent = `Uploading ${file.name}...`;
  try {
    const r = await fetch("/api/audio/upload", {
      method: "POST",
      headers: { "X-File-Name": file.name },
      body: file,
    });
    const p = await r.json();
    if (!r.ok || p.ok === false) {
      document.getElementById("detail").textContent = p.error || `Upload failed: ${r.status}`;
      return;
    }
    selectedAudioPath = p.path;
    selectedAudioName = p.fileName || file.name;
    document.getElementById("detail").textContent = `Selected: ${selectedAudioName}`;
    await refreshProxyStatus();
  } catch (e) {
    document.getElementById("detail").textContent = `Upload error: ${e.message}`;
  }
}

/* ===== Status refresh ===== */
async function refreshProxyStatus() {
  try {
    const r = await fetch("/api/proxy/status");
    setControls(await r.json());
  } catch (_) {
    setControls({ connected: false, acquiring: false });
  }
}

function setControls(proxy) {
  const connected = Boolean(proxy && proxy.connected);
  const acquiring = Boolean(proxy && proxy.acquiring);
  const audio = proxy && proxy.audio ? proxy.audio : {};
  const playing = Boolean(audio.playing);
  const aPaused = Boolean(audio.paused);

  setBadge("proxyStatus", connected ? "connected" : "disconnected", connected);
  setBadge("acqStatus", acquiring ? "running" : "idle", acquiring);
  document.getElementById("startAcqButton").disabled = !connected || acquiring;
  document.getElementById("stopAcqButton").disabled = !connected || !acquiring;
  document.getElementById("playAudioButton").disabled = !connected || !selectedAudioPath || playing;
  document.getElementById("pauseAudioButton").disabled = !connected || !playing || aPaused;
  document.getElementById("resumeAudioButton").disabled = !connected || !playing || !aPaused;
  document.getElementById("stopAudioButton").disabled = !connected || !playing;

  const label = audio.fileName || selectedAudioName;
  if (playing) {
    setBadge("audioStatus", `${aPaused ? "Paused" : "Playing"}: ${label}`, true);
  } else if (selectedAudioName) {
    setBadge("audioStatus", `Selected: ${selectedAudioName}`, true);
  } else {
    setBadge("audioStatus", "No audio", false);
  }
}

function setMicMonitorStatus() {
  setBadge("micMonitorStatus", micMonitorEnabled ? "On" : "Off", micMonitorEnabled);
  document.getElementById("monitorMicButton").disabled = micMonitorEnabled;
  document.getElementById("stopMonitorMicButton").disabled = !micMonitorEnabled;
}

async function refreshImpedanceStatus() {
  try {
    const r = await fetch("/api/impedance/status");
    const ct = r.headers.get("Content-Type") || "";
    if (!ct.includes("application/json")) throw new Error("no impedance API");
    const s = await r.json();
    if (!r.ok) throw new Error(s.error || `HTTP ${r.status}`);
    renderImpedance(s);
  } catch (e) {
    setBadge("impedanceStatus", `Err: ${e.message}`, false);
  }
}

async function refreshRecordingStatus() {
  try {
    const r = await fetch("/api/recording/status");
    renderRecording(await r.json());
  } catch (e) {
    setBadge("recordingStatus", `Err: ${e.message}`, false);
  }
}

/* ===== Recording ===== */
function renderRecording(s) {
  const running = Boolean(s && s.running);
  const elapsed = s && s.elapsedSeconds ? s.elapsedSeconds : 0;
  const eeg = s && s.eegSamples ? s.eegSamples : 0;
  const mic = s && s.micSamples ? s.micSamples : 0;
  const lastPath = s && s.lastPath ? s.lastPath : "";
  const lastErr = s && s.lastError ? s.lastError : "";
  setBadge("recordingStatus",
    running ? `${elapsed.toFixed(1)}s` : (lastErr || "Idle"),
    running && !lastErr);
  document.getElementById("startRecordingButton").disabled = running;
  document.getElementById("stopRecordingButton").disabled = !running;
  document.getElementById("recordingDetail").textContent = running
    ? `EEG:${eeg} MIC:${mic}`
    : (lastPath ? lastPath : "");
}

async function startRecording() {
  const result = await postJson("/api/recording/start", { tag: "" });
  if (result && result.ok !== false) refreshRecordingStatus();
}

async function stopRecording() {
  await postControl("/api/recording/stop");
  refreshRecordingStatus();
}

/* ===== Impedance ===== */
function renderImpedance(s) {
  const running = Boolean(s && s.running);
  const current = s && s.currentChannel ? s.currentChannel : 0;
  const results = s && Array.isArray(s.results) ? s.results : [];
  const lastErr = s && s.lastError ? s.lastError : "";
  const byCh = new Map(results.map(r => [r.channel, r]));
  setBadge("impedanceStatus",
    running ? `Ch${current}` : (lastErr || "Idle"),
    running && !lastErr);
  document.getElementById("startImpedanceButton").disabled = running;
  document.getElementById("stopImpedanceButton").disabled = !running;

  const grid = document.getElementById("impedanceGrid");
  grid.innerHTML = "";
  for (let ch = 1; ch <= 16; ch++) {
    const result = byCh.get(ch);
    const cell = document.createElement("div");
    const q = result ? result.quality : (running && ch === current ? "measuring" : "");
    cell.className = `impedance-cell ${q}`;
    const lbl = document.createElement("div");
    lbl.className = "channel";
    lbl.textContent = `CH${String(ch).padStart(2, "0")}`;
    const val = document.createElement("div");
    val.className = "value";
    if (result) {
      val.textContent = `${result.electrode_kohm.toFixed(1)} kΩ`;
      val.title = `total=${result.total_kohm.toFixed(1)} kΩ, tone=${result.rms_uv.toFixed(1)} uVrms`;
    } else if (running && ch === current) {
      val.textContent = "...";
    } else {
      val.textContent = "--";
    }
    cell.appendChild(lbl);
    cell.appendChild(val);
    grid.appendChild(cell);
  }
}

async function startImpedanceMeasurement() {
  const ch = document.getElementById("impedanceChannels").value;
  const r = await postJson("/api/impedance/start", { channels: ch, duration: 3.0 });
  if (r && r.ok !== false) refreshImpedanceStatus();
}

async function stopImpedanceMeasurement() {
  await postControl("/api/impedance/stop");
  refreshImpedanceStatus();
}

/* ===== MIC Monitor ===== */
async function startMicMonitor() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) { document.getElementById("detail").textContent = "No Web Audio"; return; }
  if (!micAudioContext) micAudioContext = new AC({ sampleRate: MIC_SAMPLE_RATE });
  try { await micAudioContext.resume(); } catch (e) {
    document.getElementById("detail").textContent = `MIC err: ${e.message}`; return;
  }
  micMonitorEnabled = true;
  micPlayTime = micAudioContext.currentTime + 0.08;
  setMicMonitorStatus();
}

function stopMicMonitor() {
  micMonitorEnabled = false;
  if (micAudioContext) micPlayTime = micAudioContext.currentTime;
  setMicMonitorStatus();
}

function queueMicAudio(samples, sampleRate) {
  if (!micMonitorEnabled || !micAudioContext || !samples.length) return;
  const rate = sampleRate || MIC_SAMPLE_RATE;
  const buf = micAudioContext.createBuffer(1, samples.length, rate);
  const ch = buf.getChannelData(0);
  for (let i = 0; i < samples.length; i++) ch[i] = Math.max(-1, Math.min(1, samples[i] / 32768));
  const src = micAudioContext.createBufferSource();
  src.buffer = buf;
  src.connect(micAudioContext.destination);
  const now = micAudioContext.currentTime;
  if (micPlayTime < now + micMonitorLeadSeconds) micPlayTime = now + micMonitorLeadSeconds;
  src.start(micPlayTime);
  micPlayTime += samples.length / rate;
}

/* ===== Focus ===== */
function updateFocus(focus) {
  if (!focus) return;
  const score = focus.score;
  const state = focus.state || "waiting";
  document.getElementById("focusScore").textContent = score != null ? String(score) : "--";
  const stateEl = document.getElementById("focusState");
  stateEl.textContent = state;
  stateEl.className = `focus-state ${state}`;
  document.getElementById("focusQuality").textContent =
    focus.quality != null ? `Q:${(focus.quality * 100).toFixed(0)}%` : "Q:--";

  const bp = focus.bandPowers || {};
  let maxP = 1;
  for (const k of BAND_KEYS) { if (bp[k] != null && bp[k] > maxP) maxP = bp[k]; }
  for (const k of BAND_KEYS) {
    const v = bp[k];
    const cap = k[0].toUpperCase() + k.slice(1);
    document.getElementById(`focusBand${cap}`).textContent = v != null ? v.toFixed(1) : "--";
    document.getElementById(`focusBar${cap}`).style.width =
      v != null ? `${(v / maxP * 100).toFixed(0)}%` : "0%";
  }
  document.getElementById("focusThetaBeta").textContent =
    focus.thetaBetaRatio != null ? focus.thetaBetaRatio.toFixed(2) : "--";
  document.getElementById("focusAlphaBeta").textContent =
    focus.alphaBetaRatio != null ? focus.alphaBetaRatio.toFixed(2) : "--";
}

/* ===== WebSocket ===== */
function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws`);
  setBadge("lslStatus", "connecting", false);
  socket.onopen = () => setBadge("lslStatus", "connected", true);
  socket.onclose = () => {
    setBadge("lslStatus", "reconnecting", false);
    setTimeout(connect, 1000);
  };
  socket.onmessage = event => {
    frameCount++;
    const frame = JSON.parse(event.data);
    setControls(frame.proxy);
    setBadge("lslStatus", frame.lslConnected ? "connected" : "waiting", frame.lslConnected);
    const mic = frame.mic || {};
    document.getElementById("eegInfo").textContent =
      `${frame.channels} ch ${frame.sampleRate} Hz`;
    document.getElementById("micInfo").textContent =
      `${mic.sampleRate || MIC_SAMPLE_RATE} Hz`;
    document.getElementById("detail").textContent =
      frame.error || `${frame.channels}ch streaming`;
    if (!paused) {
      latest = latest.map((s, i) => s.concat(frame.samples[i] || []).slice(-2500));
      if (Array.isArray(mic.samples)) {
        latestMic = latestMic.concat(mic.samples).slice(-MIC_SAMPLE_RATE * 3);
      }
    }
    if (Array.isArray(mic.samples)) queueMicAudio(mic.samples, mic.sampleRate);
    updateFocus(frame.focus);
  };
}

/* ===== Canvas rendering (throttled) ===== */
function scheduleRedraw() {
  let lastDraw = 0;
  function loop(now) {
    if (now - lastDraw >= DRAW_INTERVAL_MS) {
      lastDraw = now;
      drawEEG();
      drawMic();
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
}

function fitCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const pw = Math.max(1, Math.floor(rect.width * dpr));
  const ph = Math.max(1, Math.floor(rect.height * dpr));
  if (canvas.width !== pw || canvas.height !== ph) {
    canvas.width = pw;
    canvas.height = ph;
  }
  return { ctx: canvas.getContext("2d"), dpr, w: rect.width, h: rect.height };
}

function drawEEG() {
  const { ctx, dpr, w, h } = fitCanvas(eegCanvas);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const seconds = display.timeScale;
  const count = seconds * 250;
  const scaleVal = display.vertScale; // number or "auto"
  const labelW = 40;
  const plotL = labelW;
  const plotR = w;
  const plotW = Math.max(1, plotR - plotL);

  /* Visible channels */
  const visCh = [];
  for (let i = 0; i < CHANNELS; i++) {
    if (display.channels === "all" || electrodeSelection[i]) visCh.push(i);
  }
  const nCh = visCh.length || 1;
  const rowH = h / nCh;

  ctx.clearRect(0, 0, w, h);
  ctx.font = "10px Consolas, monospace";
  ctx.lineWidth = 1;

  /* Grid: vertical (time) */
  for (let s = 0; s <= seconds; s++) {
    const x = plotL + s * plotW / seconds;
    ctx.strokeStyle = s === 0 || s === seconds ? "#2a4a54" : "#172a30";
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    if (s < seconds) {
      ctx.fillStyle = "#4a6a74";
      ctx.fillText(`${s}s`, x + 3, h - 4);
    }
  }

  /* Each channel */
  for (let ri = 0; ri < visCh.length; ri++) {
    const ch = visCh[ri];
    const baseline = (ri + 0.5) * rowH;
    const rawData = latest[ch].slice(-count);
    /* Downsample for performance */
    const step = Math.max(1, Math.floor(rawData.length / plotW));
    const data = [];
    for (let i = 0; i < rawData.length; i += step) data.push(convertEeg(rawData[i]));

    /* Baseline */
    ctx.strokeStyle = "#1a2e34";
    ctx.beginPath(); ctx.moveTo(plotL, baseline); ctx.lineTo(plotR, baseline); ctx.stroke();

    /* Label */
    ctx.fillStyle = COLORS[ch];
    ctx.fillText(`${ch + 1}`, 8, baseline + 3);

    if (data.length < 2) continue;

    /* Stats */
    const mean = data.reduce((a, b) => a + b, 0) / data.length;
    const centered = data.map(v => v - mean);
    let peak = 1, min = data[0], max = data[0];
    for (let i = 0; i < data.length; i++) {
      const abs = Math.abs(centered[i]);
      if (abs > peak) peak = abs;
      if (data[i] < min) min = data[i];
      if (data[i] > max) max = data[i];
    }
    const scale = scaleVal === "auto" ? peak * 1.15 : Number(scaleVal);

    /* Trace */
    ctx.strokeStyle = COLORS[ch];
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < centered.length; i++) {
      const x = plotR - (centered.length - 1 - i) * plotW / Math.max(1, centered.length - 1);
      const y = baseline - centered[i] * rowH * 0.42 / scale;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  /* Scale bar (bottom-left) */
  if (scaleVal !== "auto") {
    const sv = Number(scaleVal);
    const barH = rowH * 0.42; // half-channel amplitude
    ctx.strokeStyle = "#4a6a74";
    ctx.fillStyle = "#4a6a74";
    ctx.lineWidth = 1;
    const bx = plotL + 6;
    const by = h - 22;
    ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx, by - barH); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(bx - 3, by); ctx.lineTo(bx + 3, by); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(bx - 3, by - barH); ctx.lineTo(bx + 3, by - barH); ctx.stroke();
    ctx.font = "9px Consolas, monospace";
    ctx.fillText(`${fmtUv(sv)}/Div`, bx + 6, by - barH / 2 + 3);
    ctx.fillText(`${seconds}s/page`, bx + 6, by + 10);
  }
}

function drawMic() {
  const { ctx, dpr, w, h } = fitCanvas(micCanvas);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const seconds = display.timeScale;
  const count = seconds * MIC_SAMPLE_RATE;
  const data = latestMic.slice(-count);
  const labelW = 40;
  const plotL = labelW;
  const plotR = w;
  const plotW = Math.max(1, plotR - plotL);
  const baseline = h / 2;

  ctx.clearRect(0, 0, w, h);
  ctx.font = "10px Consolas, monospace";
  ctx.lineWidth = 1;

  /* Grid */
  for (let s = 0; s <= seconds; s++) {
    const x = plotL + s * plotW / seconds;
    ctx.strokeStyle = s === 0 || s === seconds ? "#2a4a54" : "#172a30";
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  ctx.strokeStyle = "#1a2e34";
  ctx.beginPath(); ctx.moveTo(plotL, baseline); ctx.lineTo(plotR, baseline); ctx.stroke();
  ctx.fillStyle = "#22d3ee";
  ctx.fillText("MIC", 8, baseline + 3);

  if (data.length < 2) return;

  let min = data[0], max = data[0];
  for (const s of data) { if (s < min) min = s; if (s > max) max = s; }
  const peak = Math.max(Math.abs(min), Math.abs(max), 1);
  const step = Math.max(1, Math.floor(data.length / plotW));

  ctx.strokeStyle = "#22d3ee";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i < data.length; i += step) {
    const x = plotR - (data.length - 1 - i) * plotW / Math.max(1, data.length - 1);
    const y = baseline - data[i] * h * 0.42 / peak;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

/* ===== FPS counter ===== */
function updateFps() {
  const now = performance.now();
  const elapsed = now - lastFpsTime;
  if (elapsed >= 1000) {
    const fps = (frameCount / elapsed * 1000).toFixed(0);
    setBadge("fpsDisplay", `FPS ${fps}`, true);
    frameCount = 0;
    lastFpsTime = now;
  }
  requestAnimationFrame(updateFps);
}

/* ===== Section toggles ===== */
function setupToggles() {
  document.querySelectorAll(".rp-header[data-toggle]").forEach(header => {
    const targetId = header.dataset.toggle;
    const body = document.getElementById(targetId);
    if (!body) return;
    header.addEventListener("click", () => {
      const hidden = body.classList.toggle("hidden");
      header.classList.toggle("collapsed", hidden);
    });
  });
}

/* ===== Electrode config ===== */
async function loadElectrodeConfig() {
  try {
    const resp = await fetch("/electrode_config.json");
    if (!resp.ok) return;
    electrodeConfig = await resp.json();
    // Apply config to electrodeSelection
    if (electrodeConfig.channels) {
      for (let i = 0; i < Math.min(electrodeConfig.channels.length, CHANNELS); i++) {
        electrodeSelection[i] = !!electrodeConfig.channels[i].enabled;
      }
    }
    console.log("[electrode] loaded config:", electrodeConfig.name);
  } catch (e) {
    console.log("[electrode] no config file, using defaults");
  }
}

/* ===== Electrode modal ===== */
function setupElectrodeModal() {
  const modal = document.getElementById("electrodeModal");
  const grid = document.getElementById("electrodeGrid");
  grid.innerHTML = "";
  for (let i = 0; i < CHANNELS; i++) {
    const item = document.createElement("div");
    item.className = "electrode-item";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = `elec_${i}`;
    cb.checked = electrodeSelection[i];
    const lbl = document.createElement("label");
    lbl.htmlFor = `elec_${i}`;
    // Show channel name from config if available
    const chName = electrodeConfig?.channels?.[i]?.name || `CH${String(i + 1).padStart(2, "0")}`;
    lbl.textContent = chName;
    item.appendChild(cb);
    item.appendChild(lbl);
    grid.appendChild(item);
  }
  document.getElementById("electrodeSetupBtn").onclick = () => { modal.style.display = "flex"; };
  document.getElementById("electrodeModalClose").onclick = () => { modal.style.display = "none"; };
  document.getElementById("electrodeSelectAll").onclick = () => {
    for (let i = 0; i < CHANNELS; i++) document.getElementById(`elec_${i}`).checked = true;
  };
  document.getElementById("electrodeSelectNone").onclick = () => {
    for (let i = 0; i < CHANNELS; i++) document.getElementById(`elec_${i}`).checked = false;
  };
  document.getElementById("electrodeModalOk").onclick = () => {
    for (let i = 0; i < CHANNELS; i++) {
      electrodeSelection[i] = document.getElementById(`elec_${i}`).checked;
    }
    modal.style.display = "none";
  };
  // Import config file
  document.getElementById("electrodeImportBtn").onclick = () => {
    document.getElementById("electrodeFileInput").click();
  };
  document.getElementById("electrodeFileInput").onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const config = JSON.parse(text);
      if (config.channels && config.channels.length > 0) {
        electrodeConfig = config;
        for (let i = 0; i < Math.min(config.channels.length, CHANNELS); i++) {
          electrodeSelection[i] = !!config.channels[i].enabled;
        }
        // Refresh modal checkboxes and labels
        for (let i = 0; i < CHANNELS; i++) {
          const cb = document.getElementById(`elec_${i}`);
          const lbl = document.querySelector(`label[for="elec_${i}"]`);
          if (cb) cb.checked = electrodeSelection[i];
          if (lbl) lbl.textContent = config.channels[i]?.name || `CH${String(i + 1).padStart(2, "0")}`;
        }
        console.log("[electrode] imported config:", config.name);
      }
    } catch (err) {
      console.error("[electrode] failed to import config:", err);
    }
    e.target.value = ""; // reset file input
  };
  modal.addEventListener("click", e => { if (e.target === modal) modal.style.display = "none"; });
}

/* ===== Impedance modal ===== */
function setupImpedanceModal() {
  const modal = document.getElementById("impedanceModal");
  document.getElementById("impedanceViewBtn").onclick = () => { modal.style.display = "flex"; refreshImpedanceStatus(); };
  document.getElementById("impedanceModalClose").onclick = () => { modal.style.display = "none"; };
  modal.addEventListener("click", e => { if (e.target === modal) modal.style.display = "none"; });
}

/* ===== Event bindings ===== */
function setupEvents() {
  /* Device */
  document.getElementById("startAcqButton").onclick = () => postControl("/api/acquisition/start");
  document.getElementById("stopAcqButton").onclick = () => postControl("/api/acquisition/stop");

  /* Audio */
  document.getElementById("chooseAudioButton").onclick = () =>
    document.getElementById("audioFileInput").click();
  document.getElementById("audioFileInput").onchange = e => uploadAudio(e.target.files[0]);
  document.getElementById("playAudioButton").onclick = () =>
    postJson("/api/audio/play", { path: selectedAudioPath });
  document.getElementById("pauseAudioButton").onclick = () => postControl("/api/audio/pause");
  document.getElementById("resumeAudioButton").onclick = () => postControl("/api/audio/resume");
  document.getElementById("stopAudioButton").onclick = () => postControl("/api/audio/stop");

  /* MIC monitor */
  document.getElementById("monitorMicButton").onclick = () => startMicMonitor();
  document.getElementById("stopMonitorMicButton").onclick = () => stopMicMonitor();

  /* Recording */
  document.getElementById("startRecordingButton").onclick = () => startRecording();
  document.getElementById("stopRecordingButton").onclick = () => stopRecording();

  /* Impedance */
  document.getElementById("startImpedanceButton").onclick = () => startImpedanceMeasurement();
  document.getElementById("stopImpedanceButton").onclick = () => stopImpedanceMeasurement();

  /* Display */
  document.getElementById("displayTimeScale").onchange = e => {
    display.timeScale = Number(e.target.value);
  };
  document.getElementById("displayVertScale").onchange = e => {
    display.vertScale = e.target.value === "auto" ? "auto" : Number(e.target.value);
  };
  document.getElementById("displayChannels").onchange = e => {
    display.channels = e.target.value;
  };

  /* Filter (frontend state only) */
  document.getElementById("filterHighPass").onchange = e => { filter.highPass = Number(e.target.value); };
  document.getElementById("filterLowPass").onchange = e => { filter.lowPass = Number(e.target.value); };
  document.getElementById("filterNotch").onchange = e => { filter.notch = Number(e.target.value); };

  /* Drop zone */
  const dz = document.getElementById("audioDropZone");
  dz.ondragover = e => { e.preventDefault(); dz.classList.add("dragging"); };
  dz.ondragleave = () => dz.classList.remove("dragging");
  dz.ondrop = e => { e.preventDefault(); dz.classList.remove("dragging"); uploadAudio(e.dataTransfer.files[0]); };
}

/* ===== Init ===== */
async function init() {
  setControls({ connected: false, acquiring: false });
  setMicMonitorStatus();
  renderImpedance({ running: false, results: [] });
  renderRecording({ running: false });

  setupToggles();
  await loadElectrodeConfig();
  setupElectrodeModal();
  setupImpedanceModal();
  setupEvents();

  setInterval(refreshProxyStatus, 3000);
  setInterval(refreshImpedanceStatus, 3000);
  setInterval(refreshRecordingStatus, 3000);

  connect();
  scheduleRedraw();
  updateFps();
}

init();
