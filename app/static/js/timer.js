(function () {
  "use strict";

  const state = {
    status: "idle", // idle | focusing | paused | finished | break_offer | resting
    cycleId: null,
    restId: null,
    restKind: null, // 'short' | 'long'
    remainingSeconds: window.FOCUS_STATE.focusMinutes * 60,
    worker: null,
    endTime: null,
    sessionCycleCount: 0, // contagem local só para decidir pausa curta/longa (seção 27)
    modalOpen: false,
    pauseMessage: null,
    pauseLegend: "",
    pauseLegendState: 1,
    lastMessageId: null,
    pauseCardDismissed: false,
  };

  const STORAGE_KEY = "foco_timer_state_v1";
  const WATER_CYCLES_KEY = "foco_water_cycles_v1";

  // ── Contador Hídrico ────────────────────────────────────────────────────────
  // Rastreia ciclos de foco consecutivos sem registro de água.
  // Armazenado separadamente do estado do timer para sobreviver a reloads.
  function readWaterCycles() {
    try {
      const raw = localStorage.getItem(WATER_CYCLES_KEY);
      if (!raw) return { day: "", count: 0 };
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return { day: "", count: 0 };
      // Resetar automaticamente se o dia mudou
      const currentDay = getCurrentDay();
      if (parsed.day && currentDay && parsed.day !== currentDay) {
        localStorage.removeItem(WATER_CYCLES_KEY);
        return { day: currentDay, count: 0 };
      }
      return parsed;
    } catch { return { day: "", count: 0 }; }
  }

  function writeWaterCycles(count) {
    try {
      localStorage.setItem(WATER_CYCLES_KEY, JSON.stringify({ day: getCurrentDay(), count }));
    } catch { /* noop */ }
  }

  function incrementWaterCycles() {
    const wc = readWaterCycles();
    writeWaterCycles(wc.count + 1);
  }

  function resetWaterCycles() {
    try { localStorage.removeItem(WATER_CYCLES_KEY); } catch { /* noop */ }
  }

  function shouldShowWaterAlert() {
    const wc = readWaterCycles();
    return wc.count >= 3;
  }
  // ── fim Contador Hídrico ─────────────────────────────────────────────────────

  let intervalId = null;


  function getCurrentDay() {
    return (window.FOCUS_STATE && window.FOCUS_STATE.currentDay) || "";
  }

  function readStoredTimerState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      return parsed;
    } catch (err) {
      console.warn("[timer] estado salvo inválido:", err);
      return null;
    }
  }

  function clearStoredTimerState() {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (err) {
      console.warn("[timer] falha ao limpar estado salvo:", err);
    }
  }

  function persistTimerState() {
    try {
      if (state.status === "idle" && !state.modalOpen) {
        localStorage.removeItem(STORAGE_KEY);
        return;
      }
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          day: getCurrentDay(),
          status: state.status,
          cycleId: state.cycleId,
          restId: state.restId,
          restKind: state.restKind,
          remainingSeconds: Math.max(0, Math.round(state.remainingSeconds || 0)),
          endTime: state.endTime,
          sessionCycleCount: state.sessionCycleCount,
          modalOpen: !!state.modalOpen,
          pauseMessage: state.pauseMessage,
          pauseLegend: state.pauseLegend,
          pauseLegendState: state.pauseLegendState,
          lastMessageId: state.lastMessageId,
          pauseCardDismissed: !!state.pauseCardDismissed,
          savedAt: Date.now(),
        })
      );
    } catch (err) {
      console.warn("[timer] falha ao persistir estado:", err);
    }
  }

  function restoreTimerState() {
    const saved = readStoredTimerState();
    if (!saved) return false;

    const currentDay = getCurrentDay();
    if (saved.day && currentDay && saved.day !== currentDay) {
      clearStoredTimerState();
      return false;
    }

    state.status = saved.status || "idle";
    state.cycleId = saved.cycleId ?? null;
    state.restId = saved.restId ?? null;
    state.restKind = saved.restKind ?? null;
    state.remainingSeconds = Number.isFinite(saved.remainingSeconds)
      ? Math.max(0, saved.remainingSeconds)
      : window.FOCUS_STATE.focusMinutes * 60;
    state.endTime = typeof saved.endTime === "number" ? saved.endTime : null;
    state.sessionCycleCount = Number.isFinite(saved.sessionCycleCount)
      ? saved.sessionCycleCount
      : 0;
    state.modalOpen = !!saved.modalOpen;
    state.pauseMessage = saved.pauseMessage ?? null;
    state.pauseLegend = saved.pauseLegend ?? "";
    state.pauseLegendState = saved.pauseLegendState ?? 1;
    state.lastMessageId = saved.lastMessageId ?? null;
    state.pauseCardDismissed = !!saved.pauseCardDismissed;

    if (state.status === "focusing" || state.status === "resting") {
      if (state.endTime) {
        state.remainingSeconds = Math.max(0, Math.round((state.endTime - Date.now()) / 1000));
      }
      if (state.remainingSeconds <= 0) {
        state.remainingSeconds = 0;
        state.endTime = null;
        if (state.status === "focusing") {
          state.status = "finished";
          state.modalOpen = true;
        } else {
          state.status = "idle";
          state.modalOpen = false;
          clearStoredTimerState();
          return false;
        }
      } else {
        state.endTime = Date.now() + state.remainingSeconds * 1000;
      }
    } else if (state.status === "finished") {
      state.modalOpen = true;
      state.endTime = null;
    } else if (state.status === "break_offer") {
      state.endTime = null;
      state.modalOpen = false;
    } else if (state.status === "paused") {
      state.endTime = null;
      state.modalOpen = false;
    } else {
      clearStoredTimerState();
      return false;
    }

    if (state.status === "focusing" || state.status === "resting") {
      startTicker();
    }

    return true;
  }


  function getWorker() {
    if (!state.worker) {
      const workerCode = `
        let intervalId = null;
        self.onmessage = function(e) {
          if (e.data === 'start') {
            if (intervalId) clearInterval(intervalId);
            intervalId = setInterval(() => {
              self.postMessage('tick');
            }, 1000);
          } else if (e.data === 'stop') {
            if (intervalId) {
              clearInterval(intervalId);
              intervalId = null;
            }
          }
        };
      `;
      try {
        const blob = new Blob([workerCode], { type: "application/javascript" });
        state.worker = new Worker(URL.createObjectURL(blob));
        state.worker.onmessage = function() {
          tick();
        };
      } catch (err) {
        console.error("FALHA ao criar Web Worker:", err);
      }
    }
    return state.worker;
  }

  function startTicker() {
    const worker = getWorker();
    if (worker) {
      worker.postMessage("start");
    } else {
      if (intervalId) clearInterval(intervalId);
      intervalId = setInterval(tick, 1000);
    }
  }

  function stopTicker() {
    const worker = getWorker();
    if (worker) {
      worker.postMessage("stop");
    }
    if (intervalId) {
      clearInterval(intervalId);
      intervalId = null;
    }
  }

  const el = {
    stateLabel: document.getElementById("timer-state"),
    display: document.getElementById("timer-display"),
    actions: document.getElementById("timer-actions"),
    postCycleMsg: document.getElementById("post-cycle-msg"),
    errorMsg: document.getElementById("timer-error"),
    modal: document.getElementById("post-cycle-modal"),
    titleInput: document.getElementById("cycle-title"),
    concludeBtn: document.getElementById("btn-conclude"),
    extraBlock: document.getElementById("extra-block"),
    extraHint: document.getElementById("extra-hint"),
    extraFill: document.getElementById("extra-fill"),
    pauseCard: document.getElementById("pause-card"),
    pauseMessage: document.getElementById("pause-message"),
    pauseLegend: document.getElementById("pause-legend"),
    pauseConcludeBtn: document.getElementById("btn-conclude-pause"),
  };

  // ---- Animação de Pausa (GIF nativo) --------------------------------
  // O navegador anima o GIF automaticamente — sem intervalo JS.
  // Cache-buster (?t=timestamp) garante reinício ao trocar de mensagem.

  function adjustGifUrlForTheme(gifUrl) {
    if (!gifUrl) return gifUrl;
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    if (isDark) {
      const match = gifUrl.match(/^(.*)(\.[a-zA-Z0-9]+)$/);
      if (match) {
        const name = match[1];
        const ext = match[2];
        if (!name.endsWith("1")) {
          return name + "1" + ext;
        }
      }
    } else {
      const match = gifUrl.match(/^(.*)1(\.[a-zA-Z0-9]+)$/);
      if (match) {
        return match[1] + match[2];
      }
    }
    return gifUrl;
  }

  function setGif(gifUrl) {
    const imgEl = document.getElementById("pause-animation");
    if (!imgEl || !gifUrl) return;
    const adjustedUrl = adjustGifUrlForTheme(gifUrl);
    if (imgEl.getAttribute("data-last-url") === adjustedUrl) {
      return;
    }
    imgEl.setAttribute("data-last-url", adjustedUrl);
    imgEl.src = adjustedUrl + "?t=" + Date.now();
  }

  function clearGif() {
    const imgEl = document.getElementById("pause-animation");
    if (imgEl) {
      imgEl.src = "";
      imgEl.removeAttribute("data-last-url");
    }
  }

  // ---- Áudio -------------------------------------------------------
  // ---- Áudio & SOM ENGINE ---------------------------------------------------
  let _audioCtx = null;
  const _audioBuffers = {};

  function _getCtx() {
    if (!_audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (AudioContextClass) {
        _audioCtx = new AudioContextClass();
      }
    }
    if (_audioCtx && _audioCtx.state === "suspended") {
      _audioCtx.resume().catch(() => {});
    }
    return _audioCtx;
  }

  function _unlockAudioEngine() {
    const ctx = _getCtx();
    if (ctx) {
      if (ctx.state === "suspended") {
        ctx.resume().catch(() => {});
      }
      try {
        const buffer = ctx.createBuffer(1, 1, 22050);
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);
        source.start(0);
      } catch (e) {}
    }
  }

  ["click", "touchstart", "pointerdown", "keydown"].forEach((evt) => {
    window.addEventListener(evt, _unlockAudioEngine, { capture: true, passive: true });
  });

  async function preloadSoundBuffer(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) return null;
      const arrayBuffer = await res.arrayBuffer();
      const ctx = _getCtx();
      if (!ctx) return null;
      const decoded = await ctx.decodeAudioData(arrayBuffer);
      _audioBuffers[url] = decoded;
      return decoded;
    } catch (err) {
      console.warn("[som] Erro ao pré-carregar buffer:", url, err);
      return null;
    }
  }

  const SOUND_URLS = [
    "/static/sounds/fim_de_descanso.mp3",
    "/static/sounds/fim_de_foco.mp3",
    "/static/sounds/fim_dos_ciclos_de_foco.mp3",
    "/static/sounds/do_pos_conclusao.mp3",
    "/static/sounds/som_botao_iniciar.mp3",
    "/static/sounds/Pausar-foco.mp3"
  ];
  SOUND_URLS.forEach((url) => preloadSoundBuffer(url));

  let _activeRestEndSource = null;
  let _restEndAudio = null;

  function getVolumeForUrl(url) {
    const cfg = window.FOCUS_STATE || {};
    let pct = 100;
    const restUrl = cfg.soundRestEnd || "/static/sounds/fim_de_descanso.mp3";
    const focusUrl = cfg.soundFocusEnd || "/static/sounds/fim_de_foco.mp3";
    const concludeUrl = cfg.soundConcludeBtn || "/static/sounds/do_pos_conclusao.mp3";

    if (url === restUrl || url.includes("fim_de_descanso")) {
      pct = cfg.volumeRestEnd !== undefined ? cfg.volumeRestEnd : 100;
    } else if (url === focusUrl || url === concludeUrl || url.includes("fim_de_foco") || url.includes("fim_dos_ciclos") || url.includes("do_pos_conclusao")) {
      pct = cfg.volumeFocusEnd !== undefined ? cfg.volumeFocusEnd : 100;
    } else {
      pct = cfg.volumeSystem !== undefined ? cfg.volumeSystem : 100;
    }
    return Math.max(0, Math.min(1, pct / 100));
  }

  function playSound(url, isRestEnd = false) {
    _unlockAudioEngine();
    const ctx = _getCtx();
    const vol = getVolumeForUrl(url);

    if (ctx && _audioBuffers[url]) {
      try {
        const source = ctx.createBufferSource();
        source.buffer = _audioBuffers[url];
        const gainNode = ctx.createGain();
        gainNode.gain.value = vol;
        source.connect(gainNode);
        gainNode.connect(ctx.destination);
        source.start(0);
        if (isRestEnd) {
          _activeRestEndSource = source;
        }
        console.log("[som] Tocado via Web Audio API (vol=" + vol + "):", url);
        return;
      } catch (err) {
        console.warn("[som] Web Audio API falhou, usando fallback HTML5 Audio:", url, err);
      }
    }

    // Se o buffer não estava pré-carregado, tenta carregar para próximas execuções
    preloadSoundBuffer(url);

    const snd = new Audio(url);
    snd.volume = vol;
    if (isRestEnd) {
      _restEndAudio = snd;
    }
    snd.play().catch((err) => console.warn("[som] Erro ao tocar via HTML5 Audio:", url, err));
  }

  function playStartButtonSound() {
    playSound("/static/sounds/som_botao_iniciar.mp3");
  }

  function playPauseButtonSound() {
    playSound("/static/sounds/Pausar-foco.mp3");
  }

  function withStartButtonSound(handler) {
    return function () {
      playStartButtonSound();
      handler();
    };
  }

  function withPauseButtonSound(handler) {
    return function () {
      playPauseButtonSound();
      handler();
    };
  }

  function playRestEndSound() {
    const url = (window.FOCUS_STATE && window.FOCUS_STATE.soundRestEnd) || "/static/sounds/fim_de_descanso.mp3";
    console.log("[som] Disparando som de fim de descanso:", url);
    playSound(url, true);
  }

  function stopRestEndSound() {
    if (_activeRestEndSource) {
      try { _activeRestEndSource.stop(); } catch (e) {}
      _activeRestEndSource = null;
    }
    if (_restEndAudio && !_restEndAudio.paused) {
      console.log("[som] Interrompendo som de fim de descanso");
      _restEndAudio.pause();
      _restEndAudio.currentTime = 0;
    }
  }

  function playConclude() {
    const url = (window.FOCUS_STATE && window.FOCUS_STATE.soundConcludeBtn) || "/static/sounds/do_pos_conclusao.mp3";
    console.log("[som] playConclude() chamada:", url);
    playSound(url);
  }

  function playFocusEndSound(isLastCycleBeforeLongBreak) {
    const url = isLastCycleBeforeLongBreak
      ? "/static/sounds/fim_dos_ciclos_de_foco.mp3"
      : ((window.FOCUS_STATE && window.FOCUS_STATE.soundFocusEnd) || "/static/sounds/fim_de_foco.mp3");
    console.log("[som] Disparando som de fim de foco:", url);
    playSound(url);
  }

  // ── Audio Keep-Alive Ticker (evita suspensão da AudioContext durante o temporizador) ──
  let _keepAliveInterval = null;

  function startAudioKeepAlive() {
    if (_keepAliveInterval) return;
    _keepAliveInterval = setInterval(() => {
      if (state.status === "focusing" || state.status === "resting") {
        const ctx = _getCtx();
        if (ctx) {
          if (ctx.state === "suspended") {
            ctx.resume().catch(() => {});
          }
          try {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            gain.gain.value = 0.00001; // inaudível
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.01);
          } catch (e) {}
        }
      }
    }, 10000);
  }

  function stopAudioKeepAlive() {
    if (_keepAliveInterval) {
      clearInterval(_keepAliveInterval);
      _keepAliveInterval = null;
    }
  }

  // ── Screen Wake Lock API ───────────────────────────────────────────────────
  let wakeLockSentinel = null;
  let wakeLockRequested = false;

  async function requestWakeLock() {
    wakeLockRequested = true;
    if ("wakeLock" in navigator && !wakeLockSentinel) {
      try {
        wakeLockSentinel = await navigator.wakeLock.request("screen");
        console.log("[wakelock] Screen Wake Lock ativado com sucesso.");
        wakeLockSentinel.addEventListener("release", () => {
          console.log("[wakelock] Screen Wake Lock liberado.");
          wakeLockSentinel = null;
          if (wakeLockRequested && (state.status === "focusing" || state.status === "resting") && document.visibilityState === "visible") {
            requestWakeLock();
          }
        });
      } catch (err) {
        console.warn("[wakelock] Erro ao solicitar Screen Wake Lock:", err);
      }
    }
  }

  async function releaseWakeLock() {
    wakeLockRequested = false;
    if (wakeLockSentinel) {
      try {
        await wakeLockSentinel.release();
        wakeLockSentinel = null;
      } catch (err) {
        console.warn("[wakelock] Erro ao liberar Screen Wake Lock:", err);
      }
    }
  }

  document.addEventListener("visibilitychange", async () => {
    if (document.visibilityState === "visible" && (state.status === "focusing" || state.status === "resting")) {
      await requestWakeLock();
    }
  });

  window.addEventListener("click", () => {
    if ((state.status === "focusing" || state.status === "resting") && !wakeLockSentinel) {
      requestWakeLock();
    }
  }, { passive: true });

  function showPostCycleMessage(message) {
    if (!el.postCycleMsg) return;
    el.postCycleMsg.textContent = message || "";
    if (message) {
      setTimeout(() => { el.postCycleMsg.textContent = ""; }, 6000);
    }
  }

  function buildCompletionMessage(data) {
    if (!data) return "";
    let msg = data.post_cycle_message || "";
    if (!msg && data.last_result && data.last_result.post_cycle_message) {
      msg = data.last_result.post_cycle_message;
    }
    if (!msg && data.result && data.result.last_result && data.result.last_result.post_cycle_message) {
      msg = data.result.last_result.post_cycle_message;
    }
    if (data.extraordinary_just_unlocked) {
      msg = "Extraordinário desbloqueado — " + msg;
    } else if (data.rewards_achieved && data.rewards_achieved.length) {
      msg = "Recompensa conquistada: " + data.rewards_achieved.join(", ") + " — " + msg;
    } else if (data.result && data.result.last_result && data.result.last_result.rewards_achieved && data.result.last_result.rewards_achieved.length) {
      msg = "Recompensa conquistada: " + data.result.last_result.rewards_achieved.join(", ") + " — " + msg;
    }
    return msg;
  }

  function handleCompletionPayload(data, options) {
    const opts = options || {};
    if (opts.playConclude !== false) {
      playConclude();
    }
    if (data && data.home_state) {
      applyHomeState(data.home_state);
    } else if (data && data.result && data.result.last_result && data.result.last_result.home_state) {
      applyHomeState(data.result.last_result.home_state);
    } else if (data && data.last_result && data.last_result.home_state) {
      applyHomeState(data.last_result.home_state);
    }

    const message = buildCompletionMessage(data);
    if (message) {
      showPostCycleMessage(message);
    }
  }

  function handleSessionCompletionPayload(data) {
    handleCompletionPayload(data, { playConclude: false });

    const cyclesPerSession = Number(
      data && data.cycles_per_session != null
        ? data.cycles_per_session
        : window.FOCUS_STATE && window.FOCUS_STATE.cyclesPerSession
    ) || 0;
    const completedCycles = Number(
      data && (
        data.completed_cycles_after != null
          ? data.completed_cycles_after
          : data.completed_cycles != null
            ? data.completed_cycles
            : data.session_cycle_count != null
              ? data.session_cycle_count
              : 0
      )
    ) || 0;
    playFocusEndSound(
      cyclesPerSession > 0 && completedCycles > 0 && completedCycles % cyclesPerSession === 0
    );
  }

  // Expõe para uso do painel de debug e para testes no DevTools
  window.playConclude = playConclude;
  window.FocoDevTools = {
    playConclude,
    playFocusEndSound,
    applyHomeState,
    handleCompletionPayload,
    handleSessionCompletionPayload,
    showPostCycleMessage,
  };
  window.FocoTimer = window.FocoDevTools;
  // -------------------------------------------------------------------

  function fmt(seconds) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function showError(msg) {
    el.errorMsg.textContent = msg;
    setTimeout(() => { el.errorMsg.textContent = ""; }, 6000);
  }

  // Wrapper de fetch com tratamento de falha de rede/servidor — nunca
  // deixa o timer travado num estado inconsistente se a API falhar.
  async function apiFetch(url, opts) {
    let res;
    try {
      res = await fetch(url, opts);
    } catch (networkErr) {
      showError("Sem conexão com o servidor. Tente novamente.");
      return null;
    }
    if (!res.ok) {
      showError(`Erro no servidor (${res.status}). Tente novamente.`);
      return null;
    }
    try {
      return await res.json();
    } catch (parseErr) {
      showError("Resposta inválida do servidor.");
      return null;
    }
  }

  function render() {
    el.display.textContent = fmt(state.remainingSeconds);
    const isExtra = state.isExtraordinary || (window.FOCUS_STATE && window.FOCUS_STATE.dailyIdealCurrent >= window.FOCUS_STATE.dailyIdealGoal);
    el.display.className =
      "num timer-num " +
      (state.status === "finished" ? "finished" : isExtra ? "extraordinary" : state.status === "focusing" ? "focusing" : "");

    const promoBadge = document.getElementById("extra-promo-badge");
    const isStoppedOrPaused = state.status === "idle" || state.status === "paused" || state.status === "finished";
    if (isExtra && state.discountPct > 0 && isStoppedOrPaused) {
      const promoOrig = document.getElementById("extra-promo-original");
      const promoPill = document.getElementById("extra-promo-pill");
      if (promoBadge) {
        if (promoOrig) promoOrig.textContent = (state.baseDurationMinutes || window.FOCUS_STATE.focusMinutes) + " min";
        if (promoPill) promoPill.textContent = "-" + state.discountPct + "%";
        promoBadge.style.display = "flex";
      }
    } else {
      if (promoBadge) promoBadge.style.display = "none";
    }


    const labels = {
      idle: "IDLE", focusing: "FOCUSING", paused: "PAUSED", finished: "FINISHED",
      break_offer: "IDLE", resting: state.restKind === "long" ? "LONG BREAK" : "BREAK",
    };
    el.stateLabel.textContent = labels[state.status] || state.status.toUpperCase();


    if (state.status === "idle") {
      el.actions.innerHTML = `<button class="btn filled ${isExtra ? 'extraordinary' : ''}" id="btn-start">INICIAR</button>`;
      document.getElementById("btn-start").addEventListener("click", withStartButtonSound(startCycle));
    } else if (state.status === "focusing") {
      el.actions.innerHTML = `
        <button class="btn" id="btn-pause">PAUSAR</button>
        <button class="btn ghost" id="btn-stop">PARAR</button>`;
      document.getElementById("btn-pause").addEventListener("click", withPauseButtonSound(pauseCycle));
      document.getElementById("btn-stop").addEventListener("click", withStartButtonSound(stopCycle));
    } else if (state.status === "paused") {
      el.actions.innerHTML = `
        <button class="btn filled ${isExtra ? 'extraordinary' : ''}" id="btn-resume">RETOMAR</button>
        <button class="btn ghost" id="btn-stop">PARAR</button>`;
      document.getElementById("btn-resume").addEventListener("click", withStartButtonSound(resumeCycle));
      document.getElementById("btn-stop").addEventListener("click", withStartButtonSound(stopCycle));
    } else if (state.status === "finished") {
      el.actions.innerHTML = "";
    } else if (state.status === "break_offer") {
      const suggestLong = state.sessionCycleCount > 0 && state.sessionCycleCount % window.FOCUS_STATE.cyclesPerSession === 0;
      el.actions.innerHTML = `
        <button class="btn ${suggestLong ? '' : 'filled'}" id="btn-short-break">PAUSA CURTA</button>
        <button class="btn ${suggestLong ? 'filled' : ''}" id="btn-long-break">PAUSA LONGA</button>
        <button class="btn ghost" id="btn-skip-break">PULAR</button>`;
      document.getElementById("btn-short-break").addEventListener("click", withStartButtonSound(() => startBreak("short")));
      document.getElementById("btn-long-break").addEventListener("click", withStartButtonSound(() => startBreak("long")));
      document.getElementById("btn-skip-break").addEventListener("click", withStartButtonSound(skipBreak));
    } else if (state.status === "resting") {
      el.actions.innerHTML = `<button class="btn ghost" id="btn-skip-rest">ENCERRAR PAUSA</button>`;
      document.getElementById("btn-skip-rest").addEventListener("click", stopRest);
    }

    if (state.status === "resting" && !state.pauseCardDismissed) {
      document.body.classList.add("resting-mode");
      // Mover .timer-wrap para a zona protegida abaixo do pause-card
      const timerWrap = document.querySelector(".timer-wrap");
      const protectedZone = document.getElementById("protected-zone");
      if (timerWrap && protectedZone && timerWrap.parentElement !== protectedZone) {
        timerWrap._originalParent = timerWrap.parentElement;
        protectedZone.appendChild(timerWrap);
      }
      if (state.pauseMessage) {
        if (el.pauseMessage) el.pauseMessage.textContent = state.pauseMessage.mensagem;
        if (el.pauseLegend) {
          el.pauseLegend.textContent = state.pauseLegend;
          if (state.pauseLegendState === 3) {
            el.pauseLegend.className = "pause-legend extraordinary";
          } else {
            el.pauseLegend.className = "pause-legend";
          }
        }
        // Atualizar label QUADRO N
        const card = document.getElementById("pause-card");
        if (card && state.pauseMessage.id) {
          const ORDER = ["gato", "janela", "garrafa", "ampulheta", "cel"];
          const n = ORDER.indexOf(state.pauseMessage.id);
          card.dataset.quadro = "QUADRO" + (n >= 0 ? " " + (n + 1) : "");
        }
        const rightEl = document.querySelector(".pause-card-right");
        if (rightEl && state.pauseMessage.id) {
          const ALL_IDS = ["gato", "janela", "garrafa", "ampulheta", "cel"];
          ALL_IDS.forEach(id => rightEl.classList.remove(id));
          rightEl.classList.add(state.pauseMessage.id);
        }
        setGif(state.pauseMessage.gif_url);
      }
    } else {
      document.body.classList.remove("resting-mode");
      // Restaurar .timer-wrap ao local original
      const timerWrap = document.querySelector(".timer-wrap");
      if (timerWrap && timerWrap._originalParent && timerWrap.parentElement !== timerWrap._originalParent) {
        timerWrap._originalParent.appendChild(timerWrap);
        timerWrap._originalParent = null;
      }
      clearGif();
      const rightEl = document.querySelector(".pause-card-right");
      if (rightEl) {
        const ALL_IDS = ["gato", "janela", "garrafa", "ampulheta", "cel"];
        ALL_IDS.forEach(id => rightEl.classList.remove(id));
      }
    }

    if (el.modal) {
      el.modal.classList.toggle("open", state.modalOpen);
    }

    if (state.status === "focusing" || state.status === "resting") {
      requestWakeLock();
      startAudioKeepAlive();
    } else {
      releaseWakeLock();
      stopAudioKeepAlive();
    }

    persistTimerState();
  }

  function tick() {
    if (state.endTime) {
      const now = Date.now();
      state.remainingSeconds = Math.max(0, Math.round((state.endTime - now) / 1000));
    } else {
      state.remainingSeconds -= 1;
    }

    if (state.remainingSeconds <= 0) {
      state.remainingSeconds = 0;
      stopTicker();
      state.endTime = null;
      if (state.status === "focusing") {
        state.status = "finished";
        const completedCycleCount = state.sessionCycleCount + 1;
        const isLastCycleBeforeLongBreak =
          completedCycleCount > 0 &&
          completedCycleCount % window.FOCUS_STATE.cyclesPerSession === 0;
        playFocusEndSound(isLastCycleBeforeLongBreak);

        if (window.FOCUS_STATE && window.FOCUS_STATE.postCycleMessagesEnabled === false) {
          autoConcludeCycle(`Mensagem desabilitada #Ciclo ${completedCycleCount}`);
        } else {
          openModal();
          render();
        }
      } else if (state.status === "resting") {
        playRestEndSound();
        finishRestNaturally();
      }
      return;
    }
    render();
  }

  async function startCycle(options) {
    const opts = options || {};
    if (!opts.isAutoStart) {
      stopRestEndSound(); // só interrompe o som de descanso se iniciado manualmente pelo usuário
    }
    const data = await apiFetch("/api/cycles/start", { method: "POST" });
    if (!data) return; // falha já mostrada ao usuário, estado permanece idle
    state.cycleId = data.cycle_id;
    state.remainingSeconds = data.focus_duration_minutes * 60;
    state.status = "focusing";
    state.isExtraordinary = !!data.is_extraordinary;
    state.discountPct = data.discount_pct || 0;
    state.baseDurationMinutes = data.base_duration_minutes || 0;
    state.endTime = Date.now() + state.remainingSeconds * 1000;
    state.modalOpen = false;
    state.restId = null;
    state.restKind = null;

    render();
    startTicker();
  }

  function pauseCycle() {
    stopTicker();
    if (state.endTime) {
      const now = Date.now();
      state.remainingSeconds = Math.max(0, Math.round((state.endTime - now) / 1000));
    }
    state.endTime = null;
    state.status = "paused";
    state.modalOpen = false;
    render();
  }

  function resumeCycle() {
    state.status = "focusing";
    state.endTime = Date.now() + state.remainingSeconds * 1000;
    state.modalOpen = false;
    render();
    startTicker();
  }

  async function stopCycle() {
    stopTicker();
    state.endTime = null;
    if (state.cycleId) {
      await apiFetch(`/api/cycles/${state.cycleId}/abandon`, { method: "POST" });
    }
    state.cycleId = null;
    state.status = "idle";
    state.modalOpen = false;
    state.pauseCardDismissed = false;
    state.remainingSeconds = (window.FOCUS_STATE ? window.FOCUS_STATE.focusMinutes : 35) * 60;

    const homeData = await apiFetch("/api/home-state");
    if (homeData) {
      applyHomeState(homeData);
    } else {
      state.isExtraordinary = false;
      state.discountPct = 0;
      state.remainingSeconds = (window.FOCUS_STATE ? window.FOCUS_STATE.focusMinutes : 35) * 60;
    }
    render();
  }

  function openModal() {
    el.titleInput.value = "";
    state.modalOpen = true;
    if (el.modal) {
      el.modal.classList.add("open");
    }
    persistTimerState();
  }

  function closeModal() {
    state.modalOpen = false;
    if (el.modal) {
      el.modal.classList.remove("open");
    }
    persistTimerState();
  }

  function applyHomeState(homeState) {
    const blocks = document.querySelectorAll(".barblock .barfill");
    const labels = document.querySelectorAll(".barblock .barvalue");

    if (blocks[0]) blocks[0].style.width = homeState.daily_minimum.pct + "%";
    if (labels[0]) labels[0].textContent = `${homeState.daily_minimum.current} / ${homeState.daily_minimum.goal}`;
    if (blocks[1]) blocks[1].style.width = homeState.daily_ideal.pct + "%";
    if (labels[1]) labels[1].textContent = `${homeState.daily_ideal.current} / ${homeState.daily_ideal.goal}`;

    // Atualizar os títulos ativos das legendas home-group-label
    const labelMinimum = document.getElementById("label-minimum");
    if (labelMinimum) {
      labelMinimum.textContent = homeState.daily_minimum.title 
        ? `MÉDIA — ${homeState.daily_minimum.title.toUpperCase()}`
        : "MÉDIA";
    }
    const labelIdeal = document.getElementById("label-ideal");
    if (labelIdeal) {
      labelIdeal.textContent = homeState.daily_ideal.title 
        ? `IDEAL — ${homeState.daily_ideal.title.toUpperCase()}`
        : "IDEAL";
    }
    const labelWeekly = document.getElementById("label-weekly");
    if (labelWeekly) {
      labelWeekly.textContent = homeState.weekly.title 
        ? `SEMANAL — ${homeState.weekly.title.toUpperCase()}`
        : "SEMANAL";
    }

    if (homeState.extraordinary) {
      el.extraBlock.classList.add("visible");
      if (el.extraHint) el.extraHint.style.opacity = "0";
      el.extraFill.style.width = Math.min(100, homeState.extraordinary.cycles * 15) + "%";
      const valueEl = el.extraBlock.querySelector(".barvalue");
      if (valueEl) valueEl.textContent = "+" + homeState.extraordinary.cycles;

      if (homeState.extraordinary.next_discount_pct !== undefined) {
        state.isExtraordinary = true;
        state.discountPct = homeState.extraordinary.next_discount_pct;
        state.baseDurationMinutes = homeState.extraordinary.next_base_minutes || window.FOCUS_STATE.focusMinutes;
        if (state.status === "idle") {
          state.remainingSeconds = (homeState.extraordinary.next_effective_minutes || window.FOCUS_STATE.focusMinutes) * 60;
        }
      }
    }


    document.querySelectorAll(".barblock").forEach((block) => {
      const label = block.querySelector(".barlabel span");
      if (!label) return;
      const text = label.textContent.trim();
      if (text === "Semanal") {
        block.querySelector(".barfill").style.width = homeState.weekly.pct + "%";
        block.querySelector(".barvalue").textContent = `${homeState.weekly.current} / ${homeState.weekly.goal}`;
      }
      if (text === "Absoluto" && homeState.absolute) {
        block.querySelector(".barfill").style.width = homeState.absolute.pct + "%";
        block.querySelector(".barvalue").textContent = `${homeState.absolute.current} / ${homeState.absolute.goal}`;
      }
    });

    if (homeState.water) {
      const bottleFill = document.getElementById("bottle-fill");
      if (bottleFill) {
        bottleFill.style.height = `${Math.min(100, homeState.water.pct)}%`;
      }
      const waterValue = document.getElementById("water-value");
      if (waterValue) {
        waterValue.textContent = `${homeState.water.total_l}L / ${homeState.water.goal_l}L`;
      }
    }

    if (homeState.cfg) {
      if (homeState.cfg.auto_start_focus !== undefined) window.FOCUS_STATE.autoStartFocus = homeState.cfg.auto_start_focus;
      if (homeState.cfg.auto_start_break !== undefined) window.FOCUS_STATE.autoStartBreak = homeState.cfg.auto_start_break;
      if (homeState.cfg.post_cycle_messages_enabled !== undefined) window.FOCUS_STATE.postCycleMessagesEnabled = homeState.cfg.post_cycle_messages_enabled;
      if (homeState.cfg.volume_system !== undefined) window.FOCUS_STATE.volumeSystem = homeState.cfg.volume_system;
      if (homeState.cfg.volume_focus_end !== undefined) window.FOCUS_STATE.volumeFocusEnd = homeState.cfg.volume_focus_end;
      if (homeState.cfg.volume_rest_end !== undefined) window.FOCUS_STATE.volumeRestEnd = homeState.cfg.volume_rest_end;
      if (homeState.cfg.sound_focus_end !== undefined) window.FOCUS_STATE.soundFocusEnd = homeState.cfg.sound_focus_end;
      if (homeState.cfg.sound_conclude_btn !== undefined) window.FOCUS_STATE.soundConcludeBtn = homeState.cfg.sound_conclude_btn;
      if (homeState.cfg.sound_rest_end !== undefined) window.FOCUS_STATE.soundRestEnd = homeState.cfg.sound_rest_end;
    }
  }

  async function autoConcludeCycle(titleText) {
    playConclude();
    if (!state.cycleId) {
      closeModal();
      state.status = "idle";
      render();
      return;
    }
    const data = await apiFetch(`/api/cycles/${state.cycleId}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: titleText }),
    });

    if (!data) {
      state.status = "idle";
      render();
      return;
    }

    handleCompletionPayload(data, { playConclude: false });
    closeModal();

    state.cycleId = null;
    state.sessionCycleCount += 1;
    state.remainingSeconds = window.FOCUS_STATE.focusMinutes * 60;
    state.modalOpen = false;

    // Incrementar contador hídrico ao concluir ciclo com sucesso
    incrementWaterCycles();

    state.status = "break_offer";
    render();

    if (window.FOCUS_STATE && window.FOCUS_STATE.autoStartBreak) {
      const suggestLong = state.sessionCycleCount > 0 && state.sessionCycleCount % window.FOCUS_STATE.cyclesPerSession === 0;
      startBreak(suggestLong ? "long" : "short");
    }
  }

  el.concludeBtn.addEventListener("click", async () => {
    console.log("[som] botão Concluir clicado — chamando playConclude()");
    playConclude();
    if (!state.cycleId) {
      closeModal();
      state.status = "idle";
      render();
      return;
    }
    el.concludeBtn.disabled = true;
    const data = await apiFetch(`/api/cycles/${state.cycleId}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: el.titleInput.value }),
    });
    el.concludeBtn.disabled = false;

    if (!data) {
      // falha ao concluir — mantemos o modal aberto para o usuário tentar de novo,
      // nunca fingimos sucesso (seção 42: sem contabilização parcial na UI).
      return;
    }

    handleCompletionPayload(data, { playConclude: false });
    closeModal();

    state.cycleId = null;
    state.sessionCycleCount += 1;
    state.remainingSeconds = window.FOCUS_STATE.focusMinutes * 60;
    state.modalOpen = false;

    // Incrementar contador hídrico ao concluir ciclo com sucesso
    incrementWaterCycles();

    state.status = "break_offer";
    render();

    if (window.FOCUS_STATE && window.FOCUS_STATE.autoStartBreak) {
      const suggestLong = state.sessionCycleCount > 0 && state.sessionCycleCount % window.FOCUS_STATE.cyclesPerSession === 0;
      startBreak(suggestLong ? "long" : "short");
    }
  });


  // Pressionar Enter na tela inicial dispara o botão principal (Iniciar, Retomar, Concluir modal ou Concluir pausa)
  document.addEventListener("keydown", function(e) {
    if (e.key !== "Enter") return;

    if (el.modal && el.modal.classList.contains("open")) {
      if (!el.concludeBtn.disabled) {
        e.preventDefault();
        el.concludeBtn.click();
      }
      return;
    }

    const active = document.activeElement;
    const isInput = active && (
      active.tagName === "INPUT" ||
      active.tagName === "TEXTAREA" ||
      active.tagName === "SELECT" ||
      active.isContentEditable
    );
    if (isInput) return;

    // Se estiver em descanso/pausa com o painel de pausa visível, o Enter aciona o botão CONCLUIR do painel (btn-pause-conclude)
    if (state.status === "resting" && !state.pauseCardDismissed && el.pauseConcludeBtn) {
      e.preventDefault();
      el.pauseConcludeBtn.click();
      return;
    }

    const mainBtn = document.getElementById("btn-start") ||
                    document.getElementById("btn-resume") ||
                    document.getElementById("btn-conclude-pause");
    if (mainBtn) {
      e.preventDefault();
      mainBtn.click();
    }
  });

  async function startBreak(kind) {
    const waterAlert = shouldShowWaterAlert();
    const data = await apiFetch("/api/rest/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, last_message_id: state.lastMessageId, water_alert: waterAlert }),
    });
    if (!data) return;
    // Se era alerta hídrico, resetar o contador (o alerta foi entregue)
    if (waterAlert) resetWaterCycles();
    state.restId = data.rest_id;
    state.restKind = data.kind;
    state.remainingSeconds = data.duration_minutes * 60;
    state.status = "resting";
    state.pauseCardDismissed = false;
    state.pauseMessage = data.pause_message;
    state.pauseLegend = data.legend_text;
    state.pauseLegendState = data.legend_state;
    if (data.pause_message) {
      state.lastMessageId = data.pause_message.id;
    }
    state.endTime = Date.now() + state.remainingSeconds * 1000;
    state.modalOpen = false;
    render();
    startTicker();
  }


  async function skipBreak() {
    state.status = "idle";
    state.modalOpen = false;
    state.pauseCardDismissed = false;
    const homeData = await apiFetch("/api/home-state");
    if (homeData) {
      applyHomeState(homeData);
    }
    render();

    if (window.FOCUS_STATE && window.FOCUS_STATE.autoStartFocus) {
      startCycle();
    }
  }

  async function finishRestNaturally() {
    if (state.restId) {
      await apiFetch(`/api/rest/${state.restId}/complete`, { method: "POST" });
    }
    state.restId = null;
    state.status = "idle";
    state.pauseMessage = null;
    state.pauseLegend = "";
    state.pauseLegendState = 1;
    state.modalOpen = false;
    state.pauseCardDismissed = false;
    const homeData = await apiFetch("/api/home-state");
    if (homeData) {
      applyHomeState(homeData);
    }
    render();

    if (window.FOCUS_STATE && window.FOCUS_STATE.autoStartFocus) {
      startCycle({ isAutoStart: true });
    }
  }

  async function stopRest() {
    stopTicker();
    state.endTime = null;
    if (state.restId) {
      await apiFetch(`/api/rest/${state.restId}/abandon`, { method: "POST" });
    }
    state.restId = null;
    state.status = "idle";
    state.pauseMessage = null;
    state.pauseLegend = "";
    state.pauseLegendState = 1;
    state.modalOpen = false;
    state.pauseCardDismissed = false;
    const homeData = await apiFetch("/api/home-state");
    if (homeData) {
      applyHomeState(homeData);
    }
    render();
  }

  if (el.pauseConcludeBtn) {
    el.pauseConcludeBtn.addEventListener("click", function () {
      state.pauseCardDismissed = true;
      render();
    });
  }

  window.addEventListener("beforeunload", persistTimerState);
  restoreTimerState();

  if (window.FOCUS_STATE && window.FOCUS_STATE.extraordinaryPromo) {
    const promo = window.FOCUS_STATE.extraordinaryPromo;
    state.isExtraordinary = true;
    state.discountPct = promo.discount_pct || 0;
    state.baseDurationMinutes = promo.base_minutes || window.FOCUS_STATE.focusMinutes;
    if (state.status === "idle") {
      state.remainingSeconds = (promo.effective_minutes || window.FOCUS_STATE.focusMinutes) * 60;
    }
  }

  render();

})();

