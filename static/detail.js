let pc = null
var negotiatePromise = null
var socket;
var username, email, companyname;


var emo_items = {}
emo_items["happy"] = document.getElementById("happy");
emo_items["angry"] = document.getElementById("angry");
emo_items["disgust"] = document.getElementById("disgust");
emo_items["fear"] = document.getElementById("fear");
emo_items["sad"] = document.getElementById("sad");
emo_items["surprise"] = document.getElementById("surprise");
emo_items["neutral"] = document.getElementById("neutral");
emo_items["excited"] = document.getElementById("excited");
emo_items["worried"] = document.getElementById("worried");
emo_items["tense"] = document.getElementById("tense");

var maxEmo = document.getElementById("maxEmo");
var maxEmoVal = document.getElementById("maxEmoValue");


var food_intol_array = []
var mainFood = document.getElementById("mainFood")
var mainFoodVal = document.getElementById("mainFoodVal")
var nutri_items = {}
nutri_items["calories"] = document.getElementById("calories");
nutri_items["protein"] = document.getElementById("protein");
nutri_items["carbs"] = document.getElementById("carbs");
nutri_items["fat"] = document.getElementById("fat");
nutri_items["fiber"] = document.getElementById("fiber");
nutri_items["sugar"] = document.getElementById("sugar");
nutri_items["sodium"] = document.getElementById("sodium");
nutri_items["cholesterol"] = document.getElementById("cholesterol");
nutri_items["saturatedFat"] = document.getElementById("saturatedFat");

nutri_items["indiv"] = document.getElementById("indiv");
var common_nutri = (typeof CammyNutrition !== "undefined" && CammyNutrition.COMMON_KEYS)
    ? CammyNutrition.COMMON_KEYS
    : ["calories", "protein", "carbs", "fat", "fiber", "sugar", "sodium", "cholesterol", "saturatedFat"];

var percentage_val = document.getElementById("percentage")
var percentage_bar = document.getElementById("nutriRange")
let progress_bar = document.getElementById('progress');

// var emoState = document.getElementById("emoState");
// var emolog = document.getElementById("emoContent");

var foodlog = document.getElementById("foodContent");
var nutrilog = document.getElementById("nutriContent");
var foodState = document.getElementById("foodState");

var foodrect = document.getElementById("foodrect")
var intol_types = []
var pre_food = ""
var waringrect = document.getElementById("warningfood")

const video = document.querySelector('video');
const canvas = document.createElement('canvas');

const context = canvas.getContext('2d');
let intervalId;
let animationFrameId = null;

let footerA = document.getElementById('footer_slide')
let footerB = document.getElementById('footer_slide_choking')
let loader = document.getElementById("loader");

/** FER / WebSocket: blank emotion scores; optional process.html emo bar + % labels. */
function clearEmotionUI(statusMessage) {
    Object.keys(emo_items).forEach(function (k) {
        if (emo_items[k]) emo_items[k].innerText = "";
    });
    if (maxEmo) maxEmo.innerText = "";
    if (maxEmoVal) maxEmoVal.innerText = "";
    var emoSub = document.getElementById("emoStatusSub");
    if (emoSub) emoSub.textContent = statusMessage || "No face detected — move closer";
    var barKeys = ["happy", "neutral", "sad", "surprise", "angry", "disgust", "fear", "excited", "worried", "tense"];
    barKeys.forEach(function (key) {
        var bar = document.getElementById(key + "Bar");
        var pctEl = document.getElementById(key + "Pct");
        if (bar) bar.style.width = "0%";
        if (pctEl) pctEl.innerText = "—";
    });
}


var wsReconnectTimer = null;
var wsManualClose = false;

/** Re-query process-page DOM nodes (safe if script ran before late elements). */
function bindProcessDomRefs() {
    var emoKeys = ["happy", "angry", "disgust", "fear", "sad", "surprise", "neutral", "excited", "worried", "tense"];
    emoKeys.forEach(function (k) {
        emo_items[k] = document.getElementById(k);
    });
    maxEmo = document.getElementById("maxEmo");
    maxEmoVal = document.getElementById("maxEmoValue");
    mainFood = document.getElementById("mainFood");
    mainFoodVal = document.getElementById("mainFoodVal");
    foodlog = document.getElementById("foodContent");
    nutrilog = document.getElementById("nutriContent");
    foodState = document.getElementById("foodState");
    foodrect = document.getElementById("foodrect");
    waringrect = document.getElementById("warningfood");
    footerA = document.getElementById("footer_slide");
    footerB = document.getElementById("footer_slide_choking");
    loader = document.getElementById("loader");
    percentage_val = document.getElementById("percentage");
    percentage_bar = document.getElementById("nutriRange");
    progress_bar = document.getElementById("progress");
    nutri_items["indiv"] = document.getElementById("indiv");
    common_nutri.forEach(function (item) {
        nutri_items[item] = document.getElementById(item);
    });
}

