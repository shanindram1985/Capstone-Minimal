# Mobile Script Generator - Wireframe

Wireframe / screenshot → executable **Appium (Python)** tests for a retail mobile app. One pipeline, two commands.

| Mode | What it does |
|------|----------------|
| `generate` | Vision → SSM JSON → Appium script with **dummy** locators (no device) |
| `execute` | Vision → SSM JSON → retail test suite with **live** locators → run → visual HTML report |

The suite is not a single happy path. `prompts/script_steps.txt` and the step builder turn each screen’s SSM into **positive, negative, and edge** cases for that wireframe.

**Target app:** SauceLabs My Demo App Android (`demo_mobile_apps/mda-2.2.0-25.apk`).

**Slides:** [Mobile-Script-Generator-Wireframe.pptx](Mobile-Script-Generator-Wireframe.pptx) (7 slides). Rebuild with `.\.venv\Scripts\python.exe scripts\build_presentation.py`.

---

## Architecture

```
artifacts/input_screenshots/*.png
            │
            ▼
     ┌──────────────┐
     │ Vision Agent │  prompts/vision_analysis.txt
     └──────┬───────┘
            ▼
     artifacts/ssm_json_output/*.json
            │
            ▼
     ┌──────────────┐
     │ Step Builder │  prompts/script_steps.txt
     └──────┬───────┘   retail cases from this SSM only
            │
            ├── artifacts/step_output/*_steps.json
            ├── artifacts/manual_test_cases/*_manual_test_cases.md
            ▼
     ┌───────────────────┐
     │ Script Generator  │  one pytest method per case
     └──────┬────────────┘
            │
     ┌──────┴──────────────────────────┐
     │                                 │
 generate                            execute
 dummy locators               RuntimeLocatorResolver
                                      │
                                      ▼
                               visual HTML report
                               artifacts/test_execution_reports/
```

---

## Project layout

```
Mobile-Script-Generator-Wireframe/
├── agents/
│   ├── vision_agent.py          # Screenshot → SSM
│   ├── step_builder.py          # SSM → steps JSON + manual test cases
│   ├── script_generator.py      # Cases → Appium pytest
│   └── reporter_agent.py        # Visual HTML report
├── runtime/locator_resolver.py  # Live page-source locator fetch
├── models/ssm.py
├── prompts/
│   ├── vision_analysis.txt
│   └── script_steps.txt         # Retail coverage rules
├── pipelines/run.py             # CLI: generate | execute
├── scripts/
│   ├── install_prereqs.ps1
│   ├── setup_env.ps1 / .sh
│   ├── setup_appium.ps1
│   └── build_presentation.py
├── artifacts/input_screenshots/
├── demo_mobile_apps/            # mda-2.2.0-25.apk
└── Mobile-Script-Generator-Wireframe.pptx
```

---

## Test coverage

Cases use **only labels present on that wireframe’s SSM**. The same prompt covers every screen type.

| Wireframe | Positive | Negative | Edge |
|-----------|----------|----------|------|
| Login | `bod@example.com` / `10203040`, visual user | Locked-out user, bad password, unknown user, empty fields | Whitespace, 120 characters, special characters |
| Listing | Search `backpack`, scroll catalog | Empty search, no-match query | Whitespace, long query, special characters |
| Product details | Quantity 1, Add to cart | Empty quantity, quantity 0 | Quantity 99 |
| Cart | Promo `SAVE10` | Empty promo, `NOT-A-CODE` | Remove, quantity boundaries |
| Checkout | Name, address, ZIP, card, CVV | Missing and invalid fields | Whitespace, oversized text, numeric bounds |

Login tests open the menu, then Log In, before filling the form. Each case is its own pytest method and starts a fresh session.

---

## Setup from scratch (Windows)

Do these in order. PowerShell on this machine blocks `.ps1` files, so either call the `.exe` / `.cmd` directly or start a script with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\<script>.ps1
```

There is no `APPIUM_HOME` variable to set. Appium keeps drivers in `%USERPROFILE%\.appium`. The variables Appium **does** require are `JAVA_HOME` and `ANDROID_HOME`.

### 1. Project folder

```powershell
cd c:\Users\siddh\OneDrive\Desktop\Mobile-Script-Generator-Wireframe
```

### 2. Git, JDK 17, Android Studio

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_prereqs.ps1
```

