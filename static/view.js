
let peerC = null;
var dc = null, dcInterval = null;

var blob, deviceRecorder = null;
var chunks = [];


var emo_items = {}
emo_items["happy"] = document.getElementById("happy");
emo_items["angry"] = document.getElementById("angry");
emo_items["disgust"] = document.getElementById("disgust");
emo_items["fear"] = document.getElementById("fear");
emo_items["sad"] = document.getElementById("sad");
emo_items["surprise"] = document.getElementById("surprise");
emo_items["neutral"] = document.getElementById("neutral");

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

document.addEventListener("DOMContentLoaded", function () {
    connect_view();
});

// window.addEventListener('load', connect);



var waringrect = document.getElementById("warningfood")
let footerA = document.getElementById('footer_slide')
let footerB = document.getElementById('footer_slide_choking')

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


function connect_view() {
    console.log(uuid);

    // var socket = new WebSocket(`wss://localhost:8000/chill_view?token=${uuid}`);  
    // let socket = new WebSocket(`wss://40.90.233.137:8080/chill_view?token=${uuid}`); 
    let socket = new WebSocket(`wss://${window.location.host}/chill_view?token=${uuid}`);
    socket.onopen = function (event) {
        console.log('WebSocket connection established');

        fetchWeatherData();
        updateTime();

        // setTimeout(function() {
        //     showVideo();
        // }, 3000);
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
            console.log(txt[1])
        }
        else if (txt[0] === "endRec") {
            console.log("recording ended")
            stopView()
        }
        else if (txt[0] === "endPro") {
            console.log("recording processing")
        }
        else if (txt[0] === "name") {
            let displayname = document.getElementById('displayname')
            displayname.innerText = txt[1]
            let company = document.getElementById('companyName')
            company.innerText = txt[2]
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
                    emo_items[emotionLower].innerText = data[emotion]
                    if (data[emotion] > maxScore) {
                        maxScore = data[emotion];
                        maxEmotion = emotion;
                    }
                }

                maxEmotion = maxEmotion.toLowerCase();
                maxEmo.innerText = maxEmotion
                maxEmoVal.innerText = maxScore
                // emoState.innerText = maxEmotion.charAt(0).toUpperCase() + maxEmotion.slice(1) + ' ' + maxScore 

                // let jsonString = JSON.stringify(data);
                // emolog.innerText = jsonString;

            }
            if (data["_state"] == 2) {
                var main_foods = data["food_main"]
                var food_lists = data["food_list"] || {}
                var noFood = data["food_cleared"] || !main_foods
                    || main_foods === "unknown_food" || main_foods === "mixed_food"

                if (noFood) {
                    mainFood.innerText = ""
                    mainFoodVal.innerText = ""
                    if (typeof CammyNutrition !== "undefined") {
                        CammyNutrition.clearNutritionCells(nutri_items, common_nutri, true);
                    } else {
                        common_nutri.forEach(function (item) {
                            if (nutri_items[item]) nutri_items[item].innerText = "";
                        });
                    }
                    if (nutri_items["indiv"]) nutri_items["indiv"].innerText = "";
                    if (typeof nutrilog !== "undefined" && nutrilog) nutrilog.innerText = "";
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
                        nutri_items[item].innerText = "--";
                    });
                }
                nutri_items["indiv"].innerText = JSON.stringify(food_lists);
                percentage_val.innerText = "--";
                percentage_bar.value = 0;
                progress_bar.style.width = "0%";
                progress_bar.style.background = "linear-gradient(270deg, #FFFFFF 1.86%, #B0B0B0 97.39%)";

                var rawMainV = String(main_foods || "").toLowerCase();
                if (rawMainV.indexOf("grape") !== -1) {
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
                if (data["result"].toLowerCase().includes("yes"))
                    waringrect.style.display = "block"
                else
                    waringrect.style.display = "none"

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
                    if (typeof nutrilog !== "undefined" && nutrilog) nutrilog.innerText = "";
                    if (percentage_val) percentage_val.innerText = "";
                    if (percentage_bar) percentage_bar.value = 0;
                    if (progress_bar) {
                        progress_bar.style.width = "0%";
                        progress_bar.style.background = "linear-gradient(270deg, #FFFFFF 1.86%, #B0B0B0 97.39%)";
                    }
                    return;
                }
                if (typeof CammyNutrition !== "undefined") {
                    var mergedV = CammyNutrition.mergeNutrition(data["nutrition"], data["result"]);
                    CammyNutrition.applyNutritionToUI(mergedV, nutri_items, nutrilog, percentage_val, percentage_bar, progress_bar);
                    if (Object.keys(mergedV).length === 0 && data["result"]) {
                        nutrilog.innerText = typeof data["result"] === "string" ? data["result"] : JSON.stringify(data["result"]);
                    }
                } else {
                    nutrilog.innerText = typeof data["result"] === "string" ? data["result"] : JSON.stringify(data["result"]);
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
        // connect();
    };
}