function applyEmotionPayload(data) {
    bindProcessDomRefs();
    if (!data || data._cleared) {
        clearEmotionUI();
        return;
    }
    var barKeys = ["happy", "neutral", "sad", "surprise", "angry", "disgust", "fear", "excited", "worried", "tense"];
    var maxScore = 0;
    var maxEmotion = "";
    barKeys.forEach(function (key) {
        if (data[key] == null) return;
        var raw = parseFloat(data[key]);
        if (isNaN(raw)) return;
        var pct = (raw >= 0 && raw <= 1.001)
            ? Math.min(100, Math.round(raw * 100))
            : Math.min(100, Math.round(raw));
        if (emo_items[key]) emo_items[key].innerText = String(data[key]);
        var bar = document.getElementById(key + "Bar");
        var pctEl = document.getElementById(key + "Pct");
        if (bar) bar.style.width = pct + "%";
        if (pctEl) pctEl.innerText = pct + "%";
        if (raw > maxScore) {
            maxScore = raw;
            maxEmotion = key;
        }
    });
    if (maxEmo) maxEmo.innerText = maxEmotion;
    if (maxEmoVal) {
        maxEmoVal.innerText = (maxScore <= 1.001)
            ? String(Math.round(maxScore * 100))
            : String(maxScore);
    }
    var emoSub = document.getElementById("emoStatusSub");
    if (emoSub && maxEmotion) {
        emoSub.textContent = "Dominant: " + maxEmotion;
    }
}

function applyAllergenPayload(data) {
    if (data.alert_triggered === false) {
        if (typeof window.__cammy_clear_allergen_alert === "function") {
            window.__cammy_clear_allergen_alert(data);
        }
        return;
    }
    if (typeof window.__cammy_handle_allergen_alert === "function") {
        window.__cammy_handle_allergen_alert(data);
        return;
    }
    var allergens = (data.allergens || []).join(", ");
    var food = data.food || "";
    var overlayEl = document.getElementById("warningallergen");
    var textEl = document.getElementById("allergenAlertText");
    if (overlayEl && textEl) {
        textEl.innerText = "⚠ Allergen" + (allergens ? ": " + allergens : "") + (food ? " in " + food : "");
        overlayEl.style.display = "flex";
    }
    var safetyBadge = document.getElementById("safetyBadge");
    var safetySub = document.getElementById("safetySub");
    if (safetyBadge) {
        safetyBadge.textContent = "⚠ ALLERGEN DETECTED";
        safetyBadge.style.background = "#fdecec";
        safetyBadge.style.color = "#dc2626";
    }
    if (safetySub) {
        safetySub.textContent = (allergens ? allergens + " in " : "") + (food || "detected food");
    }
    if (waringrect) waringrect.style.display = "block";
}

function clearFoodSceneUI(clearNutrition) {
    if (typeof window.__cammy_clear_allergen_alert === "function") {
        window.__cammy_clear_allergen_alert({});
    } else {
        var overlayEl = document.getElementById("warningallergen");
        if (overlayEl) overlayEl.style.display = "none";
        if (waringrect) waringrect.style.display = "none";
        if (typeof window.__cammy_set_safety_clear === "function") {
            window.__cammy_set_safety_clear();
        }
    }
    if (clearNutrition && typeof CammyNutrition !== "undefined") {
        CammyNutrition.clearNutritionCells(nutri_items, common_nutri, true);
    }
}

/** Reset all live-monitor panels when the camera is fully stopped. */
function resetMonitoringUI() {
    bindProcessDomRefs();
    clearEmotionUI("Camera off");
    clearFoodSceneUI(true);

    if (mainFood) {
        mainFood.innerText = "—";
        mainFood.classList.remove("food-searching");
    }
    if (mainFoodVal) mainFoodVal.innerText = "";

    var genderEl = document.getElementById("faceGender");
    var ageEl = document.getElementById("faceAge");
    if (genderEl) genderEl.textContent = "";
    if (ageEl) ageEl.textContent = "";
    var faceSub = document.getElementById("faceStatusSub");
    if (faceSub) faceSub.textContent = "Camera off";
    var childBadge = document.getElementById("childBadge");
    if (childBadge) {
        childBadge.textContent = "—";
        childBadge.style.background = "#edf7f5";
        childBadge.style.borderColor = "#b3e9e5";
        childBadge.style.color = "#2da09a";
    }

    var respStatus = document.getElementById("respiratoryStatus");
    if (respStatus) respStatus.textContent = "Start camera & mic to listen";
    var audioAlertText = document.getElementById("audioAlertText");
    if (audioAlertText) audioAlertText.textContent = "—";
    var audioWarning = document.getElementById("warningaudio");
    if (audioWarning) audioWarning.style.display = "none";
    var childWarning = document.getElementById("warningchild");
    if (childWarning) childWarning.style.display = "none";
    var alertPill = document.getElementById("navAlertPill");
    if (alertPill) alertPill.classList.add("hidden");
    if (foodrect) foodrect.style.display = "none";

    var nutriDisplay = document.getElementById("nutriDisplay");
    if (nutriDisplay) nutriDisplay.textContent = "—";
    if (progress_bar) progress_bar.style.width = "0%";
    if (percentage_val) percentage_val.innerText = "";
    if (percentage_bar) percentage_bar.value = 0;

    if (typeof window.__cammy_reset_allergen_audit_since === "function") {
        window.__cammy_reset_allergen_audit_since();
    }
    window.__cammy_camera_ui_active = false;
}
window.__cammy_reset_monitoring_ui = resetMonitoringUI;

