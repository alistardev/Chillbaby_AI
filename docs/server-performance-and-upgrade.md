# Why the server feels slow (4 CPU / 16 GB, no GPU)

Your VPS specs look reasonable on paper. The delay is not because 16 GB RAM is too small — it is because **several AI models run on CPU at the same time**, and each frame takes real compute.

## What runs during one live session

| Task | Model / stack | Typical CPU time per run |
|------|----------------|-------------------------|
| Food detection | YOLO (`food_detector.pt`, sometimes + `yolov8m`) | ~0.8–2.5 s |
| Emotion (face) | FER (PyTorch + face backend) | ~0.5–2 s |
| Child in frame | YOLO (`yolov8n`) | ~0.2–0.8 s |
| Cough / sneeze | PANNs (PyTorch) | small, but continuous |
| Optional | Clarifai API when local is unsure | + network 0.5–3 s |

All of that shares **the same 4 vCPUs**. Only one heavy job uses the CPU fully at a time, but they **queue behind each other**, so the caregiver sees “a few seconds” after changing a slide.

## Why “4 CPU / 16 GB” is still slow

1. **No GPU** — YOLO and FER are built for GPU; on CPU they are often **5–15× slower** than on a small GPU (T4 class).

2. **vCPU ≠ fast desktop CPU** — Many cloud “4 CPU” plans are **shared cores** at ~2.0–2.5 GHz, not four fast dedicated cores. Inference cares about **single-thread speed** as much as core count.

3. **Several models loaded at once** — PyTorch (food + child + audio) and FER’s stack can use **several GB RAM**; 16 GB is enough, but **CPU is the bottleneck**.

4. **Food can run two YOLO passes** — custom `food_detector.pt`, then COCO `yolov8m` when the first pass is weak. That can **double** food latency on CPU.

5. **Clarifai when local is empty** — network round-trip adds seconds; fine for accuracy, bad for “instant” feel.

6. **WebRTC + JPEG upload + MongoDB** — smaller cost, but add jitter on a busy VPS.

So: the server is not “broken”; it is doing **real-time computer vision on CPU**, which is inherently seconds-scale unless tuned or given a GPU.

## What “good” looks like on this hardware (realistic)

| Scenario | Food label after slide change | Emotion update |
|----------|------------------------------|----------------|
| Current tuned server (CPU) | ~1.5–3 s | ~1–2 s |
| Your Windows dev PC (often faster CPU) | ~0.5–1.5 s | ~0.5–1 s |
| Same app on **GPU VPS** (e.g. T4) | ~0.3–0.8 s | ~0.3–1 s |

Sub-second everything on CPU for **all** features at once is not realistic without trade-offs (lower resolution, fewer models, or skip Clarifai).

---

## Maximum speed on the **current** server (no upgrade)

Apply in `.env` on Ubuntu (`CAMMY_PROFILE=server`), then restart the app and hard-refresh the browser.

```env
# Skip cloud food API — fastest path
FOOD_PROVIDER=local

# Smaller images = faster YOLO/FER
FOOD_CANVAS_MAX_DIM=448
LOCAL_FOOD_PREDICT_IMGSZ=256
LOCAL_FOOD_UPSCALE_MAX_DIM=416
FER_MAX_DIM=256

# Faster client upload on scene change (needs detail.js v14+)
FOOD_CAPTURE_INTERVAL_S=1.0
FOOD_CAPTURE_CHANGE_MIN_S=0.4

# Avoid second heavy YOLO (yolov8m) when possible — use lighter COCO if you keep fallback
LOCAL_FOOD_COCO_FALLBACK_PATH=yolov8n.pt
LOCAL_FOOD_TRUST_CUSTOM=0.25
CLARIFAI_WHEN_LOCAL_EMPTY=never

# Less duplicate work
FOOD_MIN_INTERVAL_S=0.5
EMOTION_INTERVAL_S=1.0
YOLO_DETECT_EVERY_N=45
```

Optional OS tuning (once per server):

```bash
# In systemd service or before start — use all 4 cores for PyTorch/OpenMP
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
```

**Trade-off:** slightly lower detection quality on hard foods / small objects; much snappier UI.

---

## Should the client upgrade the server?

### Worth it

| Upgrade | Effect | Rough guidance |
|---------|--------|----------------|
| **GPU instance** (NVIDIA T4, L4, or similar) | Largest gain for food + emotion | Best choice if “fast like an app” is required |
| **Fewer, faster CPU cores** (dedicated CPU or high GHz) | Moderate gain (20–40%) | e.g. 2–4 dedicated cores @ 3+ GHz |
| **Same box, better tuning** | Moderate gain (already partly done) | Free; see env block above |

### Usually not worth it alone

| Upgrade | Why |
|---------|-----|
| **16 GB → 32 GB RAM** | RAM is rarely the limit |
| **4 → 8 vCPU** on same slow shared chips | Little gain if jobs are single-threaded |
| **Bigger disk / bandwidth** | Does not speed inference |

### Practical recommendation to tell the client

> “The app runs four AI tasks on the server CPU at once. Your 16 GB RAM is fine; the limit is **no GPU** and **CPU inference time**. We can tune further for ~1–3 s food updates on the current box. For **near–real-time** (under ~1 s) for food and emotions together, a **small GPU cloud server** (or a dedicated-CPU plan with higher clock) is the right upgrade — not just more RAM or more slow vCPUs.”

Example directions (prices vary by region):

- **Budget GPU:** cloud VM with 1× T4 / L4 (often the best $/performance for this stack).
- **CPU-only:** dedicated CPU VPS (Hetzner, OVH, etc.) if they want to avoid GPU cost — expect improvement, not magic.

---

## Short answers for client questions

**“Why is it slow with 4 CPU and 16 GB?”**  
Because food and emotion use heavy neural networks on **CPU only**, and they run one after another on the same machine.

**“Can we make it as fast as possible without upgrading?”**  
Yes — local-only food, smaller frames, lighter YOLO fallback, scene-change upload (already in app). Expect **~1–3 s**, not instant.

**“Should we buy a better server?”**  
If they need **consistently under ~1 s**, recommend a **GPU instance**. If **2–3 s is OK**, tuning the current server may be enough.

---

*Internal reference: `CAMMY_PROFILE=server` in `.env.server.example`, `config.py` presets, `services/food.py`, `services/video_track.py`.*
