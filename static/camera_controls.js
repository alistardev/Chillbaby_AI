/**
 * Camera start/stop controls for process.html (loaded after detail.js).
 */
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function hasLiveCameraStream() {
    var vid = $("webcam");
    if (!vid || !vid.srcObject) return false;
    return vid.srcObject.getTracks().some(function (t) {
      return t.readyState === "live";
    });
  }

  function updateCameraButtonState(isActive) {
    var startBtn = $("startCamBtn");
    var stopBtn = $("stopCamBtn");
    var badge = $("badgeTracking");
    if (!startBtn || !stopBtn) return;
    if (isActive === "connecting") {
      window.__cammy_camera_connecting = true;
      startBtn.disabled = true;
      stopBtn.disabled = true;
      if (badge) {
        badge.className = "cam-badge grey";
        badge.innerHTML = '<span class="dot"></span> Starting camera…';
      }
      return;
    }
    window.__cammy_camera_connecting = false;
    startBtn.disabled = !!isActive;
    stopBtn.disabled = !isActive;
    if (badge) {
      if (isActive) {
        badge.className = "cam-badge teal";
        badge.innerHTML = '<span class="dot"></span> Tracking active';
      } else {
        badge.className = "cam-badge grey";
        badge.innerHTML = '<span class="dot"></span> Camera off';
      }
    }
  }

  function stopCameraTracks(opts) {
    opts = opts || {};
    if (typeof pauseCameraOnly === "function") {
      pauseCameraOnly();
    } else {
      if (typeof stopStream === "function") stopStream();
      var vid = $("webcam");
      if (vid && vid.srcObject) {
        vid.srcObject.getTracks().forEach(function (t) {
          t.stop();
        });
        vid.srcObject = null;
      }
    }
    if (!opts.pauseOnly && typeof stopProcessing === "function") stopProcessing();
    if (!opts.pauseOnly) {
      if (window.CammyFace && typeof window.CammyFace.stop === "function") {
        window.CammyFace.stop();
      } else if (typeof stopFaceDetection === "function") {
        stopFaceDetection();
      }
    }
    updateCameraButtonState(false);
  }

  function cammyStartCamera(ev) {
    if (ev && ev.preventDefault) ev.preventDefault();
    if (hasLiveCameraStream()) return;
    var modal = $("micConsentModal");
    if (!modal) {
      console.error("[cammy] micConsentModal not found");
      return;
    }
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
  }

  function dismissMicConsent(allow) {
    var modal = $("micConsentModal");
    if (modal) {
      modal.classList.remove("open");
      modal.setAttribute("aria-hidden", "true");
    }
    if (!allow) return;
    cammyBeginCameraAfterConsent();
  }

  function cammyBeginCameraAfterConsent() {
    if (typeof startStream !== "function") {
      console.error("[cammy] startStream missing — is detail.js loaded?");
      alert("Camera module failed to load. Refresh the page and try again.");
      updateCameraButtonState(false);
      return;
    }
    updateCameraButtonState("connecting");
    startStream({
      beforeNegotiate: function () {
        if (typeof startProcessing === "function") startProcessing();
      },
      after: function () {
        try {
          sessionStorage.setItem("cammy_monitoring_active", "1");
          sessionStorage.removeItem("cammy_paused_for_navigation");
        } catch (e) {}
        var resumeBar = $("resumeMonitoringBar");
        if (resumeBar) resumeBar.style.display = "none";
        updateCameraButtonState(true);
        if (window.CammyFace && typeof window.CammyFace.start === "function") {
          window.CammyFace.start();
        } else if (typeof window.ensureFaceDetectionWhenReady === "function") {
          window.ensureFaceDetectionWhenReady();
        }
      },
    });
  }

  function cammyStopCamera(ev) {
    if (ev && ev.preventDefault) ev.preventDefault();
    try {
      sessionStorage.removeItem("cammy_monitoring_active");
      sessionStorage.removeItem("cammy_paused_for_navigation");
    } catch (e) {}
    stopCameraTracks({ pauseOnly: false });
    var resumeBar = $("resumeMonitoringBar");
    if (resumeBar) resumeBar.style.display = "none";
  }

  function navigateToDashboard(event) {
    if (event && event.preventDefault) event.preventDefault();
    try {
      if (hasLiveCameraStream() || sessionStorage.getItem("cammy_monitoring_active") === "1") {
        sessionStorage.setItem("cammy_monitoring_active", "1");
        sessionStorage.setItem("cammy_paused_for_navigation", "1");
      }
    } catch (e) {}
    stopCameraTracks({ pauseOnly: true });
    window.location.href = "/dashboard";
  }

  function syncResumeBar() {
    if (window.__cammy_camera_connecting) return;
    var bar = $("resumeMonitoringBar");
    if (!bar) return;
    try {
      var wasMonitoring = sessionStorage.getItem("cammy_monitoring_active") === "1";
      var pausedNav = sessionStorage.getItem("cammy_paused_for_navigation") === "1";
      if (wasMonitoring && pausedNav && !hasLiveCameraStream()) {
        bar.style.display = "flex";
        updateCameraButtonState(false);
        return;
      }
      bar.style.display = "none";
      if (!hasLiveCameraStream()) {
        sessionStorage.removeItem("cammy_monitoring_active");
        sessionStorage.removeItem("cammy_paused_for_navigation");
      }
    } catch (e) {
      bar.style.display = "none";
    }
    updateCameraButtonState(hasLiveCameraStream());
  }

  window.cammyStartCamera = cammyStartCamera;
  window.cammyStopCamera = cammyStopCamera;
  window.cammyBeginCameraAfterConsent = cammyBeginCameraAfterConsent;
  window.dismissMicConsent = dismissMicConsent;
  window.cammyUpdateCameraButtonState = updateCameraButtonState;
  window.cammyNavigateToDashboard = navigateToDashboard;

  window.__cammy_on_camera_live = function () {
    updateCameraButtonState(true);
    if (window.CammyFace && typeof window.CammyFace.start === "function") {
      window.CammyFace.start();
    } else if (typeof window.ensureFaceDetectionWhenReady === "function") {
      window.ensureFaceDetectionWhenReady();
    } else if (typeof window.startFaceDetection === "function") {
      window.startFaceDetection();
    }
  };
  window.__cammy_on_camera_failed = function () {
    updateCameraButtonState(false);
  };

  function bindUi() {
    var dash = $("navDashboardLink");
    if (dash) dash.addEventListener("click", navigateToDashboard);

    var resumeBtn = $("btnResumeMonitoring");
    if (resumeBtn) {
      resumeBtn.addEventListener("click", function () {
        var bar = $("resumeMonitoringBar");
        if (bar) bar.style.display = "none";
        updateCameraButtonState("connecting");
        cammyBeginCameraAfterConsent();
      });
    }

    var startBtn = $("startCamBtn");
    if (startBtn && !startBtn.dataset.camBound) {
      startBtn.dataset.camBound = "1";
      startBtn.addEventListener("click", cammyStartCamera);
    }

    syncResumeBar();
    window.addEventListener("pageshow", syncResumeBar);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindUi);
  } else {
    bindUi();
  }
})();
