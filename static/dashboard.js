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
    testers: "/api/dashboard/testers?limit=200",
    feedback: "/api/testing-results?limit=200",
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

  var EMO_ICONS = {
    happy: "😊",
    neutral: "😐",
    sad: "😢",
    surprise: "😲",
    angry: "😠",
    disgust: "🤢",
    fear: "😨",
    excited: "✨",
    worried: "😟",
    tense: "😤",
  };

  function emotionPct(value) {
    var n = Number(value);
    if (isNaN(n) || n <= 0) return 0;
    if (n > 0 && n <= 1.001) return Math.round(n * 100);
    return Math.round(n);
  }

  function emotionScoresList(meta) {
    var scores = (meta && meta.emotion_scores) || {};
    var skip = { _state: 1, _cleared: 1 };
    var items = [];
    Object.keys(scores).forEach(function (k) {
      if (skip[k]) return;
      var pct = emotionPct(scores[k]);
      if (pct > 0) items.push({ key: k, pct: pct });
    });
    items.sort(function (a, b) {
      return b.pct - a.pct;
    });
    if (!items.length && meta && meta.dominant_emotion) {
      var domPct = emotionPct(
        scores[meta.dominant_emotion] != null ? scores[meta.dominant_emotion] : meta.confidence
      );
      if (domPct > 0) {
        items.push({ key: meta.dominant_emotion, pct: domPct });
      }
    }
    return items;
  }

  function renderEmotionChips(meta, dominantKey) {
    var items = emotionScoresList(meta);
    if (!items.length) return "—";
    var dom = (dominantKey || (meta && meta.dominant_emotion) || items[0].key || "").toLowerCase();
    return (
      '<div class="emo-chips">' +
      items
        .slice(0, 6)
        .map(function (item) {
          var icon = EMO_ICONS[item.key] || "🙂";
          var cls = item.key === dom ? "emo-chip emo-chip-dominant" : "emo-chip";
          return '<span class="' + cls + '">' + icon + " " + item.pct + "%</span>";
        })
        .join("") +
      "</div>"
    );
  }

  function statusDetailCell(it) {
    var meta = it.metadata || {};
    var t = (it.event_type || "").toLowerCase();
    if (t === "emotion") return "—";
    if (meta.severity_label) return esc(meta.severity_label);
    if (t === "child_absent") return "not in frame";
    if (t === "child_present") return "in frame";
    if (meta.label) return esc(meta.label);
    if (meta.status) return esc(meta.status);
    return "—";
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

  var ADMIN_MODE = window.__CAMMY_DASHBOARD_ADMIN__ === true;
  var DEFAULT_TAB = ADMIN_MODE ? "testers" : "overview";

  function fetchJson(base) {
    return fetch(buildUrl(base), { credentials: "same-origin" })
      .then(function (r) {
        if (r.status === 401) {
          if (ADMIN_MODE) {
            window.location.href = "/admin/login?next=" + encodeURIComponent("/admin/dashboard");
          } else {
            window.location.href = "/";
          }
          throw new Error("Sign-in required");
        }
        if (r.status === 403) {
          throw new Error("Admin access required — open /admin/dashboard and sign in again.");
        }
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
    var cards = [];
    if (ADMIN_MODE) {
      cards.push(
        { label: "Registered testers", value: data.testers_total, icon: "👥", tone: "teal" },
        { label: "Feedback submissions", value: data.feedback_total, icon: "💬", tone: "green" }
      );
    }
    cards = cards.concat([
      { label: "Meal sessions", value: data.meal_sessions_total, icon: "🍽️", tone: "teal" },
      { label: "Active now", value: data.meal_sessions_active, icon: "▶️", tone: "green" },
      { label: "Cough events", value: data.cough_events, icon: "😷", tone: "orange" },
      { label: "Sneeze events", value: data.sneeze_events, icon: "🤧", tone: "yellow" },
      { label: "Allergen alerts", value: data.allergen_alerts, icon: "🚨", tone: "red" },
    ]);
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
      '<p class="dash-hint">' +
      (ADMIN_MODE
        ? "All testers — use the Testers and Feedback tabs for management. Other counts respect the date range above."
        : "Counts respect the date range above. Use tabs for detailed logs.") +
      "</p>";
  }

  function renderTesters(items) {
    var body = panelBody("panelTesters");
    if (!body) return;
    setPanelScrollMode("panelTesters");
    var rows = (items || [])
      .map(function (it) {
        return (
          "<tr>" +
          "<td><strong>" + esc(it.name || "—") + "</strong></td>" +
          "<td>" + esc(it.email || "—") + "</td>" +
          "<td>" + esc(it.company || "—") + "</td>" +
          "<td>" +
          (it.consent_given
            ? '<span class="badge badge-clear">yes</span>'
            : '<span class="badge badge-ended">no</span>') +
          "</td>" +
          "<td>" + fmtDt(it.created_at) + "</td>" +
          "<td>" + fmtDt(it.updated_at) + "</td>" +
          "</tr>"
        );
      })
      .join("");
    body.innerHTML = tableWrap(
      ["Name", "Email", "Company", "Consent", "Joined", "Last seen"],
      rows,
      "No testers registered yet."
    );
  }

  function renderFeedback(items) {
    var body = panelBody("panelFeedback");
    if (!body) return;
    setPanelScrollMode("panelFeedback");
    var rows = (items || [])
      .map(function (it) {
        var ratings = [
          it.overall_rating != null ? "overall " + it.overall_rating : "",
          it.food_accuracy_rating != null ? "food " + it.food_accuracy_rating : "",
          it.emotion_accuracy_rating != null ? "emotion " + it.emotion_accuracy_rating : "",
          it.audio_accuracy_rating != null ? "audio " + it.audio_accuracy_rating : "",
        ]
          .filter(Boolean)
          .join(" · ");
        return (
          "<tr>" +
          "<td>" + fmtDt(it.created_at) + "</td>" +
          "<td><strong>" + esc(it.name || "—") + "</strong></td>" +
          "<td>" + esc(it.email || "—") + "</td>" +
          "<td>" + esc(ratings || "—") + "</td>" +
          "<td>" + esc(it.notes || "—") + "</td>" +
          "<td>" + esc(it.device || it.browser || "—") + "</td>" +
          "</tr>"
        );
      })
      .join("");
    body.innerHTML = tableWrap(
      ["Submitted", "Name", "Email", "Ratings", "Notes", "Device"],
      rows,
      "No feedback submitted yet."
    );
  }

  function adminTesterHeaders() {
    return ADMIN_MODE ? ["Tester name", "Tester email"] : [];
  }

  function adminTesterCells(it) {
    if (!ADMIN_MODE) return "";
    return (
      "<td>" + esc(it.tester_name || it.parent_name || "—") + "</td>" +
      "<td>" + esc(it.email || "—") + "</td>"
    );
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
          adminTesterCells(it) +
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
      adminTesterHeaders().concat(["Started", "Ended", "Status", "Duration", "Child", "Location"]),
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
          adminTesterCells(it) +
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
      adminTesterHeaders().concat(["Detected", "Food", "Confidence", "Allergens", "Calories", "Sources"]),
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
          adminTesterCells(it) +
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
      adminTesterHeaders().concat(["Checked", "Food", "Result", "Matched allergens"]),
      rows
    );
  }

  function renderStatus(items) {
    setPanelScrollMode("panelStatus");
    var rows = (items || [])
      .map(function (it) {
        var meta = it.metadata || {};
        var isEmotion = (it.event_type || "").toLowerCase() === "emotion";
        return (
          "<tr>" +
          adminTesterCells(it) +
          "<td>" + fmtDt(it.event_timestamp) + "</td>" +
          "<td><span class=\"badge badge-type\">" + esc(it.event_type || "—") + "</span></td>" +
          "<td>" + fmtPct(it.confidence) + "</td>" +
          "<td>" + statusDetailCell(it) + "</td>" +
          "<td>" +
          (isEmotion ? renderEmotionChips(meta, meta.dominant_emotion) : "—") +
          "</td>" +
          "</tr>"
        );
      })
      .join("");
    panelBody("panelStatus").innerHTML = tableWrap(
      adminTesterHeaders().concat(["Time", "Event", "Confidence", "Detail", "Emotions"]),
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
      testers: "panelTesters",
      feedback: "panelFeedback",
      meals: "panelMeals",
      food: "panelFood",
      allergens: "panelAllergens",
      status: "panelStatus",
    };
    var panelId = panelMap[tab];
    if (!panelId || !$(panelId)) return;

    setLoading(panelId);
    var url = TAB_ENDPOINTS[tab];
    if (!url) return;
    fetchJson(url)
      .then(function (data) {
        if (tab === "overview") renderOverview(data);
        else if (tab === "testers") renderTesters(data.items);
        else if (tab === "feedback") renderFeedback(data.items);
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
  loadTab(DEFAULT_TAB);
})();
