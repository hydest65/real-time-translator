(() => {
  const backend = document.getElementById("backendConnection");
  const stream = document.getElementById("streamConnection");
  const activity = document.getElementById("liveConnectionActivity");
  const retry = document.getElementById("retryConnectionCheck");
  let checking = false;
  let activeSocket = null;
  const intentionalStops = new WeakSet();
  const labels = { Connecting: "Connecting to captions", "Connecting cloud": "Connecting to cloud speech",
    Listening: "Listening to audio", Transcribing: "Recognizing speech", Translating: "Translating",
    "Loading models": "Loading local models", Recording: "Recording", Stopped: "Translation stopped" };
  function paint(element, state, text) { element.dataset.state = state; element.textContent = text; }
  async function check() {
    if (checking) return;
    checking = true;
    retry.disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    try {
      const response = await fetch("/api/health", { cache: "no-store", signal: controller.signal });
      const data = await response.json();
      if (!response.ok || data.ok !== true) throw new Error("unavailable");
      paint(backend, "online", "Server: Online");
    } catch {
      paint(backend, "error", "Server: Unreachable");
    } finally {
      clearTimeout(timeout);
      checking = false;
      retry.disabled = false;
    }
  }
  window.captionConnection = {
    watch(ws) {
      activeSocket = ws;
      paint(stream, "pending", "Captions: Connecting");
      ws.addEventListener("open", () => {
        if (activeSocket === ws) paint(stream, "online", "Captions: Connected");
      });
      ws.addEventListener("error", () => {
        if (activeSocket === ws) paint(stream, "error", "Captions: Connection error");
      });
      ws.addEventListener("close", () => {
        if (activeSocket !== ws) return;
        const stopped = intentionalStops.has(ws);
        paint(stream, stopped ? "idle" : "error", stopped ? "Captions: Stopped" : "Captions: Disconnected");
        activity.textContent = stopped ? "Translation stopped by user" : "Connection lost. Click Start to reconnect.";
        check();
      });
    },
    stop(ws) { if (ws) intentionalStops.add(ws); },
    status(status, detail) {
      // A close event must remain visible even if the legacy UI reports Stopped.
      if (status === "Stopped" && stream.dataset.state === "error") return;
      activity.textContent = status === "Error" ? `Translation error: ${detail || "Check service settings"}` : (labels[status] || status);
      activity.dataset.state = status === "Error" ? "error" : "idle";
    },
  };
  retry.addEventListener("click", check);
  window.addEventListener("online", check);
  window.addEventListener("offline", () => paint(backend, "error", "Network: Offline"));
  check();
  setInterval(check, 5000);
})();