function createPeerConnection() {
    var config = {
        sdpSemantics: 'unified-plan',
        //iceServers: [],
        iceServers: [
            {
                urls: "turn:a.relay.metered.ca:80?transport=tcp",
                username: "bcc3a585c8df20e4b5ffcc1a",
                credential: "pu2U+m9uaBqL+k7b",
            }
        ],
        //iceServers: [{urls: 'stun:your_own_stun_server:3478'},],
        //iceServers: [{urls: 'stun:your_own_stun_server:3478', credential: 'test', username: 'test'}],
        //iceCandidatePoolSize: 2
    };

    // var peerC = null;// new RTCPeerConnection(config);

    peerC = new RTCPeerConnection(config);

    peerC.addTransceiver('video', { direction: 'recvonly' });
    peerC.addTransceiver('audio', { direction: 'recvonly' });

    // connect audio / video
    peerC.addEventListener('track', function (evt) {
        if (evt.track.kind == 'video')
            document.getElementById('webcam').srcObject = evt.streams[0];
        else
            document.getElementById('audio').srcObject = evt.streams[0];
    });

    return peerC;
}

function negotiate_view() {

    console.log("------negotiate view------")

    return peerC.createOffer().then(function (offer) {
        return peerC.setLocalDescription(offer);
    }).then(function () {
        // wait for ICE gathering to complete
        return new Promise(function (resolve) {
            if (peerC.iceGatheringState === 'complete') {
                resolve();
            } else {
                function checkState() {
                    if (peerC.iceGatheringState === 'complete') {
                        peerC.removeEventListener('icegatheringstatechange', checkState);
                        resolve();
                    }
                }
                peerC.addEventListener('icegatheringstatechange', checkState);
            }
        });
    }).then(function () {
        var offer = peerC.localDescription;

        // document.getElementById('offer-sdp').textContent = offer.sdp;
        return fetch('/offer_view', {
            body: JSON.stringify({
                sdp: offer.sdp,
                type: offer.type,
            }),
            headers: {
                'Content-Type': 'application/json'
            },
            method: 'POST'
        });
    }).then(function (response) {
        return response.json();
    }).then(function (answer) {

        // document.getElementById('answer-sdp').textContent = answer.sdp;
        return peerC.setRemoteDescription(answer);
    }).catch(function (e) {
        alert(e);
    });
}

function showVideo() {
    console.log("starting -----show video")
    peerC = createPeerConnection();

    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        negotiate_view();
        stream.getTracks().forEach(function (track) {
            track.stop();   // don't use it at all
        });
    }, function (err) {
        alert('Could not acquire media: ' + err);
    });
}

async function startView() {
    document.getElementById('start').style.display = 'none';
    document.getElementById('stop').style.display = 'inline-block';

    showVideo();


    fetch('/startRec', {
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

    const displayMediaOptions = {
        video: {
            displaySurface: "browser",
        },
        audio: {
            suppressLocalAudioPlayback: false,
        },
        preferCurrentTab: true,
        // selfBrowserSurface: "exclude",
        // systemAudio: "include",
        // surfaceSwitching: "include",
        // monitorTypeSurfaces: "include",
    };

    var stream = await navigator.mediaDevices.getDisplayMedia(displayMediaOptions)
    deviceRecorder = new MediaRecorder(stream, { mimeType: "video/webm;codecs=h264" });
    deviceRecorder.ondataavailable = async (e) => {
        if (e.data.size > 0) {
            // chunks.push(e.data);
            let data = new FormData();
            data.append('file', e.data);
            await fetch('/uploadBlob', {
                method: 'POST',
                body: data
            });
        }
    }
    deviceRecorder.onstop = async () => {
        // let blob = new Blob(chunks, {type: 'video/webm'});  
        // let data = new FormData();  
        // data.append('file', blob);  
        // await fetch('/uploadBlob', {  
        //     method: 'POST',  
        //     body: data  
        // });  


        chunks = [];
    }
    deviceRecorder.start(3000)

}


function stopRec() {
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
}

function stopView() {
    document.getElementById('stop').style.display = 'none';
    document.getElementById('start').style.display = 'inline-block';

    filename = "record"
    deviceRecorder.stop(); // Stopping the recording



    // blob = new Blob(chunks, {type: "video/webm"})
    // var dataDownloadUrl = URL.createObjectURL(blob);
    // // Downloadin it onto the user's device
    // let a = document.createElement('a')
    // a.href = dataDownloadUrl;
    // a.download = `${filename}.webm`
    // a.click()


    // // close data channel
    // if (dc) {
    //     dc.close();
    // }

    // // close transceivers
    // if (peerC.getTransceivers) {
    //     peerC.getTransceivers().forEach(function(transceiver) {
    //         if (transceiver.stop) {
    //             transceiver.stop();
    //         }
    //     });
    // }

    // // close local audio / video
    // //peerC.getSenders().forEach(function(sender) {
    // //    sender.track.stop();
    // //});

    // // close peer connection
    // setTimeout(function() {
    //     peerC.close();
    // }, 500);
}