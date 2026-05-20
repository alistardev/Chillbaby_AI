# Food detection model (YOLO — detection)

Cammy loads **one Ultralytics detection checkpoint** (`.pt`). Class names are embedded in the checkpoint; optional sidecar files help humans debug.

## Download for local / client review (~329 MB)

Weights are not in git. Download **`food_detector.pt`** from Google Drive and place it in this folder:

- **Folder:** [food — Google Drive](https://drive.google.com/drive/folders/1uq5ZYzULasSR8PRsG6s9EufrXfazgtdR?usp=sharing)
- **Target path:** `models/food/food_detector.pt`
- **Expected size:** ~329 MB (if you see ~134 bytes, that is a broken/git-lfs stub — re-download from Drive)

See root **`README.md`** (sections 3 and 7) for Windows and Ubuntu setup.

## Automatic copy (no manual step)

If **`models/food/food_detector.pt`** is missing and **`CAMMY_AUTO_SYNC_FOOD_MODEL=1`** (default), the server startup copies the first file it finds from:

- `prepare_food_dataset/deploy_model/food_detector.pt`
- `prepare_food_dataset/runs/detect/runs/food_yolo11x_full/weights/best.pt` (or `last.pt`)

You can also run **`scripts/sync_food_model.ps1`** from the repo root.

Paths like `models/food/food_detector.pt` are resolved from the **repository root** (the folder that contains `config.py`), **not** from your shell’s current directory. That way `food_detector.pt` is found even if you start Python from another folder (which previously made the app fall back to `yolov8n-cls.pt`).

---

## Files to copy here (manual fallback)

After training or export from `prepare_food_dataset`, copy into **`models/food/`**:

| File | Required | Description |
|------|----------|-------------|
| **`food_detector.pt`** | **Yes** | Main weights. Use `deploy_model/food_detector.pt` **or** rename `runs/detect/runs/food_yolo11x_full/weights/best.pt` → `food_detector.pt`. |
| **`classes.txt`** | Optional | Label list (same order as training); useful for reference. Inference uses names inside the `.pt`. |
| **`category_mapping.json`** | Optional | Original category mapping from the dataset pipeline. |

> **Git:** `*.pt` is listed in `.gitignore`, so weights stay local — they are not committed.

Default config path: `LOCAL_FOOD_MODEL_PATH=models/food/food_detector.pt` (see root `.env.example`).

## Training progress

Training progress (e.g. 20 / 100 epochs) is visible in `prepare_food_dataset/train.log`. Prefer **`best.pt`** from the latest run for deployment; re-copy when training advances.

If you only have **`yolov8n-cls.pt`** (ImageNet classification) as fallback, the app now uses the **classification** branch (top‑k labels). That is **not** the same as your custom **detection** model; labels will be ImageNet English names (e.g. `pizza`, `orange`), not your Kaggle slug list. For production demo, use **`food_detector.pt`** (detect).

The Roboflow model is a convenient pretrained dataset export, but labels and coverage differ from **your Kaggle-trained YOLO11x** run (hundreds of fine-grained classes in `deploy_model/classes.txt`). Mixing checkpoints without aligning label spaces would confuse downstream nutrition/UI matching.

**Recommendation:** keep deploying **`food_detector.pt` / `best.pt` from your training** until benchmarks say otherwise. To try Roboflow later: download their `.pt`, drop it in as `food_detector.pt`, tune `LOCAL_FOOD_CONFIDENCE`, and re-test — no extra code path required.
