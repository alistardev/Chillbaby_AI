# Cammy / Chillbaby AI — Codebase review (Q&A)

Reference notes from a structured review of the repository: architecture, gaps, and roadmap alignment.

---

## 1. Eleven hardcoded foods and generic “other” — scaling plan?

**Behavior:** The nutrition **score** UI in `static/detail.js` and `static/view.js` uses a fixed `foodData` array. The first entry is `"other"` (fallback). If the detected food name does not match any row, the code uses `foodData[0]` — so scoring uses **“other”** macros.

**Documented direction:** `cammyproject_steps.md` **Phase 5** plans to replace free-text nutrition lookup with a **structured nutrition database or API** and fuller food diary logging. That is the main roadmap statement for scaling; it is not fully implemented in code yet.

**Backend:** Food recognition is **local-first** with optional Clarifai (`README.md`, `services/food.py`). The small frontend `foodData` table is separate and not auto-expanded from the model.

---

## 2. Clarifai, Azure OpenAI, MongoDB — what works offline?

**Context:** Inference runs on the host that executes `chillapp.py` (WebRTC server processes video/audio). The browser is primarily capture and UI.

| Component | Network when used | Notes |
|-----------|-------------------|--------|
| **Clarifai** | Yes (API mode) | Optional: without API keys, README documents **fully local** food path. |
| **Azure OpenAI** | Yes | If `OPENAI_API_KEY` is empty, `nutrition_info` in `services/nutrition.py` returns `{}` and skips the call. |
| **MongoDB** | Reachable `DB_URL` | Login and many flows expect Mongo; failures are logged but session fields like `insertedId` may not work. |
| **PANNs (first run)** | Yes (download) | ~330 MB labels/weights unless pre-staged (`README.md`). |

The repo does **not** promise a fully offline product. Closest: local food + no Azure key; Mongo and initial model downloads still matter for typical operation.

---

## 3. Stack weight (PyTorch, YOLO, PANNs, FER, MediaPipe, many pip packages) — minimum RAM/storage?

**Finding:** There is **no** documented minimum RAM, CPU, or disk for target hardware in the repo.

**Inference:** Expect **multi-GB disk** (venv, PyTorch, YOLO weights, PANNs ~330 MB, optional food `.pt` files — some weights are gitignored) and **several GB RAM** for comfortable **CPU** inference with multiple models; exact needs depend on GPU, concurrency, and tuning.

A large transitive dependency count (e.g. hundreds of packages from a full `pip freeze`) is an environment observation, not a spec in this repository.

---

## 4. `detail.js` vs `view.js` duplication

Both files duplicate **food data**, **nutrition scoring**, and **WebSocket** handling patterns.

**Plan in repo:** No dedicated plan to merge them (no shared module or build step documented). `cammyproject_steps.md` Phase 1 discusses **Python** global state vs per-connection sessions; it does not address JS deduplication.

---

## 5. `cert.pem` and `key.pem`

`.gitignore` lists `cert.pem` and `key.pem` with a note that dev-only certs could be versioned intentionally. **If these files are still tracked in git** (`git ls-files`), remove them from the index (`git rm --cached`) so secrets/dev certs are not in history going forward; use environment-specific certificates on each deployment.

---

## 6. `connections` and `globalvars` — single logical session

`app_state.AppState` holds one shared `globalvars` dict for the entire application while `connections` is keyed by WebSocket token.

**Effect:** Session fields (`insertedId`, `mainFood`, `processing`, etc.) are **global**, not per user/token — so **multiple concurrent independent sessions** are not safely supported.

**Roadmap:** `cammyproject_steps.md` Phase 1 calls for replacing globals with **session management tied to individual connections**. Current code centralizes state in `AppState` but does not complete per-session isolation.

---

## General questions (short answers from the codebase)

| Topic | Answer |
|--------|--------|
| **Target camera hardware** | Not fully specified. `services/domain_writes.py` defaults `device_type` to `"T40"`; Phase 8 mentions T40 for future temperature integration. |
| **Offline vs network** | Practical assumption: network for Mongo and first-time downloads; Clarifai/Azure optional per README / `nutrition.py`. |
| **Clarifai long-term** | Code is local-first + optional Clarifai. Phase 5 mentions Foodvisor and VLM ideas; Foodvisor URL exists in `config.py` but the main food path does not call Foodvisor. |
| **Food types / “other” logging** | Clarifai returns model-dependent concepts; server logs food at INFO. No dedicated metric for frontend `foodData` match vs `"other"` fallback. |
| **Multi-user / multi-camera** | Roadmap aims at per-connection sessions; current `globalvars` design favors a **single** logical session. |
| **Deployment** | `UBUNTU_SETUP.md` (systemd, Mongo, venv); Windows `bootstrap.ps1` / `run.ps1` / `dev.ps1`. No described OTA for edge devices. |
| **Roadmap / spec** | Primary: `cammyproject_steps.md`. Also `implementation.txt`, `README.md` phase bullets. |

---

## Related files

- `README.md` — setup, env profiles, food provider modes  
- `implementation.txt` — phase status, remaining work, client confirmation questions  
- `.env.local.example` / `.env.server.example` — environment templates  
- `app_state.py` — shared runtime state (single logical session today)  
- `services/food.py` — local + Clarifai pipeline  
- `services/nutrition.py` — Azure OpenAI nutrition  
- `db.py`, `services/domain_writes.py` — persistence and domain writes  
