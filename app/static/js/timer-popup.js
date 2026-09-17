(function () {
  "use strict";

  let docPipWindow = null;
  let canvasEl = null;
  let videoEl = null;
  let renderIntervalId = null;

  function playWaterSound() {
    const pct = (window.FOCUS_STATE && window.FOCUS_STATE.volumeSystem !== undefined) ? window.FOCUS_STATE.volumeSystem : 100;
    const vol = Math.max(0, Math.min(1, pct / 100));
    const sound = new Audio("/static/sounds/mais_1_garrafa.mp3");
    sound.volume = vol;
    sound.play().catch((err) => console.warn("[som] mais_1_garrafa.mp3", err));
  }

  async function logWaterFromPopup() {
    playWaterSound();

    try {
      const res = await fetch("/api/water/log", { method: "POST" });
      const data = await res.json();

      const bottleFill = document.getElementById("bottle-fill");
      if (bottleFill) {
        bottleFill.style.height = `${Math.min(100, data.pct)}%`;
      }
      const waterValue = document.getElementById("water-value");
      if (waterValue) {
        waterValue.textContent = `${data.total_l}L / ${data.goal_l}L`;
      }

      try { localStorage.removeItem("foco_water_cycles_v1"); } catch (e) {}
    } catch (err) {
      console.error("Erro ao registrar água via pop-up:", err);
    }
  }

  function getTimerInfo() {
    let state = null;
    try {
      const raw = localStorage.getItem("foco_timer_state_v1");
      if (raw) state = JSON.parse(raw);
    } catch (e) {}

    const cfg = window.FOCUS_STATE || {};
    const defaultFocusSec = (cfg.focusMinutes || 25) * 60;
    const defaultShortBreakSec = (cfg.shortBreakMinutes || 5) * 60;
    const defaultLongBreakSec = (cfg.longBreakMinutes || 15) * 60;

    let status = state ? state.status : "idle";
    let remainingSeconds = state && typeof state.remainingSeconds === "number" ? state.remainingSeconds : defaultFocusSec;
    let endTime = state ? state.endTime : null;

    if ((status === "focusing" || status === "resting") && endTime) {
      remainingSeconds = Math.max(0, Math.round((endTime - Date.now()) / 1000));
    }

    let totalSeconds = defaultFocusSec;
    let label = "IDLE";
    let statusClass = "idle";

    if (status === "focusing" || status === "paused") {
      label = status === "paused" ? "PAUSADO" : "FOCO";
      statusClass = "focus";
      totalSeconds = defaultFocusSec;
    } else if (status === "resting") {
      label = state && state.restKind === "long" ? "PAUSA LONGA" : "PAUSA";
      statusClass = "rest";
      totalSeconds = state && state.restKind === "long" ? defaultLongBreakSec : defaultShortBreakSec;
    } else if (status === "finished") {
      label = "CONCLUÍDO";
      statusClass = "finished";
      totalSeconds = defaultFocusSec;
    }

    const elapsed = Math.max(0, totalSeconds - remainingSeconds);
    const pct = totalSeconds > 0 ? Math.min(100, Math.max(0, (elapsed / totalSeconds) * 100)) : 0;

    const m = Math.floor(remainingSeconds / 60);
    const s = remainingSeconds % 60;
    const displayStr = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;

    return {
      status,
      label,
      statusClass,
      displayStr,
      pct,
      remainingSeconds,
      totalSeconds
    };
  }

  function updateMediaSession(info) {
    if ("mediaSession" in navigator) {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: `${info.displayStr} · ${info.label}`,
        artist: "+1 Garrafa de Água",
        album: "Foco App"
      });
      try {
        navigator.mediaSession.setActionHandler("nexttrack", () => {
          logWaterFromPopup();
        });
      } catch (e) {}
    }
  }

  // --- Document Picture-in-Picture (Chromium 116+) ---
  function setupDocPipWindow(pip) {
    const doc = pip.document;
    const isDark = (document.documentElement.getAttribute("data-theme") || "dark") === "dark";

    const style = doc.createElement("style");
    style.textContent = `
      * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Poppins', -apple-system, sans-serif; }
      body {
        background: ${isDark ? "#14161a" : "#f5f3ee"};
        color: ${isDark ? "#ecebe6" : "#14161a"};
        height: 100vh;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 16px;
        user-select: none;
        overflow: hidden;
      }
      .pip-badge {
        font-size: 12px;
        font-weight: 700;
        padding: 4px 14px;
        border-radius: 12px;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        margin-bottom: 12px;
      }
      .pip-badge.focus { background: ${isDark ? "rgba(76, 158, 124, 0.25)" : "rgba(31, 92, 69, 0.15)"}; color: ${isDark ? "#4c9e7c" : "#1f5c45"}; }
      .pip-badge.rest { background: rgba(16, 185, 129, 0.25); color: #10b981; }
      .pip-badge.finished { background: rgba(217, 170, 85, 0.25); color: #d9aa55; }
      .pip-badge.idle { background: rgba(148, 163, 184, 0.15); color: #94a3b8; }

      .pip-timer {
        font-family: 'Lora', serif;
        font-size: 54px;
        font-weight: 600;
        line-height: 1;
        margin-bottom: 20px;
        color: ${isDark ? "#ecebe6" : "#14161a"};
      }

      .pip-bartrack {
        width: 100%;
        height: 22px;
        background: ${isDark ? "#22262B" : "#DCDAD4"};
        border: 2px solid ${isDark ? "#ECEBE6" : "#14161A"};
        box-shadow: 3px 3px 0 ${isDark ? "#0B0C0E" : "rgba(0,0,0,0.18)"};
        position: relative;
        overflow: hidden;
      }
      .pip-barfill {
        height: 100%;
        background-color: ${isDark ? "#4c9e7c" : "#1f5c45"};
        background-image: repeating-linear-gradient(
          90deg,
          transparent,
          transparent 14px,
          rgba(0,0,0,0.14) 14px,
          rgba(0,0,0,0.14) 16px
        );
        border-right: 2px solid ${isDark ? "#ECEBE6" : "#14161A"};
        transition: width 0.25s linear;
        width: 0%;
      }
    `;
    doc.head.appendChild(style);

    const fontLink = doc.createElement("link");
    fontLink.rel = "stylesheet";
    fontLink.href = "https://fonts.googleapis.com/css2?family=Lora:wght@600&family=Poppins:wght@600;700&display=swap";
    doc.head.appendChild(fontLink);

    doc.body.innerHTML = `
      <div class="pip-badge idle" id="pip-badge">IDLE</div>
      <div class="pip-timer" id="pip-timer">25:00</div>
      <div class="pip-bartrack">
        <div class="pip-barfill" id="pip-barfill"></div>
      </div>
    `;
  }

  function updateDocPip() {
    if (!docPipWindow || !docPipWindow.document) return;
    const doc = docPipWindow.document;
    const info = getTimerInfo();

    const badgeEl = doc.getElementById("pip-badge");
    if (badgeEl) {
      badgeEl.textContent = info.label;
      badgeEl.className = `pip-badge ${info.statusClass}`;
    }

    const timerEl = doc.getElementById("pip-timer");
    if (timerEl) {
      timerEl.textContent = info.displayStr;
    }

    const barfillEl = doc.getElementById("pip-barfill");
    if (barfillEl) {
      barfillEl.style.width = `${info.pct}%`;
      const isDark = (document.documentElement.getAttribute("data-theme") || "dark") === "dark";
      const fillColor = info.statusClass === "rest" ? (isDark ? "#4c9e7c" : "#1f5c45") :
                        info.statusClass === "finished" ? (isDark ? "#D9AA55" : "#9B7320") :
                        (isDark ? "#4c9e7c" : "#1f5c45");
      barfillEl.style.backgroundColor = fillColor;
    }

    updateMediaSession(info);
  }

  // --- Canvas Video PiP Fallback ---
  function initMediaElements() {
    if (!canvasEl) {
      canvasEl = document.createElement("canvas");
      canvasEl.id = "foco-pip-canvas";
      canvasEl.width = 320;
      canvasEl.height = 200;
      canvasEl.style.display = "none";
      document.body.appendChild(canvasEl);
    }

    if (!videoEl) {
      videoEl = document.createElement("video");
      videoEl.id = "foco-pip-video";
      videoEl.muted = true;
      videoEl.playsInline = true;
      videoEl.autoplay = true;
      videoEl.style.position = "fixed";
      videoEl.style.top = "-9999px";
      videoEl.style.left = "-9999px";
      videoEl.style.width = "1px";
      videoEl.style.height = "1px";
      videoEl.style.opacity = "0";
      videoEl.style.pointerEvents = "none";
      document.body.appendChild(videoEl);

      videoEl.addEventListener("leavepictureinpicture", () => {
        stopRenderLoop();
      });
    }
  }

  function drawTimerCanvas() {
    if (!canvasEl) return;
    const ctx = canvasEl.getContext("2d");
    const width = canvasEl.width;
    const height = canvasEl.height;
    const info = getTimerInfo();
    const isDark = (document.documentElement.getAttribute("data-theme") || "dark") === "dark";

    // Background
    ctx.fillStyle = isDark ? "#14161a" : "#f5f3ee";
    ctx.fillRect(0, 0, width, height);

    // Border / Outline
    ctx.strokeStyle = isDark ? "rgba(255, 255, 255, 0.08)" : "rgba(0, 0, 0, 0.08)";
    ctx.lineWidth = 2;
    ctx.strokeRect(0, 0, width, height);

    // Status Badge Colors
    let badgeBg = "rgba(148, 163, 184, 0.15)";
    let badgeFg = "#94a3b8";

    if (info.statusClass === "focus") {
      badgeBg = isDark ? "rgba(76, 158, 124, 0.25)" : "rgba(31, 92, 69, 0.15)";
      badgeFg = isDark ? "#4c9e7c" : "#1f5c45";
    } else if (info.statusClass === "rest") {
      badgeBg = "rgba(16, 185, 129, 0.25)";
      badgeFg = "#10b981";
    } else if (info.statusClass === "finished") {
      badgeBg = "rgba(217, 170, 85, 0.25)";
      badgeFg = "#d9aa55";
    }

    // Status Badge Pill
    ctx.font = "bold 12px 'Poppins', -apple-system, sans-serif";
    const textMetrics = ctx.measureText(info.label);
    const badgeWidth = textMetrics.width + 24;
    const badgeHeight = 24;
    const badgeX = (width - badgeWidth) / 2;
    const badgeY = 22;

    ctx.beginPath();
    ctx.roundRect(badgeX, badgeY, badgeWidth, badgeHeight, 12);
    ctx.fillStyle = badgeBg;
    ctx.fill();

    ctx.fillStyle = badgeFg;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(info.label, width / 2, badgeY + badgeHeight / 2 + 1);

    // Timer Display Number
    ctx.font = "600 54px 'Lora', serif";
    ctx.fillStyle = isDark ? "#ecebe6" : "#14161a";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(info.displayStr, width / 2, 102);

    // Progress Bar — identidade visual das barras ".bartrack / .barfill"
    const margin = 24;
    const trackY = 150;
    const trackWidth = width - margin * 2;
    const trackHeight = 22;
    const borderColor = isDark ? "#ECEBE6" : "#14161A";
    const trackBg = isDark ? "#22262B" : "#DCDAD4";
    const shadowColor = isDark ? "#0B0C0E" : "rgba(0,0,0,0.18)";
    const fillColor = info.statusClass === "rest" ? (isDark ? "#4c9e7c" : "#1f5c45") :
                      info.statusClass === "finished" ? (isDark ? "#D9AA55" : "#9B7320") :
                      (isDark ? "#4c9e7c" : "#1f5c45");

    // Shadow (simula box-shadow: 3px 3px 0 color)
    ctx.fillStyle = shadowColor;
    ctx.fillRect(margin + 3, trackY + 3, trackWidth, trackHeight);

    // Track background
    ctx.fillStyle = trackBg;
    ctx.fillRect(margin, trackY, trackWidth, trackHeight);

    // Fill
    const fillWidth = Math.max(0, Math.min(trackWidth - 2, ((trackWidth - 2) * info.pct) / 100));
    if (fillWidth > 0) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(margin + 1, trackY + 1, trackWidth - 2, trackHeight - 2);
      ctx.clip();

      ctx.fillStyle = fillColor;
      ctx.fillRect(margin + 1, trackY + 1, fillWidth, trackHeight - 2);

      const stripeSpacing = 16;
      const stripeWidth = 2;
      ctx.fillStyle = "rgba(0,0,0,0.14)";
      for (let x = margin + 1; x < margin + 1 + fillWidth; x += stripeSpacing) {
        ctx.fillRect(x + 14, trackY + 1, stripeWidth, trackHeight - 2);
      }

      ctx.fillStyle = borderColor;
      ctx.fillRect(margin + 1 + fillWidth - 2, trackY + 1, 2, trackHeight - 2);

      ctx.restore();
    }

    ctx.strokeStyle = borderColor;
    ctx.lineWidth = 2;
    ctx.strokeRect(margin, trackY, trackWidth, trackHeight);

    updateMediaSession(info);
  }

  function startRenderLoop() {
    if (renderIntervalId) clearInterval(renderIntervalId);
    if (docPipWindow) {
      updateDocPip();
      renderIntervalId = setInterval(updateDocPip, 250);
    } else {
      drawTimerCanvas();
      renderIntervalId = setInterval(drawTimerCanvas, 250);
    }
  }

  function stopRenderLoop() {
    if (renderIntervalId) {
      clearInterval(renderIntervalId);
      renderIntervalId = null;
    }
  }

  async function openTimerPopup() {
    // 1. Tentar Document Picture-in-Picture (Chromium: Chrome/Edge/Brave)
    if ("documentPictureInPicture" in window) {
      if (docPipWindow) {
        docPipWindow.close();
        docPipWindow = null;
        stopRenderLoop();
        return;
      }

      try {
        docPipWindow = await window.documentPictureInPicture.requestWindow({
          width: 320,
          height: 200
        });

        setupDocPipWindow(docPipWindow);

        docPipWindow.addEventListener("pagehide", () => {
          docPipWindow = null;
          stopRenderLoop();
        });

        startRenderLoop();
        return;
      } catch (err) {
        console.warn("[timer-popup] Document PiP não disponível, fallback para Video PiP:", err);
      }
    }

    // 2. Fallback: Video Picture-in-Picture
    initMediaElements();

    if (document.pictureInPictureElement) {
      try {
        await document.exitPictureInPicture();
      } catch (e) {}
      stopRenderLoop();
      return;
    }

    drawTimerCanvas();

    try {
      const stream = canvasEl.captureStream(30);
      videoEl.srcObject = stream;
      await videoEl.play();
      await videoEl.requestPictureInPicture();

      const info = getTimerInfo();
      updateMediaSession(info);

      startRenderLoop();
    } catch (err) {
      console.warn("[timer-popup] Falha ao iniciar Picture-in-Picture:", err);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const toggleBtn = document.getElementById("toggle-timer-popup");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", (e) => {
        e.preventDefault();
        openTimerPopup();
      });
    }
  });

  window.openTimerPopup = openTimerPopup;
})();
