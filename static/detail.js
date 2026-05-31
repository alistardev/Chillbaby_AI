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
function clearEmotionUI() {
    Object.keys(emo_items).forEach(function (k) {
        if (emo_items[k]) emo_items[k].innerText = "";
    });
    if (maxEmo) maxEmo.innerText = "";
    if (maxEmoVal) maxEmoVal.innerText = "";
    var barKeys = ["happy", "neutral", "sad", "surprise", "angry", "disgust", "fear", "excited", "worried", "tense"];
    barKeys.forEach(function (key) {
        var bar = document.getElementById(key + "Bar");
        var pctEl = document.getElementById(key + "Pct");
        if (bar) bar.style.width = "0%";
        if (pctEl) pctEl.innerText = "";
    });
}


// window.onload = connect;
document.addEventListener("DOMContentLoaded", function () {
    if (typeof window.__CAMMY_INTOLERANCES__ !== "undefined" && Array.isArray(window.__CAMMY_INTOLERANCES__)) {
        food_intol_array = window.__CAMMY_INTOLERANCES__.slice();
    }
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

    if (food_intol_array.includes("dairy")) {
        let dairy_array = ["chocolate", "milk", "cheese", "yogurt", "butter", "cream"]
        food_intol_array = food_intol_array.concat(dairy_array)
    }

    // Read from hidden inputs (pre-filled at login; may be empty — session already created server-side)
    username    = document.getElementById('username')   ? document.getElementById('username').value   : '';
    email       = document.getElementById('email')      ? document.getElementById('email').value      : '';
    companyname = document.getElementById('company')    ? document.getElementById('company').value    : '';

    var displayname = document.getElementById('displayname');
    var company     = document.getElementById('companyName');
    if (displayname) displayname.innerText = username;
    if (company)     company.innerText     = companyname;

    var data = {
        username:    username,
        email:       email,
        companyname: companyname,
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
        if (rs) rs.textContent = 'Listening for coughs…';
    }).catch(function(e) {
        console.log('startProcessing fetch error: ' + e.message);
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
        method: 'GET', // or 'POST'  
        headers: {
            'Content-Type': 'application/json',
            // 'Authorization': 'Bearer ' + token // for protected routes  
        }
    })
        .then(response => response.text()) // or .text() .json() for text response  
        .then(data => console.log(data))
        .catch((error) => {
            console.error('Error:', error);
        });

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
    console.log(uuid);

    // socket = new WebSocket(`wss://localhost:8000/chill_results?token=${uuid}`);  
    // let socket = new WebSocket(`wss://40.90.233.137:8080/chill_results?token=${uuid}`); 
    let socket = new WebSocket(`wss://${window.location.host}/chill_results?token=${uuid}`);
    socket.onopen = function (event) {
        console.log('WebSocket connection established');
        // Re-sync intolerances after login (process page); do not wipe register-page selections
        if (typeof window.__CAMMY_INTOLERANCES__ !== 'undefined' && Array.isArray(window.__CAMMY_INTOLERANCES__)) {
            food_intol_array = window.__CAMMY_INTOLERANCES__.slice();
        }
        // Do NOT auto-start camera here — wait for user to click Start Camera
    };
    socket.onmessage = async function (event) {
        // console.log("WebSocket message received")
        var txt = event.data.split('\\');
        // console.log("--- log", txt)
        if (txt[0] === "state") {
            console.log(txt[1])
        }
        else if (txt[0] === "log") {
            console.log(txt[1])
        }
        else if (txt[0] === "foodrect") {
            // foodrect box intentionally hidden – only face bounding box is shown
            // foodrect.style.display = 'block'
            foodrect.style.left = '10%';
            foodrect.style.top = '78%';
            foodrect.style.width = '40%';
            foodrect.style.height = '20%';
        }
        else if (txt[0] === "endRec") {
            console.log("recording ended")
        }
        else if (txt[0] === "endPro") {

            loader.style.display = "none";
            let qrAlert = document.getElementById("qrAlert")
            qrAlert.style.display = "none"

            var filename = `https://${window.location.host}/static/videos/` + txt[1]
            console.log("stop processing.......", filename)
            var qrcode = new QRCode(document.getElementById("qrcode"), {
                text: filename,
                width: 128,
                height: 128
            });
            // stopView()
        }
        else if (txt[0] === "name") {
            console.log("username")
        }
        else {
            const result_data = event.data
            var data = JSON.parse(result_data);
            if (data["_state"] == 1) {
                if (data["_cleared"]) {
                    clearEmotionUI();
                    return;
                }
                delete data._state;

                var maxScore = 0;
                var maxEmotion = '';
                for (var emotion in data) {
                    var emotionLower = emotion.toLowerCase();
                    if (!emo_items[emotionLower]) continue;
                    emo_items[emotionLower].innerText = data[emotion];
                    if (data[emotion] > maxScore) {
                        maxScore = data[emotion];
                        maxEmotion = emotion;
                    }
                }

                maxEmotion = maxEmotion.toLowerCase();
                maxEmo.innerText = maxEmotion
                // FER scores are 0–1; show as percent if needed elsewhere
                maxEmoVal.innerText = (maxScore <= 1.001)
                    ? String(Math.round(maxScore * 100))
                    : String(maxScore)
                // emoState.innerText = maxEmotion.charAt(0).toUpperCase() + maxEmotion.slice(1) + ' ' + maxScore 

                // let jsonString = JSON.stringify(data);
                // emolog.innerText = jsonString;

            }
            if (data["_state"] == 2) {
                var main_foods = data["food_main"]
                var food_lists = data["food_list"] || {}
                var foodStatus = data["food_status"]
                var foodDisplay = data["food_display"]

                if (foodStatus === "searching") {
                    if (mainFood) {
                        mainFood.innerText = foodDisplay || "Identifying… checking cloud API"
                        mainFood.classList.add("food-searching")
                    }
                    if (mainFoodVal) mainFoodVal.innerText = ""
                    if (typeof CammyNutrition !== "undefined") {
                        CammyNutrition.clearNutritionCells(nutri_items, common_nutri);
                    } else {
                        common_nutri.forEach(function (item) {
                            if (nutri_items[item]) nutri_items[item].innerText = "--";
                        });
                    }
                    if (footerA) footerA.style.display = "flex"
                    if (footerB) footerB.style.display = "none"
                    return
                }

                if (mainFood) mainFood.classList.remove("food-searching")

                var noFood = data["food_cleared"] || foodStatus === "none" || !main_foods
                    || main_foods === "unknown_food" || main_foods === "mixed_food"

                if (noFood) {
                    mainFood.innerText = (foodStatus === "none" && foodDisplay) ? foodDisplay : ""
                    mainFoodVal.innerText = ""
                    if (typeof CammyNutrition !== "undefined") {
                        CammyNutrition.clearNutritionCells(nutri_items, common_nutri, true);
                    } else {
                        common_nutri.forEach(function (item) {
                            if (nutri_items[item]) nutri_items[item].innerText = "";
                        });
                    }
                    if (nutri_items["indiv"]) nutri_items["indiv"].innerText = "";
                    if (nutrilog) nutrilog.innerText = "";
                    if (percentage_val) percentage_val.innerText = "";
                    if (percentage_bar) percentage_bar.value = 0;
                    if (progress_bar) {
                        progress_bar.style.width = "0%";
                        progress_bar.style.background = "linear-gradient(270deg, #FFFFFF 1.86%, #B0B0B0 97.39%)";
                    }
                    footerA.style.display = "flex";
                    footerB.style.display = "none";
                    return;
                }

                mainFood.innerText = main_foods
                mainFoodVal.innerText = (food_lists && food_lists[main_foods] != null) ? food_lists[main_foods] : "--"
                if (typeof CammyNutrition !== "undefined") {
                    CammyNutrition.clearNutritionCells(nutri_items, common_nutri);
                } else {
                    common_nutri.forEach(function (item) {
                        if (nutri_items[item]) nutri_items[item].innerText = "--";
                    });
                }
                nutri_items["indiv"].innerText = JSON.stringify(food_lists);
                percentage_val.innerText = "--";
                percentage_bar.value = 0;
                progress_bar.style.width = "0%";
                progress_bar.style.background = "linear-gradient(270deg, #FFFFFF 1.86%, #B0B0B0 97.39%)";

                var rawMain = String(main_foods || "").toLowerCase();
                if (rawMain.indexOf("grape") !== -1) {
                    footerB.style.display = "flex"
                    footerA.style.display = "none"
                } else {
                    footerA.style.display = "flex"
                    footerB.style.display = "none"
                }

            }
            if (data["_state"] == 3) {

                var main_foods = data["main"]
                var food_lists = data["list"]
                var nutri_lists = data["nutri"]

                // console.log("food detected----", main_foods)
                // console.log(food_lists)

                str_main_food = ""
                let str_food_list = JSON.stringify(food_lists);
                let str_nutri_list = JSON.stringify(nutri_lists);
                for (let i = 0; i < main_foods.length; i++) {
                    if (i == 0)
                        str_main_food = main_foods[i]
                    else
                        str_main_food = str_main_food + ", " + main_foods[i]
                }
                foodState.innerText = str_main_food
                foodlog.innerText = str_food_list + "\n" + str_nutri_list

                query_data = {
                    'food': str_food_list,
                    'intol': intol_types
                }
                if (pre_food != maxFood) {
                    // console.log("--------- intolerance checking-------")
                    pre_food = maxFood;
                    fetchData(query_data).then(red_flag => {
                        console.log(red_flag)
                        // Handle red_flag here  
                        if (red_flag)
                            waringrect.style.display = "block"
                        else
                            waringrect.style.display = "none"
                    });
                }
            }
            if (data["_state"] == 4) {
                if (data["result"].toLowerCase().includes("yes")) {
                    if (waringrect) waringrect.style.display = "block";
                } else {
                    if (waringrect) waringrect.style.display = "none";
                }
            }
            if (data["_state"] == 5) {
                if (data["nutrition_source"] === "clear") {
                    if (typeof CammyNutrition !== "undefined") {
                        CammyNutrition.clearNutritionCells(nutri_items, common_nutri, true);
                    } else {
                        common_nutri.forEach(function (item) {
                            if (nutri_items[item]) nutri_items[item].innerText = "";
                        });
                    }
                    if (nutri_items["indiv"]) nutri_items["indiv"].innerText = "";
                    if (nutrilog) nutrilog.innerText = "";
                    if (percentage_val) percentage_val.innerText = "";
                    if (percentage_bar) percentage_bar.value = 0;
                    if (progress_bar) {
                        progress_bar.style.width = "0%";
                        progress_bar.style.background = "linear-gradient(270deg, #FFFFFF 1.86%, #B0B0B0 97.39%)";
                    }
                    return;
                }
                if (typeof CammyNutrition !== "undefined") {
                    var merged = CammyNutrition.mergeNutrition(data["nutrition"], data["result"]);
                    CammyNutrition.applyNutritionToUI(merged, nutri_items, nutrilog, percentage_val, percentage_bar, progress_bar);
                    if (Object.keys(merged).length === 0 && data["result"]) {
                        nutrilog.innerText = typeof data["result"] === "string" ? data["result"] : JSON.stringify(data["result"]);
                    }
                } else {
                    nutrilog.innerText = typeof data["result"] === "string" ? data["result"] : JSON.stringify(data["result"]);
                }
            }

            // Phase 2: child detection alert (_state 6)
            if (data["_state"] == 6) {
                var childWarning = document.getElementById("warningchild");
                if (!data["child_present"]) {
                    childWarning.style.display = "block";
                    console.log("Child not detected - conf:", data["confidence"]);
                } else {
                    childWarning.style.display = "none";
                    console.log("Child detected - conf:", data["confidence"]);
                }
            }

            // Phase 3: YAMNet respiratory alert (_state 7); event is cough / sneeze / wheeze / throat_clearing
            if (data["_state"] == 7) {
                var audioWarning = document.getElementById("warningaudio");
                var audioAlertText = document.getElementById("audioAlertText");
                var emojiEl = audioWarning ? audioWarning.querySelector(".audio-emoji") : null;
                var emoji = "😷";
                var rawEv = (data["event"] || "").replace(/_/g, " ");
                var label = rawEv ? rawEv.charAt(0).toUpperCase() + rawEv.slice(1) : "Event";
                var sevLabel = (data["severityLabel"] || "").toLowerCase();
                var sevNum = data["severity"];
                var band = sevLabel;
                if (!band && typeof sevNum === "number") {
                    if (sevNum >= 5) band = "severe";
                    else if (sevNum >= 4) band = "moderate";
                    else if (sevNum >= 2) band = "mild";
                }
                var sev = band || (typeof sevNum === "number" ? String(sevNum) : "");
                var severityText = (data["severityLabel"] || sev) ? " — " + (data["severityLabel"] || ("level " + sevNum)) : "";
                var line = label + " detected!" + severityText + " (confidence: " + data["confidence"] + ")";
                if (emojiEl) emojiEl.textContent = emoji;
                if (audioAlertText) audioAlertText.textContent = line;
                if (audioWarning) {
                    audioWarning.style.display = "flex";
                    audioWarning.style.background = band === "severe" ? "rgba(220,50,50,0.95)" :
                        band === "moderate" ? "rgba(255,140,0,0.93)" : "rgba(255,180,0,0.9)";
                }
                var lastEv = document.getElementById("respiratoryLastEvent");
                if (lastEv) {
                    var t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
                    lastEv.textContent = line + " @ " + t;
                }
                var rss = document.getElementById("respiratoryStatus");
                if (rss) rss.textContent = "Last: " + label + (severityText ? " (" + (data["severityLabel"] || sev) + ")" : "");
                console.log("Audio event:", data["event"], "conf:", data["confidence"], "severity:", data["severity"], data["severityLabel"]);
                if (audioWarning) {
                    clearTimeout(window.__audioWarningTimer);
                    window.__audioWarningTimer = setTimeout(function () {
                        audioWarning.style.display = "none";
                    }, 8000);
                }
            }

            // Phase 6: allergen alert / clear (_state 8)
            if (data["_state"] == 8) {
                if (data["alert_triggered"] === false) {
                    if (typeof window.__cammy_clear_allergen_alert === "function") {
                        window.__cammy_clear_allergen_alert(data);
                    }
                } else if (typeof window.__cammy_handle_allergen_alert === "function") {
                    window.__cammy_handle_allergen_alert(data);
                }
            }

        }
        window.onbeforeunload = function () {
            console.log("closed-----------")
            socket.close();
        };
    }
    socket.onclose = function (event) {
        console.log('WebSocket connection closed');
        // clearInterval(intervalId); 
        if (animationFrameId !== null) {
            window.cancelAnimationFrame(animationFrameId);
            animationFrameId = null;
        }
        // connect();
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
    var videoConstraints = { width: { ideal: 1920 }, height: { ideal: 1080 } };
    if (selectedDeviceId) videoConstraints.deviceId = { exact: selectedDeviceId };
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
        }).catch(function (err) {
            console.error(err);
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
    let lastCaptureTime = Date.now();
    var foodCaptureMs = (typeof window.__CAMMY_FOOD_CAPTURE_MS__ === "number" && window.__CAMMY_FOOD_CAPTURE_MS__ >= 500)
        ? window.__CAMMY_FOOD_CAPTURE_MS__
        : 800;

    function capture() {
        // videoWidth/videoHeight may be 0 right after stream starts; wait until ready.
        if (!video || !video.videoWidth || !video.videoHeight) {
            animationFrameId = window.requestAnimationFrame(capture);
            return;
        }

        // Full frame only — child and food anywhere in view (no region crops).
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

        const now = Date.now();
        if (now - lastCaptureTime > foodCaptureMs) {
            context.clearRect(0, 0, canvas.width, canvas.height);
            context.drawImage(video, 0, 0, vw, vh, 0, 0, cropWidth, cropHeight);

            const frame = canvas.toDataURL('image/jpeg', 0.82);
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
        sender.track.stop();
    });
    setTimeout(function () {
        pc.close();
    }, 500);
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