function handleWsJson(data) {
    if (!data || data._state == null) return;
    var st = Number(data._state);
    if (isNaN(st)) return;
    if (!window.__cammy_camera_ui_active && st >= 1 && st <= 8) return;

    if (st === 1 || st === 2 || st === 6) {
        if (typeof window.__cammy_hide_detection_bootstrap === "function") {
            window.__cammy_hide_detection_bootstrap();
        }
    }

    if (st === 1) {
        applyEmotionPayload(data);
        return;
    }

    if (st === 2) {
        if (!mainFood) mainFood = document.getElementById("mainFood");
        var main_foods = data.food_main;
        var food_lists = data.food_list || {};
        var foodStatus = data.food_status;
        var foodDisplay = data.food_display;

        if (foodStatus === "searching") {
            clearFoodSceneUI(false);
            if (mainFood) {
                mainFood.innerText = foodDisplay || "Identifying…";
                mainFood.classList.add("food-searching");
            }
            if (mainFoodVal) mainFoodVal.innerText = "";
            return;
        }

        if (mainFood) mainFood.classList.remove("food-searching");

        var noFood = data.food_cleared || foodStatus === "none" || !main_foods
            || main_foods === "unknown_food" || main_foods === "mixed_food";

        if (noFood) {
            clearFoodSceneUI(data.food_cleared || foodStatus === "none");
            if (mainFood) mainFood.innerText = (foodStatus === "none" && foodDisplay) ? foodDisplay : "";
            if (mainFoodVal) mainFoodVal.innerText = "";
            return;
        }

        if (mainFood) mainFood.innerText = main_foods;
        if (mainFoodVal) {
            mainFoodVal.innerText = (food_lists && food_lists[main_foods] != null)
                ? food_lists[main_foods]
                : "--";
        }
        if (footerA) footerA.style.display = "flex";
        if (footerB) footerB.style.display = "none";
        return;
    }

    if (st === 4) {
        if (data.result && String(data.result).toLowerCase().includes("yes")) {
            if (waringrect) waringrect.style.display = "block";
        } else if (waringrect) {
            waringrect.style.display = "none";
        }
        return;
    }

    if (st === 5) {
        if (data.nutrition_source === "clear") {
            if (typeof CammyNutrition !== "undefined") {
                CammyNutrition.clearNutritionCells(nutri_items, common_nutri, true);
            }
            return;
        }
        if (typeof CammyNutrition !== "undefined") {
            var merged = CammyNutrition.mergeNutrition(data.nutrition, data.result);
            CammyNutrition.applyNutritionToUI(merged, nutri_items, nutrilog, percentage_val, percentage_bar, progress_bar);
        }
        return;
    }

    if (st === 6) {
        var childWarning = document.getElementById("warningchild");
        if (childWarning) {
            childWarning.style.display = data.child_present ? "none" : "block";
        }
        return;
    }

    if (st === 7) {
        var audioWarning = document.getElementById("warningaudio");
        var audioAlertText = document.getElementById("audioAlertText");
        var rawEv = (data.event || "").replace(/_/g, " ");
        var label = rawEv ? rawEv.charAt(0).toUpperCase() + rawEv.slice(1) : "Event";
        var line = label + " (" + data.confidence + ")";
        if (audioAlertText) audioAlertText.textContent = line;
        if (audioWarning) audioWarning.style.display = "flex";
        var rss = document.getElementById("respiratoryStatus");
        if (rss) rss.textContent = "Last: " + label;
        return;
    }

    if (st === 8) {
        applyAllergenPayload(data);
    }
}


// window.onload = connect;
document.addEventListener("DOMContentLoaded", function () {
    bindProcessDomRefs();
    if (typeof window.__CAMMY_INTOLERANCES__ !== "undefined" && Array.isArray(window.__CAMMY_INTOLERANCES__)) {
        food_intol_array = window.__CAMMY_INTOLERANCES__.slice();
    }
    window.onbeforeunload = function () {
        wsManualClose = true;
        if (socket && socket.readyState === WebSocket.OPEN) socket.close();
    };
    connect();
    populateCameraSelector('cameraSelect');
});


const uuid = generateUUID();

function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        var r = Math.random() * 16 | 0,
            v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

OPENWEATHER_KEY = "" // REMOVED FOR GITHUB PUSH - Add your key here
async function fetchWeatherData() {
    // If no key is provided, don't even try to fetch to avoid console errors
    if (!OPENWEATHER_KEY) {
        console.warn("OpenWeather API key is missing. Weather display disabled.");
        document.getElementById("LosTemp").innerHTML = `Temp: --°C`;
        return;
    }

    try {
        const response = await fetch(`https://api.openweathermap.org/data/2.5/weather?q=Las+Vegas&appid=${OPENWEATHER_KEY}`);
        const data = await response.json();

        if (data && data.main && data.main.temp !== undefined) {
            const tempInCelsius = data.main.temp - 273.15;
            document.getElementById("LosTemp").innerHTML = `Temperature: ${Math.round(tempInCelsius)}°C`;
        } else {
            document.getElementById("LosTemp").innerHTML = `Temp: --°C`;
        }
    } catch (err) {
        console.error("Weather fetch failed:", err);
        document.getElementById("LosTemp").innerHTML = `Temp: --°C`;
    }

    // Fetch the weather data again in one hour  
    setTimeout(fetchWeatherData, 60 * 60 * 1000);
}

