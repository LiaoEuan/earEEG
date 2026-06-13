const channels = 16;
const micSampleRate = 16000;
const eegGain = 24;
const eegVoltsPerCount = 4.5 / eegGain / ((1 << 23) - 1);
const eegRanges = {
  uV: [
    ["auto", "Auto"],
    [50, "+/-50 uV"],
    [100, "+/-100 uV"],
    [250, "+/-250 uV"],
    [500, "+/-500 uV"],
    [1000, "+/-1000 uV"],
  ],
  mV: [
    ["auto", "Auto"],
    [0.05, "+/-0.05 mV"],
    [0.1, "+/-0.1 mV"],
    [0.25, "+/-0.25 mV"],
    [0.5, "+/-0.5 mV"],
    [1, "+/-1 mV"],
  ],
  V: [
    ["auto", "Auto"],
    [0.00005, "+/-0.00005 V"],
    [0.0001, "+/-0.0001 V"],
    [0.00025, "+/-0.00025 V"],
    [0.0005, "+/-0.0005 V"],
    [0.001, "+/-0.001 V"],
  ],
  counts: [
    ["auto", "Auto"],
    [50000, "+/-50k counts"],
    [250000, "+/-250k counts"],
    [1000000, "+/-1M counts"],
  ],
};
const colors = [
  "#5eead4", "#60a5fa", "#c084fc", "#f472b6",
  "#fb7185", "#fb923c", "#facc15", "#a3e635",
  "#4ade80", "#2dd4bf", "#22d3ee", "#818cf8",
  "#a78bfa", "#e879f9", "#f87171", "#fbbf24",
];
let latest = Array.from({ length: channels }, () => []);
let latestMic = [];
let paused = false;
let selectedAudioPath = "";
let selectedAudioName = "";
let micMonitorEnabled = false;
let micAudioContext = null;
let micPlayTime = 0;
const micMonitorLeadSeconds = 0.08;
let impedanceTimer = null;
let recordingTimer = null;
const canvas = document.getElementById("eegCanvas");
const micCanvas = document.getElementById("micCanvas");

function setBadge(id, text, ok) {
  const badge = document.getElementById(id);
  badge.textContent = text;
  badge.className = `badge ${ok ? "ok" : "warning"}`;
}

function updateRangeOptions() {
  const unit = document.getElementById("eegUnit").value;
  const range = document.getElementById("eegRange");
  const previous = range.value || "auto";
  range.innerHTML = "";
  for (const [value, label] of eegRanges[unit]) {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = label;
    range.appendChild(option);
  }
  range.value = eegRanges[unit].some(([value]) => String(value) === previous)
    ? previous
    : "auto";
}

function convertEegSample(raw, unit) {
  if (unit === "counts") return raw;
  const volts = raw * eegVoltsPerCount;
  if (unit === "uV") return volts * 1e6;
  if (unit === "mV") return volts * 1e3;
  return volts;
}

function formatValue(value, unit) {
  if (unit === "counts") return `${Math.round(value)} counts`;
  if (Math.abs(value) >= 100) return `${value.toFixed(0)} ${unit}`;
  if (Math.abs(value) >= 10) return `${value.toFixed(1)} ${unit}`;
  return `${value.toFixed(2)} ${unit}`;
}

