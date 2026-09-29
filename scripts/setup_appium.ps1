# Install Appium server + UiAutomator2 driver (requires Node.js/npm)

Write-Host "==> Checking Node.js / npm"
node --version
npm --version

Write-Host "==> Installing Appium globally"
npm install -g appium

Write-Host "==> Installing UiAutomator2 driver"
appium driver install uiautomator2

Write-Host "==> Appium doctor (informational)"
try {
    npm install -g appium-doctor
    appium-doctor --android
} catch {
    Write-Host "appium-doctor optional; skipped or reported issues above."
}

Write-Host ""
Write-Host "Appium installed. Start the server in a separate terminal:"
Write-Host "  appium"
Write-Host ""
Write-Host "Ensure an Android emulator/device is running and adb devices lists it."