function updateTime() {
    const date = new Date();
    const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
    const dayOfWeek = days[date.getDay()];
    const timeString = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    document.getElementById("LosTime").innerHTML = `${timeString} ${dayOfWeek}`;

    // Update the time again in one minute  
    setTimeout(updateTime, 60 * 1000);
}

function startProcessing() {
    console.log("start processing")

    if (!socket || socket.readyState !== WebSocket.OPEN) {
        connect();
    }

    if (food_intol_array.includes("dairy")) {
        let dairy_array = ["chocolate", "milk", "cheese", "yogurt", "butter", "cream"]
        food_intol_array = food_intol_array.concat(dairy_array)
    }

    // Read from hidden inputs (pre-filled at login; may be empty — session already created server-side)
    username    = document.getElementById('username')   ? document.getElementById('username').value   : '';
    email       = document.getElementById('email')      ? document.getElementById('email').value      : '';
    companyname = document.getElementById('company')    ? document.getElementById('company').value    : '';
    var childId   = document.getElementById('cammyChildId')   ? document.getElementById('cammyChildId').value   : '';
    var childName = document.getElementById('cammyChildName') ? document.getElementById('cammyChildName').value : '';

    var displayname = document.getElementById('displayname');
    var company     = document.getElementById('companyName');
    if (displayname) displayname.innerText = childName || username;
    if (company)     company.innerText     = companyname;

    var data = {
        username:    username,
        email:       email,
        companyname: companyname,
        child_id:    childId || undefined,
        child_name:  childName || undefined,
        intolerance: food_intol_array,
        user_id:     uuid,
    };

    var streamFoodFromVideo = (typeof window.__CAMMY_STREAM_FOOD_VIDEO__ !== "undefined" && window.__CAMMY_STREAM_FOOD_VIDEO__);
    if (!streamFoodFromVideo) {
        captureAndSendFrame();
        console.log("Food detection: full-frame canvas snapshots (WebRTC path disabled for CPU).");
    } else {
        console.log("Food detection: server WebRTC stream (set STREAM_FOOD_FROM_VIDEO=0 to reduce CPU).");
    }

    return fetch('/startProcessing', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    }).then(function(response) {
        if (!response.ok) throw new Error('HTTP error: ' + response.status);
        window.__CAMMY_INTOLERANCES__ = food_intol_array.slice();
        if (typeof initSafetyProfile === "function") initSafetyProfile();
        if (typeof window.__cammy_reset_allergen_audit_since === "function") {
            window.__cammy_reset_allergen_audit_since();
        }
        var rs = document.getElementById('respiratoryStatus');
        if (rs) rs.textContent = 'Mic on — listening for coughs';
    }).catch(function(e) {
        console.log('startProcessing fetch error: ' + e.message);
    });
}

function submitSessionFeedback() {
    var food = document.getElementById('feedbackFoodRating');
    var emotion = document.getElementById('feedbackEmotionRating');
    var audio = document.getElementById('feedbackAudioRating');
    var overall = document.getElementById('feedbackOverallRating');
    var notes = document.getElementById('feedbackNotes');
    var status = document.getElementById('feedbackStatus');
    var payload = {
        food_accuracy_rating: food && food.value ? parseInt(food.value, 10) : null,
        emotion_accuracy_rating: emotion && emotion.value ? parseInt(emotion.value, 10) : null,
        audio_accuracy_rating: audio && audio.value ? parseInt(audio.value, 10) : null,
        overall_rating: overall && overall.value ? parseInt(overall.value, 10) : null,
        notes: notes ? notes.value : '',
        browser: navigator.userAgent || '',
        device: (navigator.platform || '') + ' ' + (screen.width + 'x' + screen.height),
    };
    return fetch('/api/testing-results', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
    }).then(function (r) { return r.json(); }).then(function (data) {
        if (status) {
            status.hidden = false;
            status.textContent = data && data.ok ? 'Thanks — feedback saved.' : 'Could not save feedback.';
        }
    }).catch(function () {
        if (status) {
            status.hidden = false;
            status.textContent = 'Could not save feedback.';
        }
    });
}

function stopProcessing() {
    var secondPage_3 = document.getElementById('register_photo_process')
    var thirdPage = document.getElementById('register_photo_end')
    var confeti_page = document.getElementById('confeti')

    secondPage_3.style.display = "none"
    thirdPage.style.display = "flex"
    confeti_page.style.display = "block"
    foodrect.style.display = 'none'
    loader.style.display = "block";

    console.log("stop stream")
    // stopStream()

    fetch('/endProcessing', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
    })
        .then(response => response.text())
        .then(data => console.log(data))
        .catch((error) => {
            console.error('Error:', error);
        });

    var feedbackBtn = document.getElementById('feedbackSubmitBtn');
    if (feedbackBtn && !feedbackBtn.dataset.bound) {
        feedbackBtn.dataset.bound = '1';
        feedbackBtn.addEventListener('click', submitSessionFeedback);
    }

    // clearInterval(intervalId); 
    if (animationFrameId !== null) {
        window.cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
    }
    // window.location.href = "/final_page"
}

