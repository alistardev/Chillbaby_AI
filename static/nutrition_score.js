/**
 * Shared nutrition display + health score (no hardcoded foodData).
 * Loaded before detail.js / view.js.
 */
(function (global) {
    "use strict";

    var COMMON_KEYS = [
        "calories", "protein", "carbs", "fat", "fiber",
        "sugar", "sodium", "cholesterol", "saturatedFat"
    ];

    var NUTRI_WEIGHTS = {
        calories: 1,
        protein: 2,
        carbs: 1,
        fat: 1,
        fiber: 3,
        sugar: -1,
        sodium: -2,
        cholesterol: -1,
        saturatedFat: -1
    };

    /** Rough per-meal references (same order of magnitude as one plate). Used only for scoring. */
    var MEAL_REF = {
        calories: 650,
        protein: 28,
        carbs: 70,
        fat: 25,
        fiber: 8,
        sugar: 24,
        sodium: 800,
        cholesterol: 90,
        saturatedFat: 9
    };

    function clearNutritionCells(nutriItems, keys, useBlank) {
        var ks = keys || COMMON_KEYS;
        var text = useBlank ? "" : "--";
        ks.forEach(function (k) {
            if (nutriItems[k]) nutriItems[k].innerText = text;
        });
    }

    function parseColonPairs(text) {
        var out = {};
        if (!text || typeof text !== "string") return out;
        var re = /([A-Za-z][A-Za-z _\-]+)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(?:g|mg|kcal|cal)?/gi;
        var m;
        while ((m = re.exec(text)) !== null) {
            var name = m[1].replace(/[\-_]+/g, " ").trim().toLowerCase().replace(/\s+/g, "_");
            var val = parseFloat(m[2]);
            if (!isNaN(val)) out[name] = val;
        }
        return out;
    }

    function normalizeNutritionKeys(raw) {
        var aliasToCanon = {
            calories: "calories", calorie: "calories", energy: "calories", kcal: "calories",
            total_calories: "calories",
            protein: "protein", protein_g: "protein",
            carbs: "carbs", carbohydrate: "carbs", carbohydrates: "carbs", total_carbohydrate: "carbs",
            fat: "fat", total_fat: "fat",
            fiber: "fiber", dietary_fiber: "fiber",
            sugar: "sugar", sugars: "sugar", total_sugars: "sugar",
            sodium: "sodium", salt: "sodium",
            cholesterol: "cholesterol",
            saturated_fat: "saturatedFat",
            saturatedfat: "saturatedFat",
            sat_fat: "saturatedFat"
        };
        var out = {};
        if (!raw || typeof raw !== "object") return out;
        Object.keys(raw).forEach(function (k) {
            var sk = String(k).trim().toLowerCase().replace(/[\s\-]+/g, "_");
            var canon = aliasToCanon[sk];
            if (!canon) return;
            var v = raw[k];
            var n = typeof v === "number" ? v : parseFloat(String(v).replace(/[^\d.\-]/g, ""));
            if (isNaN(n)) return;
            out[canon] = n;
        });
        return out;
    }

    function mergeNutrition(apiObj, resultStr) {
        var a = normalizeNutritionKeys(apiObj || {});
        var b = normalizeNutritionKeys(parseColonPairs(resultStr || ""));
        var merged = {};
        COMMON_KEYS.forEach(function (k) {
            if (typeof a[k] === "number" && !isNaN(a[k])) merged[k] = a[k];
            else if (typeof b[k] === "number" && !isNaN(b[k])) merged[k] = b[k];
        });
        return merged;
    }

    function formatCellValue(key, val) {
        if (typeof val !== "number" || isNaN(val)) return "--";
        if (key === "calories") return String(Math.round(val));
        if (key === "sodium" || key === "cholesterol") return String(Math.round(val));
        var t = Math.round(val * 10) / 10;
        return String(t);
    }

    /**
     * 0–100 composite from weighted nutrient ratios vs MEAL_REF.
     * Higher ≈ more favorable balance for this UI (not medical advice).
     */
    function computeHealthPercent(nutrition) {
        var n = 0;
        var d = 0;
        COMMON_KEYS.forEach(function (k) {
            var v = nutrition[k];
            if (typeof v !== "number" || isNaN(v)) return;
            var ref = MEAL_REF[k] || 1;
            var t = Math.min(Math.max(v / ref, 0), 2.5);
            var w = NUTRI_WEIGHTS[k] || 0;
            d += Math.abs(w);
            if (w > 0) {
                if (k === "calories") {
                    var ideal = 0.85;
                    var closeness = 1 - Math.min(Math.abs(t - ideal), 0.85) / 0.85;
                    n += w * Math.max(0, closeness);
                } else {
                    n += w * Math.min(t, 1.15);
                }
            } else {
                n += w * Math.min(t, 1.2);
            }
        });
        if (d < 1e-6) return null;
        var raw = (n / d + 0.35) * 55;
        return Math.max(0, Math.min(100, Math.round(raw)));
    }

    function scoreGradientStyle(percent) {
        var value = percent;
        if (value <= 20) {
            return "linear-gradient(270deg, #FFFFFF 1.86%, #FF0000 97.39%)";
        }
        if (value > 20 && value <= 40) {
            return "linear-gradient(270deg, #FFFFFF 1.86%, #FF0000 97.39%)";
        }
        if (value > 40 && value < 50) {
            return "linear-gradient(270deg, #FFFFFF 1.86%, #FF0000 97.39%)";
        }
        if (value >= 50) {
            return "linear-gradient(90deg, #FFFFFF 1.86%, #ADFF00 97.39%)";
        }
        return "linear-gradient(270deg, #FFFFFF 1.86%, #ADFF00 97.39%)";
    }

    /**
     * Fill macro cells, optional log, progress bar from merged nutrition object.
     */
    function applyNutritionToUI(nutrition, nutriItems, nutrilog, percentageVal, percentageBar, progressBar) {
        COMMON_KEYS.forEach(function (k) {
            if (!nutriItems[k]) return;
            nutriItems[k].innerText = formatCellValue(k, nutrition[k]);
        });
        var pct = computeHealthPercent(nutrition);
        if (pct === null) {
            if (percentageVal) percentageVal.innerText = "--";
            if (percentageBar) percentageBar.value = 0;
            if (progressBar) {
                progressBar.style.width = "0%";
                progressBar.style.background = "linear-gradient(270deg, #FFFFFF 1.86%, #B0B0B0 97.39%)";
            }
            return;
        }
        if (percentageVal) percentageVal.innerText = pct + "%";
        if (percentageBar) percentageBar.value = pct;
        if (progressBar) {
            progressBar.style.width = pct + "%";
            progressBar.style.background = scoreGradientStyle(pct);
        }
        if (nutrilog) {
            try {
                nutrilog.innerText = JSON.stringify(nutrition);
            } catch (e) {
                nutrilog.innerText = "";
            }
        }
    }

    global.CammyNutrition = {
        COMMON_KEYS: COMMON_KEYS,
        NUTRI_WEIGHTS: NUTRI_WEIGHTS,
        clearNutritionCells: clearNutritionCells,
        mergeNutrition: mergeNutrition,
        applyNutritionToUI: applyNutritionToUI,
        computeHealthPercent: computeHealthPercent,
        scoreGradientStyle: scoreGradientStyle
    };
})(typeof window !== "undefined" ? window : this);
