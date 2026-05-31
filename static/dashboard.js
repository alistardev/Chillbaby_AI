/**
 * Phase 7 — Caregiver dashboard (consumes /api/dashboard/*).
 */
(function () {
  "use strict";

  var state = {
    tab: "overview",
    since: "",
    until: "",
    autoRefresh: false,
    refreshTimer: null,
  };

  var TAB_ENDPOINTS = {
    overview: "/api/dashboard/overview",
    meals: "/api/dashboard/meal-sessions?limit=100",
    food: "/api/dashboard/food-diary-entries?limit=150",
    allergens: "/api/dashboard/allergen-logs?limit=150",
    status: "/api/dashboard/child-status-events?limit=150",
  };

  function $(id) {
    return document.getElementById(id);
  }

  /** Scrollable inner region of a tab panel (not the whole page). */
  function panelBody(panelId) {
    var panel = $(panelId);
    if (!panel) return null;
    return panel.querySelector(".panel-scroll") || panel;
  }

  function panelScrollEl(panelId) {
    var panel = $(panelId);
    return panel ? panel.querySelector(".panel-scroll") : null;
  }

  function setPanelScrollMode(panelId) {
    document.querySelectorAll(".panel-scroll").forEach(function (el) {
      el.classList.remove("panel-scroll--overview");
    });
    var scroll = panelScrollEl(panelId);
    if (scroll && panelId === "panelOverview") {
      scroll.classList.add("panel-scroll--overview");
    }
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function fmtDt(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (e) {
      return esc(iso);
    }
  }

  function fmtDuration(sec) {
    if (sec == null || sec === "") return "—";
    var n = Number(sec);
    if (isNaN(n) || n < 0) return "—";
    if (n < 60) return n + "s";
    var m = Math.floor(n / 60);
    var s = n % 60;
    if (m < 60) return m + "m " + s + "s";
    var h = Math.floor(m / 60);
    m = m % 60;
    return h + "h " + m + "m";
  }

  function fmtPct(v) {
    if (v == null || v === "") return "—";
    var n = Number(v);
    if (isNaN(n)) return "—";
    if (n >= 0 && n <= 1.001) return Math.round(n * 100) + "%";
    return Math.round(n) + "%";
  }

  function childLabel(snap) {
    if (!snap || typeof snap !== "object") return "—";
    return esc(snap.name || "—");
  }

  function querySuffix(extra) {
    var p = new URLSearchParams(extra || "");
    if (state.since) {
      p.set("since", new Date(state.since).toISOString());
    }
    if (state.until) {
      p.set("until", new Date(state.until).toISOString());
    }
    var qs = p.toString();
    return qs ? (qs.indexOf("?") === 0 ? qs : "?" + qs) : "";
  }

  function buildUrl(base) {
    var q = base.indexOf("?");
    if (q === -1) return base + querySuffix();
    return base.slice(0, q) + querySuffix(new URLSearchParams(base.slice(q + 1)));
  }

  function fetchJson(base) {
    return fetch(buildUrl(base))
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
  }

  function setLoading(panelId, msg) {
    setPanelScrollMode(panelId);
    var el = panelBody(panelId);
    if (el) el.innerHTML = '<div class="dash-loading">' + esc(msg || "Loading…") + "</div>";
  }

  function setError(panelId, err) {
    var el = panelBody(panelId);
    if (el) {
      el.innerHTML =
        '<div class="dash-error">Could not load data. ' + esc(err.message || String(err)) + "</div>";
    }
  }

  function renderOverview(data) {
    setPanelScrollMode("panelOverview");
    var cards = [
      { label: "Meal sessions", value: data.meal_sessions_total, icon: "🍽️", tone: "teal" },
      { label: "Active now", value: data.meal_sessions_active, icon: "▶️", tone: "green" },
      { label: "Cough events", value: data.cough_events, icon: "😷", tone: "orange" },
      { label: "Sneeze events", value: data.sneeze_events, icon: "🤧", tone: "yellow" },
      { label: "Allergen alerts", value: data.allergen_alerts, icon: "🚨", tone: "red" },
    ];
    panelBody("panelOverview").innerHTML =
      '<div class="stat-grid">' +
      cards
        .map(function (c) {
          return (
            '<div class="stat-card stat-' +
            c.tone +
            '">' +
            '<span class="stat-icon">' +
            c.icon +
            "</span>" +
            '<div class="stat-body">' +
            '<div class="stat-value">' +
            esc(c.value != null ? c.value : "0") +
            "</div>" +
            '<div class="stat-label">' +
            esc(c.label) +
            "</div></div></div>"
          );
        })
        .join("") +
      "</div>" +
      '<p class="dash-hint">Counts respect the date range above. Use tabs for detailed logs.</p>';
  }

  function tableWrap(headers, rowsHtml, emptyMsg) {
    if (!rowsHtml) {
      return '<div class="dash-empty">' + esc(emptyMsg || "No records in this range.") + "</div>";
    }
    var headRow = headers
      .map(function (h) {
        return "<th>" + esc(h) + "</th>";
      })
      .join("");
    return (
      '<div class="dash-table-frame">' +
      '<div class="dash-table-head">' +
      '<table class="dash-table"><thead><tr>' +
      headRow +
      "</tr></thead></table></div>" +
      '<div class="dash-table-body-scroll">' +
      '<table class="dash-table"><tbody>' +
      rowsHtml +
      "</tbody></table></div></div>"
    );
  }

  function renderMeals(items) {
    setPanelScrollMode("panelMeals");
    var rows = (items || [])
      .map(function (it) {
        var status = (it.status || "—").toLowerCase();
        var badge =
          status === "active"
            ? '<span class="badge badge-active">active</span>'
            : '<span class="badge badge-ended">' + esc(status) + "</span>";
        return (
          "<tr>" +
          "<td>" + fmtDt(it.started_at) + "</td>" +
          "<td>" + fmtDt(it.ended_at) + "</td>" +
          "<td>" + badge + "</td>" +
          "<td>" + fmtDuration(it.duration_seconds) + "</td>" +
          "<td>" + childLabel(it.child_snapshot) + "</td>" +
          "<td>" + esc(it.location_label_snapshot || "—") + "</td>" +
          "</tr>"
        );
      })
      .join("");
    panelBody("panelMeals").innerHTML = tableWrap(
      ["Started", "Ended", "Status", "Duration", "Child", "Location"],
      rows
    );
  }

  function renderFood(items) {
    setPanelScrollMode("panelFood");
    var rows = (items || [])
      .map(function (it) {
        var allergens = (it.allergens_served || []).join(", ") || "—";
        var sources = (it.detection_sources || []).join(", ") || "—";
        var cal = it.nutrition && it.nutrition.calories != null ? it.nutrition.calories : "—";
        var allergenCell =
          allergens !== "—"
            ? '<span class="badge badge-alert">' + esc(allergens) + "</span>"
            : '<span class="badge badge-clear">clear</span>';
        return (
          "<tr>" +
          "<td>" + fmtDt(it.detected_at) + "</td>" +
          "<td><strong>" + esc(it.food_name || "—") + "</strong></td>" +
          "<td>" + fmtPct(it.confidence) + "</td>" +
          "<td>" + allergenCell + "</td>" +
          "<td>" + esc(cal) + "</td>" +
          "<td>" + esc(sources) + "</td>" +
          "</tr>"
        );
      })
      .join("");
    panelBody("panelFood").innerHTML = tableWrap(
      ["Detected", "Food", "Confidence", "Allergens", "Calories", "Sources"],
      rows
    );
  }

  function renderAllergens(items) {
    setPanelScrollMode("panelAllergens");
    var rows = (items || [])
      .map(function (it) {
        var detected = it.status === "detected" || it.alert_triggered;
        var names = (it.matched_allergen_names || []).join(", ") || "—";
        return (
          "<tr>" +
          "<td>" + fmtDt(it.checked_at) + "</td>" +
          "<td><strong>" + esc(it.food_name || "—") + "</strong></td>" +
          "<td>" +
          (detected
            ? '<span class="badge badge-alert">⚠ detected</span>'
            : '<span class="badge badge-clear">✓ clear</span>') +
          "</td>" +
          "<td>" + esc(names) + "</td>" +
          "</tr>"
        );
      })
      .join("");
    panelBody("panelAllergens").innerHTML = tableWrap(
      ["Checked", "Food", "Result", "Matched allergens"],
      rows
    );
  }

  function renderStatus(items) {
    setPanelScrollMode("panelStatus");
    var rows = (items || [])
      .map(function (it) {
        var meta = it.metadata || {};
        var detail = meta.emotion || meta.severity_label || meta.label || "";
        if (!detail && it.event_type === "child_absent") detail = "not in frame";
        if (!detail && it.event_type === "child_present") detail = "in frame";
        return (
          "<tr>" +
          "<td>" + fmtDt(it.event_timestamp) + "</td>" +
          "<td><span class=\"badge badge-type\">" + esc(it.event_type || "—") + "</span></td>" +
          "<td>" + fmtPct(it.confidence) + "</td>" +
          "<td>" + esc(detail || "—") + "</td>" +
          "<td>" + esc(it.location_label_snapshot || "—") + "</td>" +
          "</tr>"
        );
      })
      .join("");
    panelBody("panelStatus").innerHTML = tableWrap(
      ["Time", "Event", "Confidence", "Detail", "Location"],
      rows
    );
  }

  function loadTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".dash-tab").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    document.querySelectorAll(".dash-panel").forEach(function (panel) {
      var on = panel.id === "panel" + tab.charAt(0).toUpperCase() + tab.slice(1);
      panel.classList.toggle("active", on);
      if (on) {
        var scroll = panel.querySelector(".panel-scroll");
        if (scroll) scroll.scrollTop = 0;
      }
    });

    var panelMap = {
      overview: "panelOverview",
      meals: "panelMeals",
      food: "panelFood",
      allergens: "panelAllergens",
      status: "panelStatus",
    };
    var panelId = panelMap[tab];
    if (!panelId) return;

    setLoading(panelId);
    var url = TAB_ENDPOINTS[tab];
    fetchJson(url)
      .then(function (data) {
        if (tab === "overview") renderOverview(data);
        else if (tab === "meals") renderMeals(data.items);
        else if (tab === "food") renderFood(data.items);
        else if (tab === "allergens") renderAllergens(data.items);
        else if (tab === "status") renderStatus(data.items);
        $("lastUpdated").textContent = "Updated " + new Date().toLocaleTimeString();
      })
      .catch(function (err) {
        setError(panelId, err);
      });
  }

  function readFilters() {
    state.since = $("filterSince").value || "";
    state.until = $("filterUntil").value || "";
  }

  function applyFilters() {
    readFilters();
    loadTab(state.tab);
  }

  function defaultDateRange() {
    var until = new Date();
    var since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
    function localInput(d) {
      var pad = function (n) {
        return String(n).padStart(2, "0");
      };
      return (
        d.getFullYear() +
        "-" +
        pad(d.getMonth() + 1) +
        "-" +
        pad(d.getDate()) +
        "T" +
        pad(d.getHours()) +
        ":" +
        pad(d.getMinutes())
      );
    }
    $("filterSince").value = localInput(since);
    $("filterUntil").value = localInput(until);
    readFilters();
  }

  function toggleAutoRefresh(on) {
    state.autoRefresh = on;
    if (state.refreshTimer) {
      clearInterval(state.refreshTimer);
      state.refreshTimer = null;
    }
    if (on) {
      state.refreshTimer = setInterval(function () {
        applyFilters();
      }, 30000);
    }
  }

  document.querySelectorAll(".dash-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      loadTab(btn.dataset.tab);
    });
  });

  $("btnApplyFilters").addEventListener("click", applyFilters);
  $("btnClearFilters").addEventListener("click", function () {
    $("filterSince").value = "";
    $("filterUntil").value = "";
    readFilters();
    loadTab(state.tab);
  });
  $("autoRefresh").addEventListener("change", function () {
    toggleAutoRefresh(this.checked);
  });

  defaultDateRange();
  loadTab("overview");
})();
