(() => {
  const storageKey = "subtitleStudioCaptionOnly";
  const enter = document.getElementById("enterCaptionView");
  const exit = document.getElementById("exitCaptionView");
  const warning = document.getElementById("captionViewWarning");
  const states = ["backendConnection", "streamConnection", "liveConnectionActivity"]
    .map((id) => document.getElementById(id));

  function showConnectionWarning() {
    const error = states.find((element) => element?.dataset.state === "error");
    warning.hidden = !error;
    warning.textContent = error ? error.textContent : "";
  }

  function setView(compact, focus = true) {
    const positions = [...document.querySelectorAll(".subtitle-stream")].map((element) => ({
      element, top: element.scrollTop,
      following: element.scrollHeight - element.scrollTop - element.clientHeight < 40,
    }));
    document.body.classList.toggle("caption-only", compact);
    try { localStorage.setItem(storageKey, String(compact)); } catch { /* Session-only view. */ }
    // Keep the same caption elements and socket; switching never restarts translation.
    positions.forEach(({ element, top, following }) => {
      element.scrollTop = following ? element.scrollHeight : top;
    });
    showConnectionWarning();
    if (focus) (compact ? exit : enter).focus({ preventScroll: true });
  }

  enter.addEventListener("click", () => setView(true));
  exit.addEventListener("click", () => setView(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("caption-only")) setView(false);
  });
  const observer = new MutationObserver(showConnectionWarning);
  states.forEach((element) => {
    if (element) observer.observe(element, { attributes: true, childList: true, subtree: true, characterData: true });
  });
  let compact = false;
  try { compact = localStorage.getItem(storageKey) === "true"; } catch { /* Default to full view. */ }
  setView(compact, false);
})();
