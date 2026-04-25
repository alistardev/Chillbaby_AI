var nutriRange = document.getElementById('nutriRange'),
nutriRangeValue = document.getElementById('percentage'),
progress = document.getElementById('progress');

var poller = null;

scale = function (value, src_low, src_high, dest_low, dest_high) {
var pre_mapping;
pre_mapping = (value - src_low) / (src_high - src_low);
return pre_mapping * (dest_high - dest_low) + dest_low;
};

var scaleValue = function (value) {
var low = 0,
  high = 100 - low;

return scale(value, 0, 100, low, high);
};

var asPercent = function (value) {
return parseInt(value) + '%';
};

var setValue = function () {
var value = nutriRange.value;
var percentageValue = scaleValue(value);

progress.style.width = asPercent(percentageValue);
nutriRangeValue.innerHTML = asPercent(percentageValue);
};

var startPolling = function () {
poller = setInterval(function () {
  setValue();
}, 15);
};

var stopPolling = function () {
clearInterval(poller); // Fix: Use clearInterval instead of clearTimeout
};

nutriRange.addEventListener('mousedown', function () {
startPolling();
}, true);

nutriRange.addEventListener('mouseup', function () {
stopPolling();
}, true);

setValue();
nutriRange.addEventListener('input', updateColor);

const percentageSpan = document.getElementById('percentage');
percentageSpan.textContent = nutriRange.value + '%';

function updateColor() {
const value = parseFloat(nutriRange.value);
percentageSpan.textContent = value + '%';
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

progress.style.width = nutriRange.value + '%';
progress.style.background = color;
}