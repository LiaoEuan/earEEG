const channels = 16;
const colors = [
  "#5eead4", "#60a5fa", "#c084fc", "#f472b6",
  "#fb7185", "#fb923c", "#facc15", "#a3e635",
  "#4ade80", "#2dd4bf", "#22d3ee", "#818cf8",
  "#a78bfa", "#e879f9", "#f87171", "#fbbf24",
];
let latest = Array.from({ length: channels }, () => []);
let paused = false;
const canvas = document.getElementById("eegCanvas");

function setBadge(id, text, ok) {
  const badge = document.getElementById(id);
  badge.textContent = text;
  badge.className = `badge ${ok ? "ok" : "warning"}`;
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
    setBadge("lslStatus", frame.lslConnected ? "LSL connected" : "LSL waiting",
      frame.lslConnected);
    document.getElementById("sampleRate").textContent = frame.sampleRate;
    document.getElementById("sampleCount").textContent =
      frame.sampleCount.toLocaleString();
    document.getElementById("detail").textContent =
      frame.error || `${frame.channels} channels streaming`;
    if (!paused) {
      latest = latest.map((samples, index) =>
        samples.concat(frame.samples[index]).slice(-2500));
    }
  };
}

document.getElementById("pauseButton").onclick = event => {
  paused = !paused;
  event.target.textContent = paused ? "Resume" : "Pause";
};

connect();
draw();
