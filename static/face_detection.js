/**
 * Client-side age / gender via @vladmandic/face-api (process page).
 * Loaded synchronously after face-api.js and before detail.js.
 */
(function (global) {
  "use strict";

  var MODELS_URL = "https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.15/model/";
  var faceDetectInterval = null;
  var faceModelsLoaded = false;
  var faceApiBackendReady = false;
  var faceDetectCanvas = null;
  var ageHistory = [];
  var AGE_HISTORY_SIZE = 12;
  var missCount = 0;

  function $(id) {
    return document.getElementById(id);
  }

  function median(arr) {
    if (!arr.length) return 0;
    var sorted = arr.slice().sort(function (a, b) { return a - b; });
    var mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  function setStatus(text) {
    var el = $("faceStatusSub");
    if (el) el.textContent = text;
  }

  async function initFaceApiBackend() {
    if (faceApiBackendReady) return true;
    if (typeof faceapi === "undefined" || !faceapi.tf) {
      console.warn("[CammyFace] face-api / TF not available");
      return false;
    }
    try {
      await faceapi.tf.setBackend("webgl");
      await faceapi.tf.ready();
    } catch (e) {
      console.warn("[CammyFace] webgl backend failed, trying cpu:", e);
      try {
        await faceapi.tf.setBackend("cpu");
        await faceapi.tf.ready();
      } catch (e2) {
        console.warn("[CammyFace] cpu backend failed:", e2);
        return false;
      }
    }
    try {
      if (faceapi.tf.env().flagRegistry.CANVAS2D_WILL_READ_FREQUENTLY) {
        faceapi.tf.env().set("CANVAS2D_WILL_READ_FREQUENTLY", true);
      }
      if (typeof faceapi.tf.enableProdMode === "function") {
        await faceapi.tf.enableProdMode();
      }
    } catch (e) { /* optional */ }
    faceApiBackendReady = true;
    return true;
  }

  function getFaceDetectCanvas() {
    if (!faceDetectCanvas) {
      faceDetectCanvas = document.createElement("canvas");
      faceDetectCanvas.id = "faceDetectCanvas";
      faceDetectCanvas.setAttribute("aria-hidden", "true");
      faceDetectCanvas.style.cssText = "position:absolute;left:-9999px;top:0;width:1px;height:1px;opacity:0;";
      document.body.appendChild(faceDetectCanvas);
    }
    return faceDetectCanvas;
  }

  async function loadFaceModels() {
    if (faceModelsLoaded) return true;
    for (var i = 0; i < 60 && typeof faceapi === "undefined"; i++) {
      await new Promise(function (r) { setTimeout(r, 100); });
    }
    if (typeof faceapi === "undefined") {
      console.warn("[CammyFace] face-api script missing");
      return false;
    }
    if (!(await initFaceApiBackend())) return false;
    try {
      await faceapi.nets.tinyFaceDetector.loadFromUri(MODELS_URL);
      await faceapi.nets.ssdMobilenetv1.loadFromUri(MODELS_URL);
      await faceapi.nets.faceLandmark68Net.loadFromUri(MODELS_URL);
      await faceapi.nets.ageGenderNet.loadFromUri(MODELS_URL);
      faceModelsLoaded = true;
      console.info("[CammyFace] models ready (backend=" + faceapi.tf.getBackend() + ")");
      return true;
    } catch (e) {
      console.warn("[CammyFace] model load failed:", e);
      return false;
    }
  }

  function getVideoDisplayRect(video) {
    var cw = video.clientWidth || video.offsetWidth || 0;
    var ch = video.clientHeight || video.offsetHeight || 0;
    var vw = video.videoWidth || 0;
    var vh = video.videoHeight || 0;
    if (!cw || !ch || !vw || !vh) {
      return { x: 0, y: 0, width: cw, height: ch, scale: 1, vw: vw, vh: vh };
    }
    var scale = Math.min(cw / vw, ch / vh);
    var width = vw * scale;
    var height = vh * scale;
    return {
      x: (cw - width) / 2,
      y: (ch - height) / 2,
      width: width,
      height: height,
      scale: scale,
      vw: vw,
      vh: vh,
    };
  }

  function scaleDetections(detections, rect) {
    var s = rect.scale;
    var ox = rect.x;
    var oy = rect.y;
    return detections.map(function (d) {
      var b = d.detection.box;
      var w = b.width * s;
      var h = b.height * s;
      return {
        detection: {
          box: {
            x: b.x * s + ox,
            y: b.y * s + oy,
            width: w,
            height: h,
            area: w * h,
          },
        },
        age: d.age,
        gender: d.gender,
        genderProbability: d.genderProbability,
      };
    });
  }

  async function runDetection(snap, useSsd) {
    if (useSsd) {
      var ssdOpts = new faceapi.SsdMobilenetv1Options({ minConfidence: 0.35, maxResults: 3 });
      return faceapi
        .detectAllFaces(snap, ssdOpts)
        .withFaceLandmarks()
        .withAgeAndGender();
    }
    var tinyOpts = new faceapi.TinyFaceDetectorOptions({ inputSize: 608, scoreThreshold: 0.2 });
    return faceapi
      .detectAllFaces(snap, tinyOpts)
      .withFaceLandmarks()
      .withAgeAndGender();
  }

  function updateChildBadge(isChild, isInfant) {
    var badge = $("childBadge");
    if (!badge) return;
    if (isChild) {
      badge.textContent = isInfant ? "🍼 Infant Detected (≤ 3 yrs)" : "🧒 Child Detected (≤ 12 yrs)";
      badge.style.background = "#fff8e1";
      badge.style.borderColor = "#ffe082";
      badge.style.color = "#e6a800";
    } else {
      badge.textContent = "🧑 Adult (> 12 yrs)";
      badge.style.background = "#edf7f5";
      badge.style.borderColor = "#b3e9e5";
      badge.style.color = "#2da09a";
    }
  }

  function resetChildBadge() {
    var badge = $("childBadge");
    if (!badge) return;
    badge.textContent = "—";
    badge.style.background = "#edf7f5";
    badge.style.borderColor = "#b3e9e5";
    badge.style.color = "#2da09a";
  }

  async function detectFace() {
    var video = $("webcam");
    var canvas = $("faceCanvas");
    if (!video || !canvas || !faceModelsLoaded) return;
    if (video.readyState < 2 || !video.srcObject) return;

    var vw = video.videoWidth || 0;
    var vh = video.videoHeight || 0;
    if (!vw || !vh) return;

    var displayW = video.clientWidth || video.offsetWidth || vw;
    var displayH = video.clientHeight || video.offsetHeight || vh;
    var displayRect = getVideoDisplayRect(video);
    if (typeof faceapi.matchDimensions === "function") {
      faceapi.matchDimensions(canvas, { width: displayW, height: displayH });
    } else {
      canvas.width = displayW;
      canvas.height = displayH;
    }

    var snap = getFaceDetectCanvas();
    snap.width = vw;
    snap.height = vh;
    var snapCtx = snap.getContext("2d", { willReadFrequently: true });
    try {
      snapCtx.drawImage(video, 0, 0, vw, vh);
    } catch (e) {
      console.warn("[CammyFace] drawImage failed:", e);
      return;
    }

    var useSsd = missCount >= 3;
    var detections;
    try {
      detections = await runDetection(snap, useSsd);
    } catch (e) {
      console.warn("[CammyFace] detect error:", e);
      return;
    }

    var ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!detections || !detections.length) {
      missCount += 1;
      setStatus(useSsd ? "No face detected (retrying…)" : "No face detected");
      return;
    }
    missCount = 0;

    var resized = scaleDetections(detections, displayRect);
    var best = resized.reduce(function (a, b) {
      return b.detection.box.area > a.detection.box.area ? b : a;
    });

    var b = best.detection.box;
    var padX = b.width * 0.12;
    var padYTop = b.height * 0.25;
    var padYBot = b.height * 0.15;
    var rx = b.x - padX;
    var ry = b.y - padYTop;
    var rw = b.width + padX * 2;
    var rh = b.height + padYTop + padYBot;
    var side = Math.max(rw, rh);
    var cx = rx + rw / 2;
    var cy = ry + rh / 2;
    var bx = cx - side / 2;
    var by = cy - side / 2;
    var bs = side;

    if (bx < 0) { bs += bx; bx = 0; }
    if (by < 0) { bs += by; by = 0; }
    if (bx + bs > canvas.width) bs = Math.max(0, canvas.width - bx);
    if (by + bs > canvas.height) bs = Math.max(0, canvas.height - by);

    if (bs > 0) {
      ctx.strokeStyle = "rgba(94,196,188,0.35)";
      ctx.lineWidth = 10;
      ctx.strokeRect(bx - 5, by - 5, bs + 10, bs + 10);
      ctx.strokeStyle = "#5ec4bc";
      ctx.lineWidth = 2.5;
      ctx.strokeRect(bx, by, bs, bs);
    }

    var ageVal = typeof best.age === "number" ? best.age : parseFloat(best.age);
    if (isNaN(ageVal)) ageVal = 0;
    ageHistory.push(ageVal);
    if (ageHistory.length > AGE_HISTORY_SIZE) ageHistory.shift();
    var smoothedAge = Math.round(median(ageHistory));

    var genderRaw = (best.gender || "unknown").toString();
    var gender = genderRaw.charAt(0).toUpperCase() + genderRaw.slice(1);
    var genderProb = typeof best.genderProbability === "number" ? best.genderProbability : 0;
    var genderConf = Math.round(genderProb * 100);

    var frameArea = canvas.width * canvas.height;
    var faceRatio = frameArea > 0 ? (b.width * b.height) / frameArea : 0;
    var likelyInfant = faceRatio > 0.18 && smoothedAge >= 12 && smoothedAge <= 35;

    var modeEl = $("monitoringMode");
    var mode = modeEl ? modeEl.value : "auto";
    var isChild;
    var displayAge;
    if (mode === "child") {
      isChild = smoothedAge <= 12 || likelyInfant;
      displayAge = likelyInfant ? "≤ 3 yrs (infant)" : "~" + smoothedAge + " yrs";
    } else if (mode === "adult") {
      isChild = smoothedAge <= 8;
      displayAge = "~" + smoothedAge + " yrs";
    } else {
      isChild = smoothedAge <= 10 || likelyInfant;
      displayAge = likelyInfant ? "≤ 3 yrs (infant)" : "~" + smoothedAge + " yrs";
    }

    var genderEl = $("faceGender");
    var ageEl = $("faceAge");
    if (genderEl) genderEl.textContent = gender + " (" + genderConf + "% conf)";
    if (ageEl) ageEl.textContent = displayAge;
    setStatus(resized.length === 1 ? "1 face detected" : resized.length + " faces detected");
    updateChildBadge(isChild, likelyInfant);
  }

  async function startFaceDetection() {
    console.info("[CammyFace] start requested");
    setStatus("Loading face models…");
    var ok = await loadFaceModels();
    if (!ok) {
      setStatus("Model load failed — refresh page");
      return;
    }
    setStatus("Scanning for face…");
    if (faceDetectInterval) clearInterval(faceDetectInterval);
    missCount = 0;
    detectFace();
    faceDetectInterval = setInterval(function () {
      detectFace();
    }, 500);
  }

  function stopFaceDetection() {
    if (faceDetectInterval) {
      clearInterval(faceDetectInterval);
      faceDetectInterval = null;
    }
    ageHistory = [];
    missCount = 0;
    var canvas = $("faceCanvas");
    if (canvas) {
      var ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    var genderEl = $("faceGender");
    var ageEl = $("faceAge");
    if (genderEl) genderEl.textContent = "";
    if (ageEl) ageEl.textContent = "";
    setStatus("Camera off");
    resetChildBadge();
  }

  function ensureFaceDetectionWhenReady() {
    startFaceDetection();
  }

  global.CammyFace = {
    preload: loadFaceModels,
    start: startFaceDetection,
    stop: stopFaceDetection,
    ensure: ensureFaceDetectionWhenReady,
  };
  global.CammyVideoLayout = { getVideoDisplayRect: getVideoDisplayRect };
  global.startFaceDetection = startFaceDetection;
  global.stopFaceDetection = stopFaceDetection;
  global.ensureFaceDetectionWhenReady = ensureFaceDetectionWhenReady;

  function onDomReady() {
    if (!$("faceStatusSub")) return;
    loadFaceModels().then(function (ok) {
      if (ok) setStatus("Models ready — start camera");
      else setStatus("Face models failed — refresh page");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onDomReady);
  } else {
    onDomReady();
  }
})(window);
