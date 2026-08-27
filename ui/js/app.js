(() => {
  const $ = (id) => document.getElementById(id);
  const body = document.body;
  const orbBtn = $("orbBtn");
  const orbHint = $("orbHint");
  const stateChip = $("stateChip");
  const modelChip = $("modelChip");
  const youLine = $("youLine");
  const botLine = $("botLine");
  const toolLine = $("toolLine");
  const composer = $("composer");
  const textIn = $("textIn");
  const toast = $("toast");
  const clock = $("clock");

  let state = "idle";
  let ws;
  let recording = false;
  let recCtx = null;
  let recChunks = [];
  let recStream = null;
  let assistantBuf = "";

  function setState(next) {
    state = next || "idle";
    body.dataset.state = state;
    stateChip.textContent = state;
    const hints = {
      idle: "tap to talk",
      listening: "listening…",
      thinking: "thinking…",
      speaking: "speaking…",
      error: "something broke",
    };
    orbHint.textContent = hints[state] || state;
  }

  function showToast(msg) {
    if (!msg) return;
    toast.hidden = false;
    toast.textContent = msg;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => { toast.hidden = true; }, 4200);
  }

  function tickClock() {
    const now = new Date();
    clock.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  tickClock();
  setInterval(tickClock, 1000);

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      handleEvent(msg);
    };
    ws.onclose = () => setTimeout(connect, 1200);
    ws.onerror = () => { try { ws.close(); } catch {} };
  }

  function handleEvent(msg) {
    switch (msg.type) {
      case "hello":
        if (msg.model) modelChip.textContent = msg.model;
        if (msg.state) setState(msg.state);
        if (msg.dev_mode) orbHint.title = "DEV_MODE on — typed input always works";
        break;
      case "state":
        setState(msg.state);
        if (msg.state === "thinking") assistantBuf = "";
        break;
      case "transcript":
        youLine.hidden = false;
        youLine.textContent = "You: " + msg.text;
        break;
      case "assistant_delta":
        assistantBuf += msg.text || "";
        botLine.textContent = assistantBuf;
        break;
      case "assistant":
        botLine.textContent = msg.text || assistantBuf;
        break;
      case "tool":
        toolLine.hidden = false;
        toolLine.textContent = "tool · " + msg.name;
        break;
      case "open_url":
        if (msg.url) {
          toolLine.hidden = false;
          toolLine.textContent = "open · " + msg.url;
          window.open(msg.url, "_blank", "noopener");
        }
        break;
      case "timer":
        showToast("Reminder: " + (msg.message || "timer"));
        break;
      case "error":
        showToast(msg.message || "error");
        setState("error");
        botLine.textContent = msg.message || "Error";
        break;
      default:
        break;
    }
  }

  function sendChat(text) {
    const t = (text || "").trim();
    if (!t) return;
    youLine.hidden = false;
    youLine.textContent = "You: " + t;
    botLine.textContent = "";
    assistantBuf = "";
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "chat", text: t }));
    } else {
      fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: t }),
      }).then((r) => r.json()).then((j) => {
        botLine.textContent = j.reply || "";
      }).catch((e) => showToast(String(e)));
    }
  }

  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    const t = textIn.value;
    textIn.value = "";
    sendChat(t);
  });

  function encodeWav(float32, sampleRate) {
    const n = float32.length;
    const buf = new ArrayBuffer(44 + n * 2);
    const view = new DataView(buf);
    const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
    writeStr(0, "RIFF");
    view.setUint32(4, 36 + n * 2, true);
    writeStr(8, "WAVE");
    writeStr(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, "data");
    view.setUint32(40, n * 2, true);
    let off = 44;
    for (let i = 0; i < n; i++, off += 2) {
      let s = Math.max(-1, Math.min(1, float32[i]));
      view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  async function startRec() {
    if (recording || state === "thinking" || state === "speaking") return;
    recChunks = [];
    recStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
    recCtx = new AudioContext({ sampleRate: 16000 });
    const src = recCtx.createMediaStreamSource(recStream);
    const proc = recCtx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (ev) => {
      recChunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
    };
    src.connect(proc);
    proc.connect(recCtx.destination);
    recCtx._proc = proc;
    recCtx._src = src;
    recording = true;
    setState("listening");
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "listen_start" }));
  }

  async function stopRecAndSend() {
    if (!recording) return;
    recording = false;
    const ctx = recCtx;
    const stream = recStream;
    recCtx = null;
    recStream = null;
    try { ctx._src.disconnect(); ctx._proc.disconnect(); } catch {}
    try { await ctx.close(); } catch {}
    if (stream) stream.getTracks().forEach((t) => t.stop());

    const len = recChunks.reduce((n, a) => n + a.length, 0);
    const pcm = new Float32Array(len);
    let o = 0;
    for (const a of recChunks) { pcm.set(a, o); o += a.length; }
    recChunks = [];
    if (len < 1600) {
      setState("idle");
      showToast("Hold a little longer — I barely heard anything.");
      return;
    }
    const wav = encodeWav(pcm, ctx.sampleRate || 16000);
    const data = new FormData();
    data.append("file", wav, "speech.wav");
    setState("thinking");
    try {
      const res = await fetch("/api/transcribe", { method: "POST", body: data });
      const json = await res.json();
      if (json.error && !json.text) {
        showToast(json.error);
        setState("idle");
      }
      if (json.text) {
        youLine.hidden = false;
        youLine.textContent = "You: " + json.text;
      }
    } catch (err) {
      showToast(String(err));
      setState("idle");
    }
  }

  orbBtn.addEventListener("pointerdown", async (e) => {
    e.preventDefault();
    try { await startRec(); }
    catch (err) {
      showToast("Mic unavailable — type instead. " + err.message);
      textIn.focus();
    }
  });
  window.addEventListener("pointerup", () => { if (recording) stopRecAndSend(); });
  window.addEventListener("pointercancel", () => { if (recording) stopRecAndSend(); });

  orbBtn.addEventListener("click", () => {
    if (!navigator.mediaDevices) textIn.focus();
  });

  fetch("/api/status").then((r) => r.json()).then((s) => {
    if (s.model) modelChip.textContent = s.model;
    if (s.state) setState(s.state);
  }).catch(() => {});

  connect();
})();