function restartProcessing() {
    location.reload();
}

async function fetchData(query_data) {
    try {
        const response = await fetch('/intolerance', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(query_data),
        });
        const responseText = await response.text();
        console.log("intol--------", responseText);
        if (responseText.toLowerCase().includes("yes"))
            return true;
        else
            return false;
    } catch (error) {
        console.error(error);
        return false;
    }
}


function connect() {
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }
    bindProcessDomRefs();
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return;
    }

    console.log("WebSocket connecting, token=" + uuid);
    socket = new WebSocket("wss://" + window.location.host + "/chill_results?token=" + uuid);
    window.__cammySocket = socket;

    socket.onopen = function () {
        console.log("WebSocket connection established");
        bindProcessDomRefs();
        if (typeof window.__CAMMY_INTOLERANCES__ !== "undefined" && Array.isArray(window.__CAMMY_INTOLERANCES__)) {
            food_intol_array = window.__CAMMY_INTOLERANCES__.slice();
        }
    };
    socket.onmessage = function (event) {
        try {
            var raw = event.data;
            if (typeof raw !== "string") return;

            var txt = raw.split("\\");
            if (txt[0] === "state") { console.log(txt[1]); return; }
            if (txt[0] === "log") { console.log(txt[1]); return; }
            if (txt[0] === "foodrect") {
                if (foodrect) {
                    foodrect.style.left = "10%";
                    foodrect.style.top = "78%";
                    foodrect.style.width = "40%";
                    foodrect.style.height = "20%";
                }
                return;
            }
            if (txt[0] === "endRec") { console.log("recording ended"); return; }
            if (txt[0] === "endPro") {
                if (loader) loader.style.display = "none";
                var qrAlert = document.getElementById("qrAlert");
                if (qrAlert) qrAlert.style.display = "none";
                var qrNode = document.getElementById("qrcode");
                if (qrNode && typeof QRCode !== "undefined") {
                    new QRCode(qrNode, {
                        text: "https://" + window.location.host + "/static/videos/" + txt[1],
                        width: 128,
                        height: 128
                    });
                }
                return;
            }
            if (txt[0] === "name") { console.log("username"); return; }

            handleWsJson(JSON.parse(raw));
        } catch (err) {
            console.error("WebSocket handler error:", err, event.data);
        }
    };
    socket.onerror = function (err) {
        console.warn("WebSocket error:", err);
    };
    socket.onclose = function () {
        console.log("WebSocket connection closed");
        socket = null;
        window.__cammySocket = null;
        if (animationFrameId !== null) {
            window.cancelAnimationFrame(animationFrameId);
            animationFrameId = null;
        }
        if (!wsManualClose) {
            wsReconnectTimer = setTimeout(connect, 2000);
        }
    };
}


async function populateCameraSelector(selectElementId) {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(function (d) { return d.kind === 'videoinput'; });
        const select = document.getElementById(selectElementId);
        if (!select) return;
        select.innerHTML = '';
        videoDevices.forEach(function (device, i) {
            const option = document.createElement('option');
            option.value = device.deviceId;
            option.text = device.label || 'Camera ' + (i + 1);
            select.appendChild(option);
        });
        if (videoDevices.length === 0) {
            select.innerHTML = '<option value="">No cameras found</option>';
        }
    } catch (err) {
        console.warn('Could not enumerate cameras:', err);
        var select = document.getElementById(selectElementId);
        if (select) select.innerHTML = '<option value="">Camera access denied</option>';
    }
}

function cammyKickFaceDetection() {
    function kick() {
        if (window.CammyFace && typeof window.CammyFace.start === "function") {
            window.CammyFace.start();
        } else if (typeof window.startFaceDetection === "function") {
            window.startFaceDetection();
        }
    }
    kick();
    setTimeout(kick, 400);
    setTimeout(kick, 1500);
}

/**
 * @param {function(): void | { beforeNegotiate?: function(): void, after?: function(): void }} [opts]
 *        If a function, it runs after WebRTC negotiation completes.
 *        If an object: beforeNegotiate runs after tracks are attached (set processing / session
 *        before /offer so audio classification is active immediately); after runs when connected.
 */
