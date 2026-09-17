(function () {
  "use strict";

  const state = {
    status: "idle", // idle | focusing | paused | finished | break_offer | resting
    cycleId: null,
    restId: null,
    restKind: null, // 'short' | 'long'
    remainingSeconds: window.FOCUS_STATE.focusMinutes * 60,
    intervalId: null,
    sessionCycleCount: 0, // contagem local só para decidir pausa curta/longa (seção 27)
  };

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
  };

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
    el.display.className =
      "num timer-num " +
      (state.status === "focusing" ? "focusing" : state.status === "finished" ? "finished" : "");

    const labels = {
      idle: "IDLE", focusing: "FOCUSING", paused: "PAUSED", finished: "FINISHED",
      break_offer: "IDLE", resting: state.restKind === "long" ? "LONG BREAK" : "BREAK",
    };
    el.stateLabel.textContent = labels[state.status] || state.status.toUpperCase();

    if (state.status === "idle") {
      el.actions.innerHTML = `<button class="btn filled" id="btn-start">INICIAR</button>`;
      document.getElementById("btn-start").addEventListener("click", startCycle);
    } else if (state.status === "focusing") {
      el.actions.innerHTML = `
        <button class="btn" id="btn-pause">PAUSAR</button>
        <button class="btn ghost" id="btn-stop">PARAR</button>`;
      document.getElementById("btn-pause").addEventListener("click", pauseCycle);
      document.getElementById("btn-stop").addEventListener("click", stopCycle);
    } else if (state.status === "paused") {
      el.actions.innerHTML = `
        <button class="btn filled" id="btn-resume">RETOMAR</button>
        <button class="btn ghost" id="btn-stop">PARAR</button>`;
      document.getElementById("btn-resume").addEventListener("click", resumeCycle);
      document.getElementById("btn-stop").addEventListener("click", stopCycle);
    } else if (state.status === "finished") {
      el.actions.innerHTML = "";
    } else if (state.status === "break_offer") {
      const suggestLong = state.sessionCycleCount > 0 && state.sessionCycleCount % window.FOCUS_STATE.cyclesPerSession === 0;
      el.actions.innerHTML = `
        <button class="btn ${suggestLong ? '' : 'filled'}" id="btn-short-break">PAUSA CURTA</button>
        <button class="btn ${suggestLong ? 'filled' : ''}" id="btn-long-break">PAUSA LONGA</button>
        <button class="btn ghost" id="btn-skip-break">PULAR</button>`;
      document.getElementById("btn-short-break").addEventListener("click", () => startBreak("short"));
      document.getElementById("btn-long-break").addEventListener("click", () => startBreak("long"));
      document.getElementById("btn-skip-break").addEventListener("click", skipBreak);
    } else if (state.status === "resting") {
      el.actions.innerHTML = `<button class="btn ghost" id="btn-skip-rest">ENCERRAR PAUSA</button>`;
      document.getElementById("btn-skip-rest").addEventListener("click", stopRest);
    }
  }

  function tick() {
    state.remainingSeconds -= 1;
    if (state.remainingSeconds <= 0) {
      state.remainingSeconds = 0;
      clearInterval(state.intervalId);
      if (state.status === "focusing") {
        state.status = "finished";
        render();
        openModal();
      } else if (state.status === "resting") {
        finishRestNaturally();
      }
      return;
    }
    render();
  }

  async function startCycle() {
    const data = await apiFetch("/api/cycles/start", { method: "POST" });
    if (!data) return; // falha já mostrada ao usuário, estado permanece idle
    state.cycleId = data.cycle_id;
    state.remainingSeconds = data.focus_duration_minutes * 60;
    state.status = "focusing";
    render();
    state.intervalId = setInterval(tick, 1000);
  }

  function pauseCycle() {
    clearInterval(state.intervalId);
    state.status = "paused";
    render();
  }

  function resumeCycle() {
    state.status = "focusing";
    render();
    state.intervalId = setInterval(tick, 1000);
  }

  async function stopCycle() {
    clearInterval(state.intervalId);
    if (state.cycleId) {
      await apiFetch(`/api/cycles/${state.cycleId}/abandon`, { method: "POST" });
    }
    state.cycleId = null;
    state.status = "idle";
    state.remainingSeconds = window.FOCUS_STATE.focusMinutes * 60;
    render();
  }

  function openModal() {
    el.titleInput.value = "";
    el.modal.classList.add("open");
  }

  function closeModal() {
    el.modal.classList.remove("open");
  }

  function applyHomeState(homeState) {
    const blocks = document.querySelectorAll(".barblock .barfill");
    const labels = document.querySelectorAll(".barblock .barvalue");

    if (blocks[0]) blocks[0].style.width = homeState.daily_minimum.pct + "%";
    if (labels[0]) labels[0].textContent = `${homeState.daily_minimum.current} / ${homeState.daily_minimum.goal}`;
    if (blocks[1]) blocks[1].style.width = homeState.daily_ideal.pct + "%";
    if (labels[1]) labels[1].textContent = `${homeState.daily_ideal.current} / ${homeState.daily_ideal.goal}`;

    if (homeState.extraordinary) {
      el.extraBlock.style.display = "block";
      if (el.extraHint) el.extraHint.style.display = "none";
      el.extraFill.style.width = Math.min(100, homeState.extraordinary.cycles * 15) + "%";
      const valueEl = el.extraBlock.querySelector(".barvalue");
      if (valueEl) valueEl.textContent = "+" + homeState.extraordinary.cycles;
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
  }

  el.concludeBtn.addEventListener("click", async () => {
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

    applyHomeState(data.home_state);
    closeModal();

    state.cycleId = null;
    state.sessionCycleCount += 1;
    state.remainingSeconds = window.FOCUS_STATE.focusMinutes * 60;

    let msg = data.post_cycle_message || "";
    if (data.extraordinary_just_unlocked) {
      msg = "Extraordinário desbloqueado — " + msg;
    } else if (data.rewards_achieved && data.rewards_achieved.length) {
      msg = "Recompensa conquistada: " + data.rewards_achieved.join(", ") + " — " + msg;
    }
    el.postCycleMsg.textContent = msg;
    setTimeout(() => { el.postCycleMsg.textContent = ""; }, 6000);

    state.status = "break_offer";
    render();
  });

  async function startBreak(kind) {
    const data = await apiFetch("/api/rest/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind }),
    });
    if (!data) return;
    state.restId = data.rest_id;
    state.restKind = data.kind;
    state.remainingSeconds = data.duration_minutes * 60;
    state.status = "resting";
    render();
    state.intervalId = setInterval(tick, 1000);
  }

  function skipBreak() {
    state.status = "idle";
    render();
  }

  async function finishRestNaturally() {
    if (state.restId) {
      await apiFetch(`/api/rest/${state.restId}/complete`, { method: "POST" });
    }
    state.restId = null;
    state.status = "idle";
    state.remainingSeconds = window.FOCUS_STATE.focusMinutes * 60;
    render();
  }

  async function stopRest() {
    clearInterval(state.intervalId);
    if (state.restId) {
      await apiFetch(`/api/rest/${state.restId}/abandon`, { method: "POST" });
    }
    state.restId = null;
    state.status = "idle";
    state.remainingSeconds = window.FOCUS_STATE.focusMinutes * 60;
    render();
  }

  render();
})();
