param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsRest
)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "ERROR: .venv not found. Run: .\scripts\setup_env.ps1"
    exit 1
}

& $venvPython -c "import pydantic, cursor_sdk" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: venv missing packages. Run: .\scripts\setup_env.ps1"
    exit 1
}

if (-not $ArgsRest -or $ArgsRest.Count -eq 0) {
    Write-Host "Usage:"
    Write-Host "  .\scripts\run.ps1 generate artifacts\input_screenshots\Login.png"
    Write-Host "  .\scripts\run.ps1 execute  artifacts\input_screenshots\Login.png"
    exit 2
}

& $venvPython (Join-Path $Root "pipelines\run.py") @ArgsRest
exit $LASTEXITCODE
