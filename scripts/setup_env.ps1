param(
    [string]$PythonExe = "python",
    [string]$VenvDir = ".venv"
)

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
Write-Host "Python environment ready."
Write-Host "Next: .\scripts\setup_appium.ps1"
Write-Host "Then:  python pipelines/run.py generate artifacts/input_screenshots/Login.png"
