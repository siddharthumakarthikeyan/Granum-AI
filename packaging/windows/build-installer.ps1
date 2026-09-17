# Build Granum for Windows as one installer: Python, every dependency, the dashboard and a
# Chromium-based window (Qt WebEngine), packed by Inno Setup into Granum-<version>-Setup.exe.
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build-installer.ps1
#   ... -Wheel path\to\granum-0.1.0-py3-none-any.whl   (skip building the dashboard and wheel)
#
# Needs: Windows 10/11 x64, internet, Inno Setup 6 (ISCC.exe), and Node.js 20+ unless -Wheel
# is given. Training (PyTorch) is not bundled; the app installs it on first use.
param(
    [string]$Wheel = "",
    [string]$PbsTag = "20260901",
    [string]$PyFull = "3.12.14",
    [string]$PySide = "6.10.*"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is many times slower with the progress bar

$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$Build = Join-Path $Repo "build\windows"
$Cache = Join-Path $Repo "build\cache\win"
$App = Join-Path $Build "Granum"
$Version = ((Select-String -Path "$Repo\pyproject.toml" -Pattern '^version = "(.*)"').Matches[0].Groups[1].Value)

function Say($text) { Write-Host "build " -ForegroundColor Cyan -NoNewline; Write-Host $text }

function Invoke-Checked {
    param([string]$Exe, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

function Get-Cached($url, $name) {
    $target = Join-Path $Cache $name
    if ((Test-Path $target) -and (Get-Item $target).Length -gt 0) { return $target }
    Say "downloading $name"
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile "$target.partial" -UseBasicParsing
            Move-Item -Force "$target.partial" $target
            return $target
        } catch {
            if ($attempt -eq 6) { throw }
            Start-Sleep -Seconds 5
        }
    }
}

New-Item -ItemType Directory -Force -Path $Cache, (Join-Path $Repo "dist") | Out-Null
if (Test-Path $App) { Remove-Item -Recurse -Force $App }
New-Item -ItemType Directory -Force -Path $App | Out-Null

# 1. A relocatable CPython.
$pbs = "cpython-$PyFull+$PbsTag-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
$archive = Get-Cached "https://github.com/astral-sh/python-build-standalone/releases/download/$PbsTag/$($pbs -replace '\+', '%2B')" $pbs
Invoke-Checked tar -xzf $archive -C $App
$Py = Join-Path $App "python\python.exe"
$env:PYTHONNOUSERSITE = "1"
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

# 2. The Granum wheel, with the dashboard inside.
if (-not $Wheel) {
    Say "building the dashboard"
    Push-Location "$Repo\web"
    try {
        Invoke-Checked npm ci --no-audit --no-fund
        Invoke-Checked npm run build
    } finally { Pop-Location }
    Say "building the granum wheel"
    $wheelDir = Join-Path $Build "wheel"
    if (Test-Path $wheelDir) { Remove-Item -Recurse -Force $wheelDir }
    Invoke-Checked $Py -m pip install --quiet --disable-pip-version-check build
    Invoke-Checked $Py -m build --wheel --outdir $wheelDir $Repo
    $Wheel = (Get-ChildItem "$wheelDir\granum-*.whl" | Select-Object -First 1).FullName
    Invoke-Checked $Py -m pip uninstall --quiet -y build pyproject_hooks
}
$Wheel = (Resolve-Path $Wheel).Path

# 3. Everything Granum needs, into the bundled Python.
Say "installing granum and its dependencies"
Invoke-Checked $Py -m pip install --quiet --disable-pip-version-check --no-warn-script-location `
    "$Wheel[service,images,pandas]" "PySide6-Essentials==$PySide" "PySide6-Addons==$PySide"
# The Microsoft Visual C++ 2015-2022 runtime beside python.exe (the program folder, which Windows
# always searches for DLLs). PyTorch and other add-on packages need it, and a fresh Windows may
# not have it; installing Microsoft's redistributable would need administrator rights.
Invoke-Checked $Py -m pip install --quiet --disable-pip-version-check --no-warn-script-location "msvc-runtime==14.44.*"
Get-ChildItem (Join-Path $App "python\Scripts\*.dll") -ErrorAction SilentlyContinue | Remove-Item -Force

# 4. Trim what an app never uses.
Say "trimming"
$pyRoot = Join-Path $App "python"
foreach ($extra in @("Lib\test", "Lib\idlelib", "Lib\tkinter", "Lib\turtledemo", "Lib\lib2to3", "Lib\ensurepip\_bundled",
                     "include", "tcl", "libs", "DLLs\_tkinter.pyd", "DLLs\tcl86t.dll", "DLLs\tk86t.dll")) {
    $path = Join-Path $pyRoot $extra
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}
Get-ChildItem -Path $pyRoot -Directory -Recurse -Include "__pycache__", "tests", "testing" -ErrorAction SilentlyContinue |
    Sort-Object { $_.FullName.Length } -Descending |
    ForEach-Object { if (Test-Path $_.FullName) { Remove-Item -Recurse -Force $_.FullName } }
$tools = Join-Path $Build "tools"
Invoke-Checked $Py -m pip install --quiet --disable-pip-version-check --upgrade --target $tools pefile
$env:PYTHONPATH = $tools
Invoke-Checked $Py "$Repo\packaging\windows\prune_qt.py" (Join-Path $pyRoot "Lib\site-packages\PySide6")
Remove-Item Env:PYTHONPATH

# Fail the build, not the user's first launch, if trimming broke anything.
Say "checking the bundle imports"
Invoke-Checked $Py -c "import PySide6.QtWebEngineWidgets, PySide6.QtWebEngineCore, granum.service.app, granum.cli.window, pandas, pyarrow, PIL, fastapi, uvicorn, pip; print('bundle imports ok')"

# 5. Precompile, so the first launch does not wait for bytecode.
Invoke-Checked $Py -m compileall -q -j 0 (Join-Path $pyRoot "Lib")

# 6. The launcher, icon and licence.
Say "making the launcher"
$ico = Join-Path $App "granum.ico"
Invoke-Checked $Py -c "import sys; from PIL import Image; Image.open(sys.argv[1]).save(sys.argv[2], sizes=[(16,16),(20,20),(24,24),(32,32),(40,40),(48,48),(64,64),(128,128),(256,256)])" `
    "$Repo\src\granum\assets\granum-256.png" $ico
Copy-Item "$Repo\LICENSE" (Join-Path $App "LICENSE.txt")
# Granum.exe is the windowed Python (no console) under Granum's name and icon, so the taskbar,
# Task Manager and "Open with" show Granum rather than Python.
$launcher = Join-Path $pyRoot "Granum.exe"
Copy-Item (Join-Path $pyRoot "pythonw.exe") $launcher
$rcedit = Get-Cached "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe" "rcedit-x64.exe"
Invoke-Checked $rcedit $launcher --set-icon $ico --set-version-string FileDescription "Granum" `
    --set-version-string ProductName "Granum" --set-version-string CompanyName "Granum" `
    --set-file-version $Version --set-product-version $Version
Invoke-Checked $rcedit (Join-Path $pyRoot "python.exe") --set-version-string FileDescription "Granum service" `
    --set-version-string ProductName "Granum"

# 7. The installer.
$iscc = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 was not found; install it from https://jrsoftware.org/isdl.php" }
$size = "{0:N0} MB" -f ((Get-ChildItem -Recurse -File $App | Measure-Object Length -Sum).Sum / 1MB)
Say "packing $size into the installer"
Invoke-Checked $iscc /Q "/DAppVersion=$Version" "/DSourceDir=$App" "/DOutputDir=$Repo\dist" "$Repo\packaging\windows\granum.iss"
$out = Join-Path $Repo "dist\Granum-$Version-Setup.exe"
Say ("done: $out ({0:N0} MB)" -f ((Get-Item $out).Length / 1MB))
