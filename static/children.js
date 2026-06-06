(function () {
  "use strict";

  var _children = [];
  var _allergens = [];
  var _selectedAllergies = new Set();

  function $(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function allergenKey(id) {
    return String(id);
  }

  function formatAge(months) {
    if (months == null || months === "") return "—";
    var m = Number(months);
    if (isNaN(m)) return "—";
    var y = Math.floor(m / 12);
    var rem = m % 12;
    if (y <= 0) return m + " mo";
    if (rem === 0) return y + " yr";
    return y + " yr " + rem + " mo";
  }

  function formatSex(sex) {
    if (!sex) return "—";
    return sex.charAt(0).toUpperCase() + sex.slice(1);
  }

  function loadAllergens() {
    return fetch("/api/dashboard/master-allergens?active=true&limit=200")
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        _allergens = (data.items || []).map(function (item) {
          return { id: allergenKey(item._id), name: item.name };
        });
        _allergens.sort(function (a, b) {
          return a.name.localeCompare(b.name);
        });
        renderAllergenPills();
      })
      .catch(function () {
        var container = $("editAllergenPills");
        if (container) {
          container.innerHTML =
            '<span class="pill-loading" style="color:#dc2626;">Could not load allergens — is the server running?</span>';
        }
      });
  }

  function loadChildren() {
    return fetch("/api/children?active=true&limit=200", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        _children = data.items || [];
        renderList();
      });
  }

  function renderList() {
    var list = $("childList");
    var setupMode = !!window.__CAMMY_CHILDREN_SETUP__;
    var continueLink = $("linkContinue");
    if (continueLink && setupMode) {
      continueLink.style.display = _children.length ? "inline-block" : "none";
    }
    if (!_children.length) {
      list.innerHTML =
        '<div class="card empty-state">No saved profiles yet. Fill in the form above and click <strong>Save profile</strong>.</div>';
      return;
    }
    list.innerHTML = _children
      .map(function (c) {
        var names = c.allergy_names || [];
        var tags = names.length
          ? names
              .map(function (n) {
                return '<span class="tag">' + esc(n) + "</span>";
              })
              .join("")
          : '<span class="tag empty">No allergies set — edit to add Wheat, Milk, etc.</span>';
        return (
          '<div class="card" data-id="' +
          esc(c._id) +
          '">' +
          '<div class="child-row">' +
          "<div>" +
          '<div class="child-name">' +
          esc(c.name) +
          "</div>" +
          '<div class="child-meta">' +
          esc(formatAge(c.age_months)) +
          " · " +
          esc(formatSex(c.sex)) +
          "</div>" +
          '<div class="allergy-label">Allergies</div>' +
          '<div class="allergy-tags">' +
          tags +
          "</div></div>" +
          '<div class="row-actions">' +
          '<button type="button" class="primary" data-action="edit" data-id="' +
          esc(c._id) +
          '">Edit &amp; allergies</button>' +
          '<button type="button" class="danger" data-action="delete" data-id="' +
          esc(c._id) +
          '">Remove</button>' +
          "</div></div></div>"
        );
      })
      .join("");
  }

  function renderAllergenPills() {
    var container = $("editAllergenPills");
    if (!container) return;
    if (!_allergens.length) {
      container.innerHTML =
        '<span class="pill-loading">No allergens in database yet — add a custom one below.</span>';
      return;
    }
    container.innerHTML = _allergens
      .map(function (a) {
        var active = _selectedAllergies.has(a.id) ? " active" : "";
        return (
          '<span class="pill' +
          active +
          '" data-id="' +
          esc(a.id) +
          '">' +
          esc(a.name) +
          "</span>"
        );
      })
      .join("");
    container.querySelectorAll(".pill").forEach(function (pill) {
      pill.addEventListener("click", function () {
        var id = allergenKey(pill.dataset.id);
        if (_selectedAllergies.has(id)) _selectedAllergies.delete(id);
        else _selectedAllergies.add(id);
        pill.classList.toggle("active");
      });
    });
  }

  function resetForm() {
    $("editChildId").value = "";
    $("editName").value = "";
    $("editAgeYears").value = "";
    $("editSex").value = "";
    $("editError").style.display = "none";
    $("formTitle").textContent = "Add child profile";
    $("btnCancelEdit").style.display = "none";
    _selectedAllergies = new Set();
    renderAllergenPills();
    $("childFormCard").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function loadFormFromChild(child) {
    $("editError").style.display = "none";
    $("formTitle").textContent = "Edit: " + child.name;
    $("btnCancelEdit").style.display = "inline-block";
    $("editChildId").value = child._id;
    $("editName").value = child.name || "";
    if (child.age_months != null) {
      $("editAgeYears").value = Math.floor(Number(child.age_months) / 12) || "";
    } else {
      $("editAgeYears").value = "";
    }
    $("editSex").value = child.sex || "";
    _selectedAllergies = new Set();
    if (child.allergy_ids) {
      child.allergy_ids.forEach(function (id) {
        _selectedAllergies.add(allergenKey(id));
      });
    }
    renderAllergenPills();
    $("childFormCard").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function saveChild() {
    var name = $("editName").value.trim();
    var err = $("editError");
    if (!name) {
      err.textContent = "Child name is required.";
      err.style.display = "block";
      $("editName").focus();
      return;
    }
    var years = parseInt($("editAgeYears").value, 10);
    var ageMonths = isNaN(years) || years < 0 ? null : years * 12;
    var body = {
      name: name,
      age_months: ageMonths,
      sex: $("editSex").value || null,
      allergy_ids: Array.from(_selectedAllergies),
    };
    var id = $("editChildId").value;
    var url = id ? "/api/children/" + id : "/api/children";
    var method = id ? "PATCH" : "POST";

    $("btnSaveChild").disabled = true;
    fetch(url, {
      method: method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        if (!r.ok) return r.text().then(function (t) { throw new Error(t || "Save failed"); });
        return r.json();
      })
      .then(function () {
        resetForm();
        return loadChildren().then(function () {
          if (window.__CAMMY_CHILDREN_SETUP__ && _children.length === 1) {
            window.location.href = "/select-child";
          }
        });
      })
      .catch(function (e) {
        err.textContent = e.message || "Could not save profile.";
        err.style.display = "block";
      })
      .finally(function () {
        $("btnSaveChild").disabled = false;
      });
  }

  function deleteChild(id, name) {
    if (!confirm('Remove profile for "' + name + '"? (Soft-delete — history is kept.)')) return;
    fetch("/api/children/" + id, { method: "DELETE", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("Delete failed");
        return loadChildren();
      })
      .catch(function () {
        alert("Could not remove child profile.");
      });
  }

  function addCustomAllergen() {
    var input = $("customAllergenInput");
    var name = input.value.trim();
    if (!name) {
      input.focus();
      return;
    }
    var btn = $("customAllergenBtn");
    btn.disabled = true;
    btn.textContent = "…";
    fetch("/api/allergens", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, category: "custom" }),
    })
      .then(function (r) {
        if (r.status === 409) {
          return r.json().then(function () {
            var existing = _allergens.find(function (a) {
              return a.name.toLowerCase() === name.toLowerCase();
            });
            if (existing) _selectedAllergies.add(existing.id);
            return loadAllergens();
          });
        }
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        if (d && d.id) {
          var key = allergenKey(d.id);
          if (!_allergens.some(function (a) { return a.id === key; })) {
            _allergens.push({ id: key, name: d.name || name });
            _allergens.sort(function (a, b) { return a.name.localeCompare(b.name); });
          }
          _selectedAllergies.add(key);
          renderAllergenPills();
        }
        input.value = "";
      })
      .catch(function (e) {
        alert("Could not add allergen: " + e.message);
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "+ Add";
      });
  }

  $("btnSaveChild").addEventListener("click", saveChild);
  $("btnCancelEdit").addEventListener("click", resetForm);
  $("customAllergenBtn").addEventListener("click", addCustomAllergen);
  $("customAllergenInput").addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      addCustomAllergen();
    }
  });

  $("childList").addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-action]");
    if (!btn) return;
    var id = btn.dataset.id;
    var child = _children.find(function (c) { return String(c._id) === id; });
    if (!child) return;
    if (btn.dataset.action === "edit") loadFormFromChild(child);
    if (btn.dataset.action === "delete") deleteChild(id, child.name);
  });

  loadAllergens()
    .then(loadChildren)
    .then(function () {
      var q = new URLSearchParams(window.location.search);
      var editId = q.get("edit");
      if (!editId) return;
      var child = _children.find(function (c) { return String(c._id) === editId; });
      if (child) loadFormFromChild(child);
    });
})();
