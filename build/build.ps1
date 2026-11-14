# .\build\build.ps1 [-Out <folder>] [-Venv <folder>]
param(
    [string]$Out = (Join-Path $PSScriptRoot "..\dist"),
    [string]$Venv = (Join-Path $PSScriptRoot "venv")
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not (Test-Path (Join-Path $Root "mogi_tracker\model\rec.onnx"))) {
    throw "mogi_tracker\model\rec.onnx is missing. The OCR model is not part of the source code (see the README), so put it there first."
}

$Python = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Python)) {
    python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "could not create the build environment in $Venv" }
}
$env:PIP_CACHE_DIR = Join-Path $Venv "pip-cache"
& $Python -m pip install --quiet --disable-pip-version-check -r (Join-Path $Root "requirements.txt") pyinstaller onnx
if ($LASTEXITCODE -ne 0) { throw "installing the build dependencies failed" }

& $Python (Join-Path $PSScriptRoot "pack_model.py")
if ($LASTEXITCODE -ne 0) { throw "packing the model failed" }
# onnx is only needed to stamp the model: take it out again so it is not counted (or bundled) as part of the app
& $Python -m pip uninstall --quiet --yes onnx protobuf ml_dtypes 2>$null
& $Python (Join-Path $PSScriptRoot "make_notices.py")
if ($LASTEXITCODE -ne 0) { throw "collecting the licence notices failed" }

& $Python -m PyInstaller (Join-Path $PSScriptRoot "mogi_tracker.spec") --noconfirm --distpath $Out --workpath (Join-Path $Out "work")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Copy-Item (Join-Path $PSScriptRoot "notices\THIRD_PARTY_NOTICES.txt") $Out -Force
Write-Host "Built: $(Join-Path $Out 'MKWorldMogiTracker.exe') (attach THIRD_PARTY_NOTICES.txt to the release next to it)"
