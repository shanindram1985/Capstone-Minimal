# Install system prerequisites for Capstone-Minimal on Windows (winget).
# Run from an elevated PowerShell if installs fail due to permissions.

$ErrorActionPreference = "Continue"

function Install-WingetPackage {
    param([string]$Id, [string]$Name)
    Write-Host "`n==> Installing $Name ($Id)"
    winget install --id $Id -e --accept-package-agreements --accept-source-agreements
}

Write-Host "Installing Git, GitHub CLI, Temurin JDK 17, Android Studio (SDK/emulator)..."

Install-WingetPackage -Id "Git.Git" -Name "Git"
Install-WingetPackage -Id "GitHub.cli" -Name "GitHub CLI"
Install-WingetPackage -Id "EclipseAdoptium.Temurin.17.JDK" -Name "Temurin JDK 17"

# Android Studio brings SDK Manager + Emulator. Skip if already present.
if (-not (Test-Path "${env:LOCALAPPDATA}\Android\Sdk")) {
    Install-WingetPackage -Id "Google.AndroidStudio" -Name "Android Studio"
} else {
    Write-Host "Android SDK already present under LOCALAPPDATA\Android\Sdk"
}

Write-Host @"

After installs complete, open a NEW terminal and verify:

  git --version
  gh --version
  java -version
  node --version
  npm --version

Android setup (after Android Studio installs):
  1. Open Android Studio → More Actions → SDK Manager
  2. Install Android SDK Platform-Tools, a recent platform (API 34), and an emulator system image
  3. Create a Virtual Device (Device Manager)
  4. Add to User PATH:
       %LOCALAPPDATA%\Android\Sdk\platform-tools
       %LOCALAPPDATA%\Android\Sdk\emulator
  5. Verify: adb version

Then run:
  .\scripts\setup_env.ps1
  .\scripts\setup_appium.ps1
"@
