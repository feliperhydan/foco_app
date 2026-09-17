(function () {
  "use strict";

  const wrap = document.getElementById("calendar-wrap");
  const toggle = document.getElementById("toggle-calendar");
  const heatmapEl = document.getElementById("heatmap");
  const modeButtons = document.querySelectorAll(".tag[data-mode]");

  let currentMode = "cycles";
  let loaded = false;

  function renderGrid(grid) {
    heatmapEl.innerHTML = "";
    grid.forEach((week) => {
      const col = document.createElement("div");
      col.className = "hcol";
      week.forEach((day) => {
        const cell = document.createElement("div");
        cell.className = "hcell l" + day.level;
        cell.title = `${day.date} · ${day.value}`;
        col.appendChild(cell);
      });
      heatmapEl.appendChild(col);
    });
  }

  async function loadCalendar(mode) {
    const res = await fetch(`/api/calendar?mode=${mode}&weeks=18`);
    const data = await res.json();
    renderGrid(data.grid);
  }

  toggle.addEventListener("click", (e) => {
    e.preventDefault();
    wrap.classList.toggle("open");
    if (wrap.classList.contains("open") && !loaded) {
      loaded = true;
      loadCalendar(currentMode);
    }
  });

  modeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      modeButtons.forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");
      currentMode = btn.dataset.mode;
      loadCalendar(currentMode);
    });
  });
})();