function setControls(proxy) {
  const connected = Boolean(proxy && proxy.connected);
  const acquiring = Boolean(proxy && proxy.acquiring);
  const audio = proxy && proxy.audio ? proxy.audio : {};
  const audioPlaying = Boolean(audio.playing);
  const audioPaused = Boolean(audio.paused);
  setBadge("proxyStatus", connected ? "Device connected" : "Device disconnected", connected);
  setBadge("acqStatus", acquiring ? "Acquisition running" : "Acquisition idle", acquiring);
  document.getElementById("startAcqButton").disabled = !connected || acquiring;
  document.getElementById("stopAcqButton").disabled = !connected || !acquiring;
  document.getElementById("playAudioButton").disabled = !connected || !selectedAudioPath || audioPlaying;
  document.getElementById("pauseAudioButton").disabled = !connected || !audioPlaying || audioPaused;
  document.getElementById("resumeAudioButton").disabled = !connected || !audioPlaying || !audioPaused;
  document.getElementById("stopAudioButton").disabled = !connected || !audioPlaying;

  const label = audio.fileName || selectedAudioName;
  if (audioPlaying) {
    setBadge("audioStatus", `${audioPaused ? "Paused" : "Playing"}: ${label}`, true);
  } else if (selectedAudioName) {
    setBadge("audioStatus", `Selected: ${selectedAudioName}`, true);
  } else {
    setBadge("audioStatus", "No audio selected", false);
  }
}

function setMicMonitorStatus() {
  setBadge("micMonitorStatus", micMonitorEnabled ? "MIC monitor on" : "MIC monitor off",
    micMonitorEnabled);
  document.getElementById("monitorMicButton").disabled = micMonitorEnabled;
  document.getElementById("stopMonitorMicButton").disabled = !micMonitorEnabled;
}

async function postControl(path) {
  const detail = document.getElementById("detail");
  try {
    const response = await fetch(path, { method: "POST" });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      detail.textContent = payload.error || `Control request failed: ${response.status}`;
      return;
    }
    detail.textContent = "Command sent";
    await refreshProxyStatus();
  } catch (error) {
    detail.textContent = `Control unavailable: ${error.message}`;
  }
}

async function postJson(path, body) {
  const detail = document.getElementById("detail");
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      detail.textContent = payload.error || `Control request failed: ${response.status}`;
      return payload;
    }
    await refreshProxyStatus();
    return payload;
  } catch (error) {
    detail.textContent = `Control unavailable: ${error.message}`;
    return { ok: false, error: error.message };
  }
}

async function uploadAudio(file) {
  const detail = document.getElementById("detail");
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".wav")) {
    detail.textContent = "Only WAV files are supported";
    return;
  }
  detail.textContent = `Uploading ${file.name}...`;
  try {
    const response = await fetch("/api/audio/upload", {
      method: "POST",
      headers: { "X-File-Name": file.name },
      body: file,
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      detail.textContent = payload.error || `Upload failed: ${response.status}`;
      return;
    }
    selectedAudioPath = payload.path;
    selectedAudioName = payload.fileName || file.name;
    detail.textContent = `Audio selected: ${selectedAudioName}`;
    await refreshProxyStatus();
  } catch (error) {
    detail.textContent = `Upload failed: ${error.message}`;
  }
}

async function refreshProxyStatus() {
  try {
    const response = await fetch("/api/proxy/status");
    const payload = await response.json();
    setControls(payload);
  } catch (_error) {
    setControls({ connected: false, acquiring: false });
  }
}

async function refreshImpedanceStatus() {
  try {
    const response = await fetch("/api/impedance/status");
    const contentType = response.headers.get("Content-Type") || "";
    if (!contentType.includes("application/json")) {
      throw new Error("viewer backend has no impedance API; restart eeg_viewer");
    }
    const status = await response.json();
    if (!response.ok) {
      throw new Error(status.error || `HTTP ${response.status}`);
    }
    renderImpedance(status);
  } catch (error) {
    setBadge("impedanceStatus", `Impedance unavailable: ${error.message}`, false);
  }
}

async function refreshRecordingStatus() {
  try {
    const response = await fetch("/api/recording/status");
    const status = await response.json();
    renderRecording(status);
  } catch (error) {
    setBadge("recordingStatus", `Recording unavailable: ${error.message}`, false);
  }
}

