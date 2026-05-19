# Copy food YOLO weights into models/food/food_detector.pt (same rules as food_model_sync.py).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dest = Join-Path $root "models\food\food_detector.pt"
$sources = @(
    (Join-Path $root "prepare_food_dataset\deploy_model\food_detector.pt"),
    (Join-Path $root "prepare_food_dataset\runs\detect\runs\food_yolo11x_full\weights\best.pt"),
    (Join-Path $root "prepare_food_dataset\runs\detect\runs\food_yolo11x_full\weights\last.pt")
)
if (Test-Path -LiteralPath $dest) {
    Write-Host "Already exists: $dest"
    exit 0
}
foreach ($s in $sources) {
    if (Test-Path -LiteralPath $s) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
        Copy-Item -LiteralPath $s -Destination $dest -Force
        Write-Host "Copied: $s -> $dest"
        exit 0
    }
}
Write-Warning "No source weights found under prepare_food_dataset/. Train or copy a .pt manually."
exit 1
