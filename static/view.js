
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
var common_nutri = ["calories", "protein", "carbs", "fat", "fiber", "sugar", "sodium", "cholesterol", "saturatedFat"]


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
                delete data._state;

                var maxScore = 0;
                var maxEmotion = '';
                for (var emotion in data) {
                    emotionLower = emotion.toLowerCase();
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
                var food_lists = data["food_list"]

                // foodlog.innerText = JSON.stringify(food_lists)
                // foodState.innerText = main_foods + ' ' + food_lists[main_foods]

                mainFood.innerText = main_foods
                mainFoodVal.innerText = food_lists[main_foods]

                let dairy_array = ["milk", "cheese", "yogurt", "butter", "cream"]
                if (dairy_array.includes(main_foods)) {
                    main_foods = "dairy";
                }
                else if (main_foods.includes("bean")) {
                    main_foods = "bean";
                }

                let foodInfo = foodData.find(food => food.name === main_foods.toLowerCase());
                if (!foodInfo)
                    foodInfo = foodData[0]

                let total_score = 0
                common_nutri.forEach(function (item) {
                    nutri_items[item].innerText = foodInfo[item]
                    total_score += foodInfo[item] * nutri_weights[item]
                });

                nutri_items["indiv"].innerText = JSON.stringify(food_lists)

                percentage_val.innerText = parseInt(total_score / 188 * 100) + "%";
                percentage_bar.value = parseInt(total_score / 188 * 100)
                progress_bar.style.width = parseInt(total_score / 188 * 100) + '%';

                let value = total_score / 188 * 100
                let color = '';
                if (value <= 20) {
                    color = 'linear-gradient(270deg, #FFFFFF 1.86%, #FF0000 97.39%)';
                } else if (value > 20 && value <= 40) {
                    color = 'linear-gradient(270deg, #FFFFFF 1.86%, #FF0000 97.39%)';
                } else if (value > 40 && value < 50) {
                    color = 'linear-gradient(270deg, #FFFFFF 1.86%, #FF0000 97.39%)';
                } else if (value >= 50) {
                    color = 'linear-gradient(90deg, #FFFFFF 1.86%, #ADFF00 97.39%)';
                } else {
                    // Handle other cases if needed
                    color = 'linear-gradient(270deg, #FFFFFF 1.86%, #ADFF00 97.39%)';
                }
                progress_bar.style.background = color;

                if (main_foods != "grape") {
                    footerA.style.display = "flex"
                    footerB.style.display = "none"
                }
                else {
                    footerB.style.display = "flex"
                    footerA.style.display = "none"
                }

                // nutrilog.innerText = ""
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
                let nutri_info = JSON.stringify(data["result"]);
                // console.log("Nutri info--------", nutri_info)
                nutrilog.innerText = nutri_info
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


let nutri_weights = {
    "calories": 1,
    "protein": 2,
    "carbs": 1,
    "fat": 1,
    "fiber": 3,
    "sugar": -1,
    "sodium": -2,
    "cholesterol": -1,
    "saturatedFat": -1
}


let foodData = [
    {
        "name": "other",
        "calories": 62,
        "protein": 0.6,
        "carbs": 15,
        "fat": 0.3,
        "fiber": 0.8,
        "sugar": 14,
        "sodium": 2,
        "cholesterol": 0,
        "saturatedFat": 0
    },
    {
        "name": "apple",
        "calories": 95,
        "protein": 0.5,
        "carbs": 25,
        "fat": 0.3,
        "fiber": 4.4,
        "sugar": 19,
        "sodium": 2,
        "cholesterol": 0,
        "saturatedFat": 0
    },
    {
        "name": "banana",
        "calories": 105,
        "protein": 1.3,
        "carbs": 27,
        "fat": 0.4,
        "fiber": 3.1,
        "sugar": 14,
        "sodium": 1,
        "cholesterol": 0,
        "saturatedFat": 0
    },
    {
        "name": "grape",
        "calories": 62,
        "protein": 0.6,
        "carbs": 15,
        "fat": 0.3,
        "fiber": 0.8,
        "sugar": 14,
        "sodium": 2,
        "cholesterol": 0,
        "saturatedFat": 0

    },
    {
        "name": "nut",
        "calories": 161,
        "protein": 7,
        "carbs": 4,
        "fat": 14,
        "fiber": 2,
        "sugar": 1,
        "sodium": 5,
        "cholesterol": 0,
        "saturatedFat": 0
    },
    {
        "name": "dairy",
        "calories": 103,
        "protein": 8,
        "carbs": 12,
        "fat": 2.4,
        "fiber": 0,
        "sugar": 12,
        "sodium": 107,
        "cholesterol": 12,
        "saturatedFat": 1.5
    },
    {
        "name": "beans",
        "calories": 80,
        "protein": 7,
        "carbs": 10,
        "fat": 4,
        "fiber": 1,
        "sugar": 7,
        "sodium": 85,
        "cholesterol": 1,
        "saturatedFat": 1
    },
    {
        "name": "strawberry",
        "calories": 50,
        "protein": 1,
        "carbs": 11,
        "fat": 0.5,
        "fiber": 3,
        "sugar": 7,
        "sodium": 1,
        "cholesterol": 0,
        "saturatedFat": 0
    },
    {
        "name": "chocolate",
        "calories": 150,
        "protein": 3,
        "carbs": 15,
        "fat": 20,
        "fiber": 3,
        "sugar": 15,
        "sodium": 10,
        "cholesterol": 5,
        "saturatedFat": 7
    },
    {
        "name": "almond",
        "calories": 160,
        "protein": 6,
        "carbs": 6,
        "fat": 14,
        "fiber": 4,
        "sugar": 2,
        "sodium": 0.5,
        "cholesterol": 0,
        "saturatedFat": 1.5
    },
    {
        "name": "cookie",
        "calories": 100,
        "protein": 2,
        "carbs": 15,
        "fat": 6,
        "fiber": 1,
        "sugar": 8,
        "sodium": 100,
        "cholesterol": 5,
        "saturatedFat": 2
    }
];  