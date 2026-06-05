const channels = 16;
const micSampleRate = 16000;
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
const canvas = document.getElementById("eegCanvas");
const micCanvas = document.getElementById("micCanvas");

function setBadge(id, text, ok) {
  const badge = document.getElementById(id);
  badge.textContent = text;
  badge.className = `badge ${ok ? "ok" : "warning"}`;
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
  const scaleValue = document.getElementById("amplitudeMode").value;
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
  const valueWidth = 92;
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
    const data = latest[channel].slice(-count);
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
    const peak = Math.max(...centered.map(Math.abs), 1);
    const scale = scaleValue === "auto" ? peak * 1.15 : Number(scaleValue);
    const min = Math.min(...data);
    const max = Math.max(...data);
    ctx.fillText(`p-p ${Math.round(max - min)}`, plotRight + 10, baseline + 4);
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

setControls({ connected: false, acquiring: false });
setMicMonitorStatus();
setInterval(refreshProxyStatus, 1000);
connect();
draw();
drawMic();