That script installs from the `winget` source (the Microsoft Store source often fails with certificate error `0x8a15005e`):

- Git
- GitHub CLI
- Eclipse Temurin JDK 17
- Android Studio, if `%LOCALAPPDATA%\Android\Sdk` is not already there

Node.js is required for Appium and is not in that script. Install it, then open a **new** terminal:

```powershell
winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements
```

### 3. `JAVA_HOME` and `ANDROID_HOME`

Find the JDK folder (the one that contains `bin\java.exe`), then save both variables for your user:

```powershell
# Example after Temurin 17 is installed. Use the folder that actually exists.
dir "C:\Program Files\Eclipse Adoptium"

setx JAVA_HOME "C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot"
setx ANDROID_HOME "%LOCALAPPDATA%\Android\Sdk"
setx ANDROID_SDK_ROOT "%LOCALAPPDATA%\Android\Sdk"
```

`setx` applies to **new** terminals only. Also add these to the user Path:

- `%LOCALAPPDATA%\Android\Sdk\platform-tools`
- `%LOCALAPPDATA%\Android\Sdk\emulator`
- `%JAVA_HOME%\bin`

Open a new PowerShell and check:

```powershell
java -version
echo $env:JAVA_HOME
echo $env:ANDROID_HOME
```

`java -version` must print 17. `ANDROID_HOME` must be `C:\Users\<you>\AppData\Local\Android\Sdk`.

### 4. Android SDK and emulator

Open Android Studio (`C:\Program Files\Android\Android Studio\bin\studio64.exe`).

SDK Manager:

1. **SDK Platforms:** Android 14 (API 34) or Android 15 (API 35). Do **not** install a system image labeled **16 KB Page Size**.
2. **SDK Tools:** Android SDK Platform-Tools, Android Emulator, Android SDK Build-Tools.

Device Manager:

1. **Create Device** → Pixel 6.
2. System image: **Google APIs**, **x86_64**, API 34 or 35. Download it if needed.
3. Show Advanced Settings → RAM **4096 MB**.
4. Finish, then start it with **Cold Boot Now**.
5. Wait until the home screen is up. The first boot can take several minutes.

Check the emulator. `device` is the only good state:

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices
```

```text
emulator-5554   device
```

| `adb` status | Meaning |
|--------------|---------|
| `device` | Ready for Appium |
| `offline` | Process is up, Android has not finished the handshake. Wait, or cold-boot a normal (not 16 KB) image with at least 4 GB RAM |
| `unauthorized` | Accept the USB debugging prompt on the device |
| empty list | Emulator is not running |

See the Android version, then set `.env` to the same major version:

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" shell getprop ro.build.version.release
```

If that prints `15`, set `PLATFORM_VERSION=15` in `.env`. A mismatch produces `Unable to find an active device or emulator with OS …`.

### 5. Python 3.12 virtual environment

Use Python 3.12. System Python 3.14 does not have this project’s packages, which shows up as `No module named pydantic`.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1
```

If activation is blocked, create the venv without the script:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

### 6. `.env`

```powershell
copy .env.example .env
```

Edit `.env`:

- `VISION_AGENT_PROVIDER=cursor`
- `CURSOR_API_KEY=` your key from the Cursor dashboard
- `OPENAI_API_KEY=` leave empty
- `PLATFORM_VERSION=` the emulator Android version from step 4
- `APPIUM_SERVER_URL=http://127.0.0.1:4723`
- `APP_PATH=demo_mobile_apps/mda-2.2.0-25.apk`

