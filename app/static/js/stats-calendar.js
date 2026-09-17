document.addEventListener("DOMContentLoaded", function() {
  var topStrip = document.getElementById("cal-hover-strip-top");
  var leftStrip = document.getElementById("cal-hover-strip-left");
  var monthLabels = document.getElementById("cal-month-labels");
  var weekLabels = document.getElementById("cal-week-labels");
  var summaryButtons = document.querySelectorAll("[data-summary-scale]");
  var summaryData = window.STATS_SUMMARY_DATA || {};
  var summaryComparisons = window.STATS_SUMMARY_COMPARISONS || {};
  var summaryStorageKey = "foco_stats_summary_scale_v1";
  var activeSummaryScale = window.STATS_SUMMARY_SCALE || "day";

  function saveSummaryScale(scale) {
    // No-op to avoid storing in localStorage and keep header scale synchronized with top switch
  }

  function formatMinutes(totalMinutes) {
    var total = Number(totalMinutes) || 0;
    var hours = Math.floor(total / 60);
    var minutes = total % 60;
    return hours + "h" + String(minutes).padStart(2, "0");
  }

  function pctClass(pct) {
    if (pct > 0) return "up";
    if (pct < 0) return "down";
    return "flat";
  }

  function getSummary(scale) {
    return summaryData[scale] || summaryData.day || {};
  }

  function getComparison(scale) {
    return summaryComparisons[scale] || summaryComparisons.day || {};
  }

  function setCompareLine(el, html) {
    if (!el) return;
    el.innerHTML = html || "";
  }

  function setText(selector, value) {
    var el = document.querySelector(selector);
    if (el) {
      el.textContent = value;
    }
  }

  function applySummaryScale(scale) {
    var comparison = getComparison(scale);
    var isDay = scale === "day";
    var cycleCompare = document.querySelector('[data-summary-compare="cycles"]');
    var minuteCompare = document.querySelector('[data-summary-compare="minutes"]');
    var activeLabel = document.querySelector('[data-summary-label="active"]');
    var activeValue = document.querySelector('[data-summary-value="active"]');
    var activeCompare = document.querySelector('[data-summary-compare="active"]');
    var activeDelta = document.querySelector('[data-summary-delta="active"]');
    var extraValue = document.querySelector('[data-summary-value="extraordinary"]');
    var extraCompare = document.querySelector('[data-summary-compare="extraordinary"]');
    var extraDelta = document.querySelector('[data-summary-delta="extraordinary"]');

    summaryButtons.forEach(function(button) {
      button.classList.toggle("on", button.getAttribute("data-summary-scale") === scale);
    });

    setText('[data-summary-value="cycles"]', comparison.cycles ? comparison.cycles.b : 0);
    setText('[data-summary-value="minutes"]', formatMinutes(comparison.minutes ? comparison.minutes.b : 0));
    setText('[data-summary-value="active"]', comparison.active_days ? comparison.active_days.b : 0);
    setText('[data-summary-value="extraordinary"]', "+" + ((comparison.extraordinary && comparison.extraordinary.cycles) ? comparison.extraordinary.cycles.b : 0));

    if (comparison.cycles && comparison.cycles.pct != null) {
      setCompareLine(cycleCompare, '<span class="pct ' + pctClass(comparison.cycles.pct) + '">' + (comparison.cycles.pct > 0 ? "+" : "") + comparison.cycles.pct + '%</span><span>vs. ' + comparison.cycles.a + ' no período anterior</span>');
    } else {
      setCompareLine(cycleCompare, "");
    }

    if (comparison.minutes && comparison.minutes.pct != null) {
      setCompareLine(minuteCompare, '<span class="pct ' + pctClass(comparison.minutes.pct) + '">' + (comparison.minutes.pct > 0 ? "+" : "") + comparison.minutes.pct + '%</span><span>vs. ' + formatMinutes(comparison.minutes.a) + ' no período anterior</span>');
    } else {
      setCompareLine(minuteCompare, "");
    }

    if (activeLabel) {
      activeLabel.textContent = isDay ? "Sequência ativa" : "Dias ativos";
    }

    if (activeValue) {
      activeValue.textContent = comparison.active_days ? comparison.active_days.b : 0;
    }

    if (isDay) {
      if (activeCompare) {
        activeCompare.style.color = "var(--text3)";
        if (comparison.best_streak && comparison.best_streak.length > 0) {
          activeCompare.innerHTML = "Melhor: " + comparison.best_streak.length + " dias (" + comparison.best_streak.start + " a " + comparison.best_streak.end + ")";
        } else {
          activeCompare.textContent = "Sem recorde";
        }
      }
      if (activeDelta) {
        activeDelta.style.display = "none";
        activeDelta.textContent = "";
      }
    } else {
      if (activeCompare) {
        activeCompare.style.color = "";
        if (comparison.active_days && comparison.active_days.pct != null) {
          activeCompare.innerHTML = '<span class="pct ' + pctClass(comparison.active_days.pct) + '">' + (comparison.active_days.pct > 0 ? "+" : "") + comparison.active_days.pct + '%</span><span>vs. ' + comparison.active_days.a + ' no período anterior</span>';
        } else {
          activeCompare.textContent = "";
        }
      }
      if (activeDelta) {
        activeDelta.style.display = "";
        activeDelta.textContent = (comparison.sessions ? comparison.sessions.b : 0) + " sessões";
      }
    }

    if (extraValue) {
      extraValue.textContent = "+" + ((comparison.extraordinary && comparison.extraordinary.cycles) ? comparison.extraordinary.cycles.b : 0);
    }

    if (extraCompare) {
      if (comparison.extraordinary && comparison.extraordinary.cycles && comparison.extraordinary.cycles.pct != null) {
        extraCompare.innerHTML = '<span class="pct ' + pctClass(comparison.extraordinary.cycles.pct) + '">' + (comparison.extraordinary.cycles.pct > 0 ? "+" : "") + comparison.extraordinary.cycles.pct + '%</span><span>vs. +' + comparison.extraordinary.cycles.a + ' no período anterior</span>';
      } else {
        extraCompare.textContent = "";
      }
    }

    if (extraDelta) {
      extraDelta.textContent = (comparison.extraordinary && comparison.extraordinary.minutes ? comparison.extraordinary.minutes.b : 0) + " min";
    }

    saveSummaryScale(scale);
  }

  if (summaryData[activeSummaryScale]) {
    applySummaryScale(activeSummaryScale);
  }

  summaryButtons.forEach(function(button) {
    button.addEventListener("click", function() {
      var scale = button.getAttribute("data-summary-scale");
      if (scale && summaryData[scale]) {
        saveSummaryScale(scale);
      }
    });
  });

  if (topStrip && monthLabels) {
    topStrip.addEventListener("mouseenter", function() {
      monthLabels.classList.add("visible");
    });
    topStrip.addEventListener("mouseleave", function(e) {
      // Don't hide if mouse moved to the labels themselves
      if (!monthLabels.contains(e.relatedTarget)) {
        monthLabels.classList.remove("visible");
      }
    });
    monthLabels.addEventListener("mouseleave", function(e) {
      // Hide when leaving the labels area (unless going back to strip)
      if (!topStrip.contains(e.relatedTarget)) {
        monthLabels.classList.remove("visible");
      }
    });
  }

  if (leftStrip && weekLabels) {
    leftStrip.addEventListener("mouseenter", function() {
      weekLabels.classList.add("visible");
    });
    leftStrip.addEventListener("mouseleave", function() {
      weekLabels.classList.remove("visible");
    });
  }

  // ─── Scroll Preservation ───────────────────────────────────────────────────
  // Save scroll position before any internal navigation so the page doesn't
  // jump back to the top when switching tabs, filters, periods or calendar cells.
  var SCROLL_KEY = "foco_stats_scroll_v1";
  var SCROLL_ORIGIN_KEY = "foco_stats_scroll_origin_v1";
  var currentPath = window.location.pathname;

  // Restore scroll if we navigated from the same stats page
  try {
    var savedScroll = sessionStorage.getItem(SCROLL_KEY);
    var savedOrigin = sessionStorage.getItem(SCROLL_ORIGIN_KEY);
    if (savedScroll !== null && savedOrigin === currentPath) {
      var targetY = parseInt(savedScroll, 10);
      // Small timeout ensures the DOM is fully painted before scrolling
      setTimeout(function() { window.scrollTo({ top: targetY, behavior: "instant" }); }, 0);
    }
    sessionStorage.removeItem(SCROLL_KEY);
    sessionStorage.removeItem(SCROLL_ORIGIN_KEY);
  } catch (e) {}

  function saveScroll() {
    try {
      sessionStorage.setItem(SCROLL_KEY, String(window.scrollY));
      sessionStorage.setItem(SCROLL_ORIGIN_KEY, currentPath);
    } catch (e) {}
  }

  // Intercept <a href> clicks that stay on the stats page
  document.addEventListener("click", function(e) {
    var anchor = e.target.closest("a");
    if (anchor && anchor.href && anchor.href.indexOf(currentPath) !== -1) {
      saveScroll();
    }
  }, true);

  // Intercept onclick="window.location.href='...'" calls on non-anchor elements
  // by saving scroll on any click on an element that has an onclick handler
  // pointing to the same path (cal cells, week handles, month labels)
  document.addEventListener("click", function(e) {
    var el = e.target.closest("[onclick]");
    if (el) {
      var attr = el.getAttribute("onclick") || "";
      if (attr.indexOf(currentPath) !== -1) {
        saveScroll();
      }
    }
  }, true);
  // ───────────────────────────────────────────────────────────────────────────
});