function startStream(opts) {
    var onBeforeNegotiate = null;
    var onStreamReady = null;
    if (typeof opts === 'function') {
        onStreamReady = opts;
    } else if (opts && typeof opts === 'object') {
        onBeforeNegotiate = opts.beforeNegotiate;
        onStreamReady = opts.after;
    }

    if (pc) {
        try {
            pc.getSenders().forEach(function (sender) {
                if (sender.track) sender.track.stop();
            });
            pc.close();
        } catch (e) {
            console.warn('WebRTC: closing previous peer connection', e);
        }
        pc = null;
    }
    negotiatePromise = null;

    pc = createPeerConnection();
    var cameraSelect = document.getElementById('cameraSelect');
    var selectedDeviceId = cameraSelect ? cameraSelect.value : null;
    // Virtual cameras (ManyCam): do not force 16:9 — use native source aspect & resolution.
    var videoConstraints = selectedDeviceId
        ? { deviceId: { exact: selectedDeviceId } }
        : { width: { ideal: 1280 }, height: { ideal: 720 } };
    var constraints = {
        audio: {
            // ── Cough detection: disable browser-side audio processing ───────
            // echoCancellation and noiseSuppression suppress the short transient
            // bursts that YAMNet uses to classify coughs. Server-side noisereduce
            // handles noise filtering instead.
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl:  false,
        },
        video: videoConstraints,
    };

    if (constraints.audio || constraints.video) {
        navigator.mediaDevices.getUserMedia(constraints).then(function (stream) {
            video.srcObject = stream;
            video.muted = true;
            var playP = video.play();
            if (playP && typeof playP.catch === "function") {
                playP.catch(function (e) { console.warn("video.play:", e); });
            }
            cammyKickFaceDetection();
            if (typeof window.__cammy_on_camera_live === 'function') {
                try { window.__cammy_on_camera_live(stream); } catch (e) { console.warn(e); }
            }
            stream.getTracks().forEach(function (track) {
                pc.addTrack(track, stream);
            });     // connect a video stream("track") from local webcam to the WebRTC connection
            console.log("----------- video constraints", constraints)

            var pre = Promise.resolve();
            if (typeof onBeforeNegotiate === 'function') {
                var maybe = onBeforeNegotiate();
                pre = (maybe && typeof maybe.then === 'function') ? maybe : Promise.resolve();
            }
            return pre.then(function () { return negotiate(); });
        }).then(function () {
            if (typeof onStreamReady === 'function') onStreamReady();
            cammyKickFaceDetection();
        }).catch(function (err) {
            console.error(err);
            if (typeof window.__cammy_on_camera_failed === 'function') {
                try { window.__cammy_on_camera_failed(err); } catch (e) { console.warn(e); }
            }
            alert(
                'Could not access the camera or microphone. ' +
                'Cough detection needs the microphone — allow both when the browser asks. ' +
                (err && err.message ? err.message : String(err))
            );
        });
    } else {
        if (typeof onBeforeNegotiate === 'function') onBeforeNegotiate();
        negotiate().then(function () {
            if (typeof onStreamReady === 'function') onStreamReady();
        });
    }
}

function captureAndSendFrame() {
    let lastCaptureTime = 0;
    var foodCaptureMs = (typeof window.__CAMMY_FOOD_CAPTURE_MS__ === "number" && window.__CAMMY_FOOD_CAPTURE_MS__ >= 500)
        ? window.__CAMMY_FOOD_CAPTURE_MS__
        : 600;
    var foodChangeMinMs = (typeof window.__CAMMY_FOOD_CAPTURE_CHANGE_MIN_MS__ === "number"
        && window.__CAMMY_FOOD_CAPTURE_CHANGE_MIN_MS__ >= 350)
        ? window.__CAMMY_FOOD_CAPTURE_CHANGE_MIN_MS__
        : 450;

    var thumbCanvas = document.createElement("canvas");
    thumbCanvas.width = 64;
    thumbCanvas.height = 48;
    var thumbCtx = thumbCanvas.getContext("2d", { willReadFrequently: true });
    var lastThumb = null;

    function thumbChanged(data) {
        if (!lastThumb || lastThumb.length !== data.length) return true;
        var diff = 0;
        for (var i = 0; i < data.length; i += 16) {
            diff += Math.abs(data[i] - lastThumb[i])
                + Math.abs(data[i + 1] - lastThumb[i + 1])
                + Math.abs(data[i + 2] - lastThumb[i + 2]);
        }
        var samples = data.length / 16;
        return (diff / samples) > 10;
    }

    function capture() {
        if (!video || !video.videoWidth || !video.videoHeight) {
            animationFrameId = window.requestAnimationFrame(capture);
            return;
        }

        const vw = video.videoWidth;
        const vh = video.videoHeight;
        const maxDim = (typeof window.__CAMMY_FOOD_CANVAS_MAX_DIM__ === "number" && window.__CAMMY_FOOD_CANVAS_MAX_DIM__ >= 320)
            ? window.__CAMMY_FOOD_CANVAS_MAX_DIM__
            : 720;
        const scale = Math.min(1, maxDim / Math.max(vw, vh));
        const cropWidth = Math.max(1, Math.round(vw * scale));
        const cropHeight = Math.max(1, Math.round(vh * scale));

        if (canvas.width !== cropWidth) canvas.width = cropWidth;
        if (canvas.height !== cropHeight) canvas.height = cropHeight;

        thumbCtx.drawImage(video, 0, 0, vw, vh, 0, 0, 64, 48);
        var thumbData = thumbCtx.getImageData(0, 0, 64, 48).data;
        var sceneChanged = thumbChanged(thumbData);
        lastThumb = thumbData;

        const now = Date.now();
        var elapsed = now - lastCaptureTime;
        var sendHeartbeat = elapsed >= foodCaptureMs;
        var sendOnChange = sceneChanged && elapsed >= foodChangeMinMs;

        if (sendHeartbeat || sendOnChange) {
            context.clearRect(0, 0, canvas.width, canvas.height);
            context.drawImage(video, 0, 0, vw, vh, 0, 0, cropWidth, cropHeight);

            const frame = canvas.toDataURL("image/jpeg", 0.82);
            sendFrameToBackend(frame);

            lastCaptureTime = now;
        }

        animationFrameId = window.requestAnimationFrame(capture);
    }

    capture();
}

