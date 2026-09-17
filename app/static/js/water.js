(function () {
  "use strict";
  const btn = document.getElementById("btn-water");
  const toggle = document.getElementById("toggle-water");
  const wrap = document.getElementById("water-wrap");

  if (toggle && wrap) {
    toggle.addEventListener("click", (e) => {
      e.preventDefault();
      wrap.classList.toggle("open");
    });
  }

  if (!btn) return;

  function playBottleSound() {
    const pct = (window.FOCUS_STATE && window.FOCUS_STATE.volumeSystem !== undefined) ? window.FOCUS_STATE.volumeSystem : 100;
    const vol = Math.max(0, Math.min(1, pct / 100));
    const sound = new Audio("/static/sounds/mais_1_garrafa.mp3");
    sound.volume = vol;
    sound.play().catch((err) => console.warn("[som] +1_garrafa.mp3", err));
  }

  btn.addEventListener("click", async () => {
    playBottleSound();
    btn.disabled = true;
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

      // Resetar contador hídrico — o usuário adicionou água, reiniciar contagem
      try { localStorage.removeItem("foco_water_cycles_v1"); } catch { /* noop */ }
    } catch (err) {
      console.error("Erro ao registrar água:", err);
    } finally {
      btn.disabled = false;
    }
  });
})();
