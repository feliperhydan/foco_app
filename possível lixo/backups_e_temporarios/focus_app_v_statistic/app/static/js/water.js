(function () {
  "use strict";
  const btn = document.getElementById("btn-water");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const res = await fetch("/api/water/log", { method: "POST" });
    const data = await res.json();
    const label = btn.previousElementSibling; // <span class="section-label">
    if (label) {
      label.innerHTML = `ÁGUA HOJE: <span class="num" style="font-size:13px;">${data.total_l} L</span>`;
    }
    btn.disabled = false;
  });
})();