### 7. Appium and the UiAutomator2 driver

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_appium.ps1
```

That runs `npm install -g appium` and `appium driver install uiautomator2`.

If `appium` itself is blocked as a script, install the driver with the `.cmd` launcher:

```powershell
npm install -g appium
appium.cmd driver install uiautomator2
appium.cmd driver list --installed
```

You should see `uiautomator2`.

### 8. Start Appium (leave this window open)

`appium` resolves to `appium.ps1`, which PowerShell may refuse. Use `appium.cmd`. The server only sees environment variables from **this** window, so set them here even if `setx` was already done:

```powershell
$env:JAVA_HOME = [Environment]::GetEnvironmentVariable("JAVA_HOME", "User")
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:Path = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:Path"
appium.cmd
```

Wait for:

```text
Appium REST http interface listener started on http://0.0.0.0:4723
```

In another terminal:

```powershell
curl http://127.0.0.1:4723/status
```

A connection error means Appium is not running.

### 9. Generate (no device, no Appium)

```powershell
.\.venv\Scripts\python.exe pipelines/run.py generate artifacts/input_screenshots/Login.png
```

Writes:

- `artifacts/ssm_json_output/ssm_<Screen>_*.json`
- `artifacts/step_output/<screen>_steps.json` — the steps the script generator uses
- `artifacts/manual_test_cases/<screen>_manual_test_cases.md` — the same cases for a tester
- `artifacts/generated_appium_scripts/test_<screen>_screen.py`

### 10. Execute (emulator `device` + Appium up)

```powershell
.\.venv\Scripts\python.exe pipelines/run.py execute artifacts/input_screenshots/Login.png
```

Add `--no-browser` to skip opening the report.

Before this command, both of these must already be true:

```powershell
curl http://127.0.0.1:4723/status
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices
```

Output:

- `artifacts/step_output/` and `artifacts/manual_test_cases/`
- Runtime script under `artifacts/generated_appium_scripts/`
- `artifacts/resolved_locators/`
- `artifacts/test_execution_reports/<timestamp>/report.html`
- Failure screenshots in `artifacts/test_screenshots/`

The report shows a pass-rate banner, result counts, a donut, time-per-test bars, and status pills for positive, negative, and edge cases.

### Setup checklist

| Check | Command | Expected |
|-------|---------|----------|
| Java | `java -version` | 17 |
| `JAVA_HOME` | `echo $env:JAVA_HOME` | Temurin JDK 17 folder |
| `ANDROID_HOME` | `echo $env:ANDROID_HOME` | `%LOCALAPPDATA%\Android\Sdk` |
| Emulator | `adb devices` | `emulator-5554   device` |
| Android version | `adb shell getprop ro.build.version.release` | Same as `PLATFORM_VERSION` |
| Appium | `curl http://127.0.0.1:4723/status` | JSON status, not connection refused |
| UiAutomator2 | `appium.cmd driver list --installed` | `uiautomator2` |
| Project Python | `.\.venv\Scripts\python.exe -c "import pydantic"` | No error |

---

## How locators work

**generate** embeds placeholder IDs (`com.example.dummy:id/...`).

**execute** calls `RuntimeLocatorResolver`, which:

1. Reads Appium `page_source`
2. Prefers a known My Demo App control when that node is on screen (`menuIV`, `nameET`, `passwordET`, `loginBtn`, drawer text `Log In`)
3. Ignores Android system dialog chrome
4. Writes matches to `artifacts/resolved_locators/resolved_locators.json`

---

## Prompts

| File | Role |
|------|------|
| `prompts/vision_analysis.txt` | Screenshot → SSM JSON |
| `prompts/script_steps.txt` | SSM JSON → retail positive, negative, and edge cases |

The default step builder follows those retail rules from the SSM. Set `STEP_BUILDER_PROVIDER=cursor` to ask the model, using the same prompt. Thin model output falls back to the SSM rules.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `No module named pydantic` | Call `.\.venv\Scripts\python.exe`, not system `python`. |
| `appium.ps1` or `Activate.ps1` cannot be loaded | Use `appium.cmd` and the venv `python.exe`. |
| Connection refused on port 4723 | Start Appium and leave that window open. |
| `ANDROID_HOME` / `JAVA_HOME` not set | Set them in the **same** terminal that starts Appium, then restart Appium. |
| Emulator OS does not match | Set `PLATFORM_VERSION` in `.env` to the AVD version. |
| `adb` stays `offline` | Cold-boot a normal API image. Avoid 16 KB page-size images. Give the AVD at least 4 GB RAM. |
| Menu tap hits the wrong control | A system dialog was in front. Dismiss it, then re-run. The suite now dismisses common alerts first. |

---

## License / demo app

The SauceLabs My Demo App APK is included for local automation demos. Respect Sauce Labs licensing for redistribution.
