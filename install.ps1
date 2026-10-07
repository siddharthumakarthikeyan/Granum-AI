param(
    [switch]$Dev,
    [switch]$Training,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path $PSScriptRoot).Path
$Venv = Join-Path $Repo ".venv"

function Say($text) {
    Write-Host "granum " -ForegroundColor Cyan -NoNewline
    Write-Host $text
}

function Fail($text) {
    Write-Host "granum " -ForegroundColor Red -NoNewline
    Write-Host $text
    exit 1
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Exe,

        [Parameter(ValueFromRemainingArguments = $true)]
        [object[]]$Arguments
    )

    & $Exe @Arguments

    if ($LASTEXITCODE -ne 0) {
        throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

# ============================================================
# 1. Find and validate Python
# ============================================================

$PythonCommand = Get-Command python -ErrorAction SilentlyContinue

if (-not $PythonCommand) {
    Fail "Python was not found. Install Python 3.10 or newer."
}

$PythonVersion = & python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"

Say "using Python $PythonVersion"

$PythonVersionCheck = & python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"

if ($LASTEXITCODE -ne 0) {
    Fail "Python 3.10 or newer is required. Found Python $PythonVersion"
}

# ============================================================
# 2. Clean existing development environment if requested
# ============================================================

if ($Clean) {
    if (Test-Path $Venv) {
        Say "removing existing development environment"
        Remove-Item -Recurse -Force $Venv
    }
}

# ============================================================
# 3. Create local virtual environment
# ============================================================

if (-not (Test-Path "$Venv\Scripts\python.exe")) {

    Say "creating development virtual environment"

    Invoke-Checked python -m venv $Venv
}

$Py = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Py)) {
    Fail "Virtual environment Python was not created correctly."
}

# ============================================================
# 4. Upgrade packaging tools
# ============================================================

Say "upgrading pip"

Invoke-Checked $Py -m pip install --upgrade pip setuptools wheel

# ============================================================
# 5. Build the dashboard
# ============================================================

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail "npm was not found. Install Node.js 20 or newer."
}

Say "installing dashboard dependencies"

Push-Location (Join-Path $Repo "web")

try {

    Invoke-Checked npm ci --no-audit --no-fund

    Say "building dashboard"

    Invoke-Checked npm run build

}
finally {
    Pop-Location
}

# ============================================================
# 6. Install Granum in editable mode
# ============================================================

Say "installing Granum in editable mode"

$Project = "${Repo}[service,desktop,images,pandas,dev]"

& $Py -m pip install -e $Project

if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Granum in editable mode."
}

# ============================================================
# 7. Optional training dependencies
# ============================================================

if ($Training) {

    Say "installing Ultralytics for training"

    Invoke-Checked $Py -m pip install ultralytics
}

# ============================================================
# 8. Verify installation
# ============================================================

Say "checking Granum installation"

& $Py -c "import granum; print('Granum import OK')"

if ($LASTEXITCODE -ne 0) {
    throw "Granum installation verification failed."
}

# ============================================================
# 9. Finished
# ============================================================

Say ""
Say "development environment ready"
Say ""
Say "Environment:"
Say "  $Venv"
Say ""
Say "Python:"
Say "  $Py"
Say ""
Say "Activate it with:"
Say "  .\.venv\Scripts\Activate.ps1"
Say ""
Say "Then run:"
Say "  granum --help"
Say ""
Say "For a clean reinstall:"
Say "  .\install.ps1 -Clean"
Say ""