function sendFrameToBackend(frame) {
    // Safely strip the data-URL prefix (works for any MIME type)
    const parts = frame.split(',');
    if (parts.length < 2 || !parts[1]) return;  // guard: empty/invalid frame
    const base64Data = parts[1];

    let byteCharacters;
    try {
        byteCharacters = atob(base64Data);
    } catch(e) {
        console.warn('sendFrameToBackend: invalid base64, skipping frame.', e);
        return;
    }

    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
    }

    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: 'image/jpeg' });

    const formData = new FormData();
    formData.append('photo', blob, 'frame.jpeg');

    fetch(`/canvasImage?token=${uuid}`, {
        method: 'POST',
        body: formData
    }).then(response => {
        // Handle the response from the server
    }).catch(error => {
        console.error('Error:', error);
    });
}


function stopStream() {
    if (!pc) return;
    negotiatePromise = null;
    if (pc.getTransceivers) {
        pc.getTransceivers().forEach(function (transceiver) {
            if (transceiver.stop) {
                transceiver.stop();
            }
        });
    }
    pc.getSenders().forEach(function (sender) {
        if (sender.track) sender.track.stop();
    });
    setTimeout(function () {
        pc.close();
        pc = null;
    }, 500);
}

/** Stop WebRTC + canvas food capture without ending the meal session (e.g. dashboard pause). */
function pauseCameraOnly() {
    negotiatePromise = null;
    if (animationFrameId !== null) {
        window.cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
    }
    if (pc) {
        stopStream();
    }
    var video = document.getElementById('webcam');
    if (video && video.srcObject) {
        video.srcObject.getTracks().forEach(function (track) {
            track.stop();
        });
        video.srcObject = null;
    }
}


function createPeerConnection() {
    pc = new RTCPeerConnection({
        iceServers: [
            // {
            //     urls: "stun:stun.relay.metered.ca:80",
            // },

            //---------- mealtimecammy
            // {
            //     urls: "turn:standard.relay.metered.ca:80",
            //     username: "1bd4dc81147de6e178f73446",
            //     credential: "CRz9w0yVvfe2i0XO",
            // },
            // {
            //     urls: "turn:standard.relay.metered.ca:80?transport=tcp",
            //     username: "1bd4dc81147de6e178f73446",
            //     credential: "CRz9w0yVvfe2i0XO",
            // },
            // {
            //     urls: "turn:standard.relay.metered.ca:443",
            //     username: "1bd4dc81147de6e178f73446",
            //     credential: "CRz9w0yVvfe2i0XO",
            // },
            {
                urls: "turn:standard.relay.metered.ca:443?transport=tcp",
                username: "1bd4dc81147de6e178f73446",
                credential: "CRz9w0yVvfe2i0XO",
            },


            //------------------ babii
            // {
            // urls: "turn:a.relay.metered.ca:80",
            // username: "bcc3a585c8df20e4b5ffcc1a",
            // credential: "pu2U+m9uaBqL+k7b",
            // },

            // {
            // urls: "turn:a.relay.metered.ca:80?transport=tcp",
            // username: "bcc3a585c8df20e4b5ffcc1a",
            // credential: "pu2U+m9uaBqL+k7b",
            // },

            // {
            // urls: "turn:a.relay.metered.ca:443",
            // username: "bcc3a585c8df20e4b5ffcc1a",
            // credential: "pu2U+m9uaBqL+k7b",
            // },

            // {
            // urls: "turn:a.relay.metered.ca:443?transport=tcp",
            // username: "bcc3a585c8df20e4b5ffcc1a",
            // credential: "pu2U+m9uaBqL+k7b",
            // },


            // {
            //     urls: "turn:standard.relay.metered.ca:80",
            //     username: "bcc3a585c8df20e4b5ffcc1a",
            //     credential: "pu2U+m9uaBqL+k7b",
            // },
            //   {
            //     urls: "turn:standard.relay.metered.ca:80?transport=tcp",
            //     username: "bcc3a585c8df20e4b5ffcc1a",
            //     credential: "pu2U+m9uaBqL+k7b",
            //   },
            //   {
            //     urls: "turn:standard.relay.metered.ca:443",
            //     username: "bcc3a585c8df20e4b5ffcc1a",
            //     credential: "pu2U+m9uaBqL+k7b",
            //   },
            //   {
            //     urls: "turn:standard.relay.metered.ca:443?transport=tcp",
            //     username: "bcc3a585c8df20e4b5ffcc1a",
            //     credential: "pu2U+m9uaBqL+k7b",
            //   },

            // ------------------ global
            // {
            //     urls: "turn:global.relay.metered.ca:80",
            //     username: "bcc3a585c8df20e4b5ffcc1a",
            //     credential: "pu2U+m9uaBqL+k7b",
            //   },
            // {
            //     urls: "turn:global.relay.metered.ca:80?transport=tcp",
            //     username: "bcc3a585c8df20e4b5ffcc1a",
            //     credential: "pu2U+m9uaBqL+k7b",
            //   },
            //   {
            //     urls: "turn:global.relay.metered.ca:443",
            //     username: "bcc3a585c8df20e4b5ffcc1a",
            //     credential: "pu2U+m9uaBqL+k7b",
            //   },
            //   {
            //     urls: "turn:global.relay.metered.ca:443?transport=tcp",
            //     username: "bcc3a585c8df20e4b5ffcc1a",
            //     credential: "pu2U+m9uaBqL+k7b",
            //   },

            // ----------------- North America
            // {
            //     urls: "turn:na.relay.metered.ca:80?transport=tcp",
            //     username: "bcc3a585c8df20e4b5ffcc1a",
            //     credential: "pu2U+m9uaBqL+k7b",
            //   },
        ],
    });



    // making the video stream visible on the web page, a video stream from the server to the frontend is attached to an HTML <video> element as it's source
    // pc.addEventListener('track', function(evt) {
    //     if (evt.track.kind == 'video')
    //         document.getElementById('webcam').srcObject = evt.streams[0];        
    // });

    console.log("creating pc....")
    return pc;
}