function renderRecording(status) {
  const running = Boolean(status && status.running);
  const elapsed = status && status.elapsedSeconds ? status.elapsedSeconds : 0;
  const eegSamples = status && status.eegSamples ? status.eegSamples : 0;
  const micSamples = status && status.micSamples ? status.micSamples : 0;
  const lastPath = status && status.lastPath ? status.lastPath : "";
  const lastError = status && status.lastError ? status.lastError : "";
  setBadge("recordingStatus",
    running ? `Recording ${elapsed.toFixed(1)}s` : (lastError || "Recording idle"),
    running && !lastError);
  document.getElementById("startRecordingButton").disabled = running;
  document.getElementById("stopRecordingButton").disabled = !running;
  document.getElementById("recordingTag").disabled = running;
  document.getElementById("recordingDetail").textContent = running
    ? `EEG ${eegSamples} samples, MIC ${micSamples} samples`
    : (lastPath ? `Saved: ${lastPath}` : "NPZ: eeg, mic, stimuli");
}

async function startRecording() {
  const tag = document.getElementById("recordingTag").value;
  const result = await postJson("/api/recording/start", { tag });
  if (result && result.ok !== false) {
    refreshRecordingStatus();
  }
}

async function stopRecording() {
  await postControl("/api/recording/stop");
  refreshRecordingStatus();
}

function renderImpedance(status) {
  const running = Boolean(status && status.running);
  const current = status && status.currentChannel ? status.currentChannel : 0;
  const results = status && Array.isArray(status.results) ? status.results : [];
  const lastError = status && status.lastError ? status.lastError : "";
  const resultByChannel = new Map(results.map(result => [result.channel, result]));
  setBadge("impedanceStatus",
    running ? `Measuring Ch${current}` : (lastError || "Impedance idle"),
    running && !lastError);
  document.getElementById("startImpedanceButton").disabled = running;
  document.getElementById("stopImpedanceButton").disabled = !running;

  const grid = document.getElementById("impedanceGrid");
  grid.innerHTML = "";
  for (let channel = 1; channel <= 16; channel += 1) {
    const result = resultByChannel.get(channel);
    const cell = document.createElement("div");
    const quality = result ? result.quality : (running && channel === current ? "measuring" : "");
    cell.className = `impedance-cell ${quality}`;
    const channelLabel = document.createElement("div");
    channelLabel.className = "channel";
    channelLabel.textContent = `CH${String(channel).padStart(2, "0")}`;
    const value = document.createElement("div");
    value.className = "value";
    if (result) {
      value.textContent = `${result.electrode_kohm.toFixed(1)} kOhm`;
      value.title = `total=${result.total_kohm.toFixed(1)} kOhm, tone=${result.rms_uv.toFixed(1)} uVrms`;
    } else if (running && channel === current) {
      value.textContent = "measuring...";
    } else {
      value.textContent = "--";
    }
    cell.appendChild(channelLabel);
    cell.appendChild(value);
    grid.appendChild(cell);
  }
}

async function startImpedanceMeasurement() {
  const channelsValue = document.getElementById("impedanceChannels").value;
  const result = await postJson("/api/impedance/start", {
    channels: channelsValue,
    duration: 3.0,
  });
  if (result && result.ok !== false) {
    refreshImpedanceStatus();
  }
}

async function stopImpedanceMeasurement() {
  await postControl("/api/impedance/stop");
  refreshImpedanceStatus();
}

async function startMicMonitor() {
  const detail = document.getElementById("detail");
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) {
    detail.textContent = "Web Audio API is not available in this browser";
    return;
  }
  if (!micAudioContext) {
    micAudioContext = new AudioContext({ sampleRate: micSampleRate });
  }
  try {
    await micAudioContext.resume();
  } catch (error) {
    detail.textContent = `MIC monitor failed: ${error.message}`;
    return;
  }
  micMonitorEnabled = true;
  micPlayTime = micAudioContext.currentTime + 0.08;
  setMicMonitorStatus();
}

function stopMicMonitor() {
  micMonitorEnabled = false;
  if (micAudioContext) {
    micPlayTime = micAudioContext.currentTime;
  }
  setMicMonitorStatus();
}