// ── Debug: Preview do Painel de Pausa ──────────────────────────────────────
window.focoPauseDebug = (function () {
  "use strict";

  // Nomes reais dos GIFs no disco (divergem do prompt — ver api.py)
  const ALL_MESSAGES = [
    { id: "gato",      mensagem: "Alongue-se",                        gif_url: "/GIFs/GIFGATO.gif" },
    { id: "janela",    mensagem: "Olhe para longe",                   gif_url: "/GIFs/JANELAGIF.gif" },
    { id: "garrafa",   mensagem: "Encha a garrafa de água",           gif_url: "/GIFs/GARRAFAGIF.gif" },
    { id: "garrafa",   mensagem: "Beba água",                         gif_url: "/GIFs/GARRAFAGIF.gif" }, // alerta hídrico (3+ ciclos sem água)
    { id: "ampulheta", mensagem: "Só pare um pouco",                  gif_url: "/GIFs/AMPULHETAGIF.gif" },
    { id: "cel",       mensagem: "Cheque as mensagens da namorada",   gif_url: "/GIFs/CELGIF.gif" }
  ];

  var currentIdx = 0;
  var active = false;

  function adjustGifUrlForTheme(gifUrl) {
    if (!gifUrl) return gifUrl;
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    if (isDark) {
      var match = gifUrl.match(/^(.*)(\.[a-zA-Z0-9]+)$/);
      if (match) {
        var name = match[1];
        var ext = match[2];
        if (!name.endsWith("1")) {
          return name + "1" + ext;
        }
      }
    } else {
      var match = gifUrl.match(/^(.*)1(\.[a-zA-Z0-9]+)$/);
      if (match) {
        return match[1] + match[2];
      }
    }
    return gifUrl;
  }

  function applyMessage(msg) {
    var msgEl  = document.getElementById("pause-message");
    var legEl  = document.getElementById("pause-legend");
    var imgEl  = document.getElementById("pause-animation");
    var card   = document.getElementById("pause-card");
    if (msgEl) msgEl.textContent = msg.mensagem;
    if (legEl) { legEl.textContent = "Fim do ciclo 4 de foco · 3 ciclos da média  [PREVIEW]"; legEl.className = "pause-legend"; }
    if (imgEl) {
      var adjustedUrl = adjustGifUrlForTheme(msg.gif_url);
      imgEl.src = adjustedUrl + "?t=" + Date.now();
    }
    if (card)  card.dataset.quadro = "QUADRO " + (currentIdx + 1);
    var rightEl = document.querySelector(".pause-card-right");
    if (rightEl && msg.id) {
      var ALL_IDS = ["gato", "janela", "garrafa", "ampulheta", "cel"];
      ALL_IDS.forEach(function(id) { rightEl.classList.remove(id); });
      rightEl.classList.add(msg.id);
    }
  }

  function moveToDom() {
    var timerWrap    = document.querySelector(".timer-wrap");
    var protectedZone = document.getElementById("protected-zone");
    if (timerWrap && protectedZone && timerWrap.parentElement !== protectedZone) {
      timerWrap._debugOriginalParent = timerWrap.parentElement;
      protectedZone.appendChild(timerWrap);
    }
  }

  function restoreDom() {
    var timerWrap = document.querySelector(".timer-wrap");
    if (timerWrap && timerWrap._debugOriginalParent &&
        timerWrap.parentElement !== timerWrap._debugOriginalParent) {
      timerWrap._debugOriginalParent.appendChild(timerWrap);
      timerWrap._debugOriginalParent = null;
    }
  }

  function updateDevInfo(msg, idx) {
    var infoEl = document.getElementById("devtools-pause-info");
    if (!infoEl) return;
    infoEl.style.display = "block";
    infoEl.innerHTML = "<strong>" + (idx + 1) + "/" + ALL_MESSAGES.length + "</strong>"
      + " — id: <code>" + msg.id + "</code>, gif: <code>" + msg.gif_url.split("/").pop() + "</code>";
  }

  function show() {
    if (!document.getElementById("pause-card")) {
      alert("O painel de pausa só existe na página inicial.");
      return;
    }
    active = true; currentIdx = 0;
    document.body.classList.add("resting-mode");
    moveToDom();
    applyMessage(ALL_MESSAGES[currentIdx]);
    updateDevInfo(ALL_MESSAGES[currentIdx], currentIdx);
    var btn     = document.getElementById("devtools-pause-preview");
    var nextBtn = document.getElementById("devtools-pause-next");
    var closeBtn= document.getElementById("devtools-pause-close");
    if (btn)     btn.style.display = "none";
    if (nextBtn) nextBtn.style.display = "";
    if (closeBtn)closeBtn.style.display = "";
  }

  function next() {
    if (!active) return;
    currentIdx = (currentIdx + 1) % ALL_MESSAGES.length;
    applyMessage(ALL_MESSAGES[currentIdx]);
    updateDevInfo(ALL_MESSAGES[currentIdx], currentIdx);
  }

  function hide() {
    active = false;
    var imgEl = document.getElementById("pause-animation");
    if (imgEl) imgEl.src = "";
    document.body.classList.remove("resting-mode");
    restoreDom();
    var rightEl = document.querySelector(".pause-card-right");
    if (rightEl) {
      var ALL_IDS = ["gato", "janela", "garrafa", "ampulheta", "cel"];
      ALL_IDS.forEach(function(id) { rightEl.classList.remove(id); });
    }
    var btn     = document.getElementById("devtools-pause-preview");
    var nextBtn = document.getElementById("devtools-pause-next");
    var closeBtn= document.getElementById("devtools-pause-close");
    var infoEl  = document.getElementById("devtools-pause-info");
    if (btn)     btn.style.display = "";
    if (nextBtn) nextBtn.style.display = "none";
    if (closeBtn)closeBtn.style.display = "none";
    if (infoEl)  infoEl.style.display = "none";
  }

  // Botões existem no DOM quando timer.js executa (final do body) — binding direto
  (function wireButtons() {
    var previewBtn = document.getElementById("devtools-pause-preview");
    var nextBtn    = document.getElementById("devtools-pause-next");
    var closeBtn   = document.getElementById("devtools-pause-close");
    if (previewBtn) previewBtn.addEventListener("click", show);
    if (nextBtn)    nextBtn.addEventListener("click", next);
    if (closeBtn)   closeBtn.addEventListener("click", hide);
  })();

  return { show, next, hide };
})();