// Signaling is the exchange of the metadata of each peer, called session description, such as IP address of peer, available ports, etc
function negotiate() {
    if (!pc) {
        return Promise.reject(new Error('WebRTC: no peer connection'));
    }
    if (negotiatePromise) {
        return negotiatePromise;
    }

    var activePc = pc;
    negotiatePromise = activePc.createOffer().then(function (offer) {
        if (!activePc || activePc.signalingState === 'closed') return;
        return activePc.setLocalDescription(offer);
    }).then(function () {
        if (!activePc || activePc.signalingState === 'closed') return;
        return new Promise(function (resolve) {
            if (activePc.iceGatheringState === 'complete') {
                resolve();
                return;
            }
            var settled = false;
            function finish() {
                if (settled) return;
                settled = true;
                activePc.removeEventListener('icegatheringstatechange', checkState);
                resolve();
            }
            function checkState() {
                if (activePc.iceGatheringState === 'complete') finish();
            }
            activePc.addEventListener('icegatheringstatechange', checkState);
            setTimeout(finish, 8000);
        });
    }).then(function () {
        if (!activePc || activePc.signalingState === 'closed') return;
        var offer = activePc.localDescription;
        if (!offer) {
            throw new Error('WebRTC: missing local offer');
        }

        return fetch(`/offer?token=${uuid}`, {
            body: JSON.stringify({
                sdp: offer.sdp,
                type: offer.type,
                video_transform: ""  // "edges"
            }),
            headers: {
                'Content-Type': 'application/json'
            },
            method: 'POST'
        });
    }).then(function (response) {
        if (!response.ok) {
            throw new Error('WebRTC offer failed: HTTP ' + response.status);
        }
        return response.json();
    }).then(function (answer) {
        if (!activePc || activePc.signalingState === 'closed') return;
        if (activePc.signalingState === 'stable') {
            console.warn('WebRTC: answer skipped — connection already stable');
            return;
        }
        if (activePc.signalingState !== 'have-local-offer') {
            console.warn('WebRTC: answer skipped — unexpected state:', activePc.signalingState);
            return;
        }
        return activePc.setRemoteDescription(answer);
    }).catch(function (e) {
        if (!activePc || activePc.signalingState === 'closed') return;
        if (e && e.name === 'InvalidStateError' && activePc.signalingState === 'stable') {
            console.warn('WebRTC negotiation already settled:', e.message || e);
            return;
        }
        console.error('WebRTC negotiation failed:', e);
    }).finally(function () {
        negotiatePromise = null;
    });

    return negotiatePromise;
}

let isSvgChecked = false;

function toggleDiv(clickedDiv) {
    // Toggle the class between 'checked' and 'unchecked'
    console.log("toggle div clicked")
    if (clickedDiv.classList.contains("checked")) {
        clickedDiv.classList.remove("checked");
        clickedDiv.classList.add("unchecked");
        isSvgChecked = false;
    } else {
        clickedDiv.classList.remove("unchecked");
        clickedDiv.classList.add("checked");
        isSvgChecked = true;
    }

}

function updateSpanStyle(clickedDiv) {
    ///////////// 1.egg  2.fish  3.shellfish  4.nut 5.dairy  6.soy

    var clickedDivId = clickedDiv.id;
    let intolId = clickedDivId.split("_")[0]
    console.log("clickedDivId", intolId);

    // Get the current text color
    var currentColor = clickedDiv.style.color;
    console.log("currentColor", currentColor);

    // Toggle between two colors (e.g., red and blue)
    if (currentColor === 'skyblue') {
        clickedDiv.style.color = 'lightgray';
        food_intol_array = food_intol_array.filter(item => item !== intolId);
        console.log("-----", food_intol_array)
    } else {
        clickedDiv.style.color = 'skyblue';
        // if (!food_intol_array.includes(intolId))
        food_intol_array.push(intolId)
        console.log("-----", food_intol_array)
    }
}