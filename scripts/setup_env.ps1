param(
    [string]$PythonExe = "",
    [string]$VenvDir = ".venv"
)

if (-not $PythonExe) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "C:\Program Files\Python312\python.exe",
        "python"
    )
    foreach ($c in $candidates) {
        if ($c -eq "python") { $PythonExe = $c; break }
        if (Test-Path $c) { $PythonExe = $c; break }
    }
}

Write-Host "==> Using Python: $PythonExe"
Write-Host "==> Creating virtual environment in $VenvDir"
$python = Get-Command $PythonExe -ErrorAction Stop
& $python.Source -m venv $VenvDir

Write-Host "==> Activating virtual environment"
& "$PWD\$VenvDir\Scripts\Activate.ps1"

Write-Host "==> Upgrading pip"
python -m pip install --upgrade pip setuptools wheel

Write-Host "==> Installing Python dependencies"
python -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "==> Created .env from .env.example"
}

Write-Host ""
Write-Host "Python environment ready (prefer Python 3.12 on Windows)."
Write-Host "Next: .\scripts\setup_appium.ps1"
Write-Host "Then:  .\scripts\run.ps1 generate artifacts\input_screenshots\Login.png"