function queueMicAudio(samples, sampleRate) {
  if (!micMonitorEnabled || !micAudioContext || !samples.length) return;
  const rate = sampleRate || micSampleRate;
  const audioBuffer = micAudioContext.createBuffer(1, samples.length, rate);
  const channel = audioBuffer.getChannelData(0);
  for (let i = 0; i < samples.length; i += 1) {
    channel[i] = Math.max(-1, Math.min(1, samples[i] / 32768));
  }
  const source = micAudioContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(micAudioContext.destination);
  const now = micAudioContext.currentTime;
  if (micPlayTime < now + micMonitorLeadSeconds) {
    micPlayTime = now + micMonitorLeadSeconds;
  }
  source.start(micPlayTime);
  micPlayTime += samples.length / rate;
}

function draw() {
  const seconds = Number(document.getElementById("windowSeconds").value);
  const count = seconds * 250;
  const unit = document.getElementById("eegUnit").value;
  const scaleValue = document.getElementById("eegRange").value;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const pixelWidth = Math.max(1, Math.floor(rect.width * ratio));
  const pixelHeight = Math.max(1, Math.floor(rect.height * ratio));
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const width = rect.width;
  const height = rect.height;
  const labelWidth = 54;
  const valueWidth = 130;
  const plotLeft = labelWidth;
  const plotRight = width - valueWidth;
  const plotWidth = Math.max(1, plotRight - plotLeft);
  const rowHeight = height / channels;

  ctx.clearRect(0, 0, width, height);
  ctx.font = "12px monospace";
  ctx.lineWidth = 1;

  for (let second = 0; second <= seconds; second += 1) {
    const x = plotLeft + second * plotWidth / seconds;
    ctx.strokeStyle = second === 0 || second === seconds ? "#31505b" : "#1b343d";
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
    ctx.fillStyle = "#78919a";
    ctx.fillText(`${second}s`, x + 4, height - 6);
  }

  for (let channel = 0; channel < channels; channel += 1) {
    const baseline = (channel + 0.5) * rowHeight;
    const rawData = latest[channel].slice(-count);
    const data = rawData.map(sample => convertEegSample(sample, unit));
    ctx.strokeStyle = "#17343c";
    ctx.beginPath();
    ctx.moveTo(plotLeft, baseline);
    ctx.lineTo(plotRight, baseline);
    ctx.stroke();

    ctx.fillStyle = colors[channel];
    ctx.fillText(`CH${String(channel + 1).padStart(2, "0")}`, 10, baseline + 4);
    if (data.length < 2) {
      ctx.fillText("p-p --", plotRight + 10, baseline + 4);
      continue;
    }

    const mean = data.reduce((sum, sample) => sum + sample, 0) / data.length;
    const centered = data.map(sample => sample - mean);
    let peak = 1;
    let min = data[0];
    let max = data[0];
    for (let i = 0; i < data.length; i += 1) {
      const abs = Math.abs(centered[i]);
      if (abs > peak) peak = abs;
      if (data[i] < min) min = data[i];
      if (data[i] > max) max = data[i];
    }
    const scale = scaleValue === "auto" ? peak * 1.15 : Number(scaleValue);
    ctx.fillText(`p-p ${formatValue(max - min, unit)}`, plotRight + 10, baseline + 4);
    ctx.strokeStyle = colors[channel];
    ctx.lineWidth = 1;
    ctx.beginPath();
    centered.forEach((sample, index) => {
      const x = plotRight - (centered.length - 1 - index) * plotWidth / (count - 1);
      const y = baseline - sample * rowHeight * 0.42 / scale;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }
  requestAnimationFrame(draw);
}

function drawMic() {
  const seconds = Number(document.getElementById("windowSeconds").value);
  const count = seconds * micSampleRate;
  const data = latestMic.slice(-count);
  const rect = micCanvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const pixelWidth = Math.max(1, Math.floor(rect.width * ratio));
  const pixelHeight = Math.max(1, Math.floor(rect.height * ratio));
  if (micCanvas.width !== pixelWidth || micCanvas.height !== pixelHeight) {
    micCanvas.width = pixelWidth;
    micCanvas.height = pixelHeight;
  }

  const ctx = micCanvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const width = rect.width;
  const height = rect.height;
  const labelWidth = 54;
  const valueWidth = 120;
  const plotLeft = labelWidth;
  const plotRight = width - valueWidth;
  const plotWidth = Math.max(1, plotRight - plotLeft);
  const baseline = height / 2;

  ctx.clearRect(0, 0, width, height);
  ctx.font = "12px monospace";
  ctx.lineWidth = 1;

  for (let second = 0; second <= seconds; second += 1) {
    const x = plotLeft + second * plotWidth / seconds;
    ctx.strokeStyle = second === 0 || second === seconds ? "#31505b" : "#1b343d";
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }

  ctx.strokeStyle = "#17343c";
  ctx.beginPath();
  ctx.moveTo(plotLeft, baseline);
  ctx.lineTo(plotRight, baseline);
  ctx.stroke();
  ctx.fillStyle = "#22d3ee";
  ctx.fillText("MIC", 10, baseline + 4);

  if (data.length < 2) {
    ctx.fillText("p-p --", plotRight + 10, baseline + 4);
    requestAnimationFrame(drawMic);
    return;
  }

  let min = data[0];
  let max = data[0];
  for (const sample of data) {
    if (sample < min) min = sample;
    if (sample > max) max = sample;
  }
  const peak = Math.max(Math.abs(min), Math.abs(max), 1);
  const step = Math.max(1, Math.floor(data.length / plotWidth));
  ctx.fillText(`p-p ${Math.round(max - min)}`, plotRight + 10, baseline + 4);
  ctx.strokeStyle = "#22d3ee";
  ctx.beginPath();
  for (let i = 0; i < data.length; i += step) {
    const x = plotRight - (data.length - 1 - i) * plotWidth / (data.length - 1);
    const y = baseline - data[i] * height * 0.42 / peak;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  requestAnimationFrame(drawMic);
}

const bandKeys = ["delta", "theta", "alpha", "beta", "gamma"];

function updateFocus(focus) {
  if (!focus) return;
  const score = focus.score;
  const state = focus.state || "waiting";
  document.getElementById("focusScore").textContent =
    score != null ? String(score) : "--";
  const stateEl = document.getElementById("focusState");
  stateEl.textContent = state;
  stateEl.className = `focus-state ${state}`;
  document.getElementById("focusQuality").textContent =
    focus.quality != null ? `${(focus.quality * 100).toFixed(0)}%` : "--";

  // Reasons
  const reasonsEl = document.getElementById("focusReasons");
  reasonsEl.innerHTML = "";
  if (Array.isArray(focus.reasons)) {
    for (const reason of focus.reasons) {
      const tag = document.createElement("span");
      tag.className = "focus-reason-tag";
      tag.textContent = reason.replace(/_/g, " ");
      reasonsEl.appendChild(tag);
    }
  }

  // Band powers
  const bp = focus.bandPowers || {};
  let maxPower = 1;
  for (const key of bandKeys) {
    if (bp[key] != null && bp[key] > maxPower) maxPower = bp[key];
  }
  for (const key of bandKeys) {
    const val = bp[key];
    document.getElementById(`focusBand${key[0].toUpperCase()}${key.slice(1)}`).textContent =
      val != null ? val.toFixed(1) : "--";
    document.getElementById(`focusBar${key[0].toUpperCase()}${key.slice(1)}`).style.width =
      val != null ? `${(val / maxPower * 100).toFixed(0)}%` : "0%";
  }

  // Ratios
  document.getElementById("focusThetaBeta").textContent =
    focus.thetaBetaRatio != null ? focus.thetaBetaRatio.toFixed(2) : "--";
  document.getElementById("focusAlphaBeta").textContent =
    focus.alphaBetaRatio != null ? focus.alphaBetaRatio.toFixed(2) : "--";
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws`);
  setBadge("socketStatus", "WebSocket connecting", false);
  socket.onopen = () => setBadge("socketStatus", "WebSocket connected", true);
  socket.onclose = () => {
    setBadge("socketStatus", "WebSocket reconnecting", false);
    setTimeout(connect, 1000);
  };
  socket.onmessage = event => {
    const frame = JSON.parse(event.data);
    setControls(frame.proxy);
    setBadge("lslStatus", frame.lslConnected ? "LSL connected" : "LSL waiting",
      frame.lslConnected);
    const mic = frame.mic || {};
    setBadge("micStatus", mic.lslConnected ? "MIC connected" : "MIC waiting",
      mic.lslConnected);
    document.getElementById("sampleRate").textContent = frame.sampleRate;
    document.getElementById("sampleCount").textContent =
      frame.sampleCount.toLocaleString();
    document.getElementById("detail").textContent =
      frame.error || `${frame.channels} channels streaming`;
    document.getElementById("micDetail").textContent =
      mic.error || `${(mic.sampleCount || 0).toLocaleString()} MIC samples @ ${mic.sampleRate || micSampleRate} Hz`;
    if (!paused) {
      latest = latest.map((samples, index) =>
        samples.concat(frame.samples[index]).slice(-2500));
      if (Array.isArray(mic.samples)) {
        latestMic = latestMic.concat(mic.samples).slice(-micSampleRate * 10);
      }
    }
    if (Array.isArray(mic.samples)) {
      queueMicAudio(mic.samples, mic.sampleRate);
    }
    updateFocus(frame.focus);
  };
}

document.getElementById("pauseButton").onclick = event => {
  paused = !paused;
  event.target.textContent = paused ? "Resume" : "Pause";
};

document.getElementById("startAcqButton").onclick = () =>
  postControl("/api/acquisition/start");

document.getElementById("stopAcqButton").onclick = () =>
  postControl("/api/acquisition/stop");

document.getElementById("chooseAudioButton").onclick = () =>
  document.getElementById("audioFileInput").click();

document.getElementById("audioFileInput").onchange = event =>
  uploadAudio(event.target.files[0]);

document.getElementById("playAudioButton").onclick = () =>
  postJson("/api/audio/play", { path: selectedAudioPath });

document.getElementById("pauseAudioButton").onclick = () =>
  postControl("/api/audio/pause");

document.getElementById("resumeAudioButton").onclick = () =>
  postControl("/api/audio/resume");

document.getElementById("stopAudioButton").onclick = () =>
  postControl("/api/audio/stop");

document.getElementById("monitorMicButton").onclick = () => startMicMonitor();

document.getElementById("stopMonitorMicButton").onclick = () => stopMicMonitor();

document.getElementById("eegUnit").onchange = () => updateRangeOptions();

document.getElementById("startImpedanceButton").onclick = () =>
  startImpedanceMeasurement();

document.getElementById("stopImpedanceButton").onclick = () =>
  stopImpedanceMeasurement();

document.getElementById("startRecordingButton").onclick = () => startRecording();

document.getElementById("stopRecordingButton").onclick = () => stopRecording();

const dropZone = document.getElementById("audioDropZone");
dropZone.ondragover = event => {
  event.preventDefault();
  dropZone.classList.add("dragging");
};
dropZone.ondragleave = () => dropZone.classList.remove("dragging");
dropZone.ondrop = event => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
  uploadAudio(event.dataTransfer.files[0]);
};

const legacyAmplitude = document.getElementById("amplitudeMode");
if (legacyAmplitude) {
  legacyAmplitude.closest("label").style.display = "none";
}

setControls({ connected: false, acquiring: false });
setMicMonitorStatus();
updateRangeOptions();
renderImpedance({ running: false, results: [] });
renderRecording({ running: false });
setInterval(refreshProxyStatus, 1000);
impedanceTimer = setInterval(refreshImpedanceStatus, 1000);
recordingTimer = setInterval(refreshRecordingStatus, 1000);
connect();
draw();
drawMic();
