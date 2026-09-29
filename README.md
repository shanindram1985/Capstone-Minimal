# Capstone-Minimal

Wireframe / screenshot → executable **Appium (Python)** tests for the SauceLabs My Demo App — with a **single minimal agent pipeline** and **only two commands**.

| Mode | What it does |
|------|----------------|
| `generate` | Vision → SSM → Appium script with **dummy** locators (no device needed) |
| `execute` | Vision → SSM → Appium script that **fetches locators on the fly** from the live app → run → HTML report |

No separate locator agent, no manual testcases, no reviewer, no self-healing stack.

---

## Architecture

```
artifacts/input_screenshots/*.png
            │
            ▼
     ┌──────────────┐
     │ Vision Agent │  prompts/vision_analysis.txt  (openai | mock)
     └──────┬───────┘
            ▼
     artifacts/ssm_json_output/*.json
            │
            ▼
     ┌──────────────┐
     │ Step Builder │  heuristics (or optional LLM via script_steps.txt)
     └──────┬───────┘
            ▼
     ┌───────────────────┐
     │ Script Generator  │
     └──────┬────────────┘
            │
     ┌──────┴──────────────────────────┐
     │                                 │
 generate                            execute
 dummy locators               RuntimeLocatorResolver
 com.example.dummy:id/...     (page source match + SauceLabs hints)
                                      │
                                      ▼
                               pytest + pytest-html
                               artifacts/test_execution_reports/
```

**Target app:** SauceLabs My Demo App Android (`demo_mobile_apps/mda-2.2.0-25.apk`), login flow.

---

## Project layout

```
Capstone-Minimal/
├── agents/
│   ├── vision_agent.py          # Screenshot → SSM
│   ├── step_builder.py          # SSM → ordered actions
│   ├── script_generator.py      # Actions → Appium pytest
│   └── reporter_agent.py        # pytest-html
├── runtime/
│   └── locator_resolver.py      # Live page-source locator fetch
├── models/ssm.py
├── prompts/
│   ├── vision_analysis.txt
│   └── script_steps.txt
├── pipelines/run.py             # CLI: generate | execute
├── scripts/
│   ├── install_prereqs.ps1      # Git, gh, JDK, Android Studio
│   ├── setup_env.ps1 / .sh      # Python venv + deps
│   └── setup_appium.ps1         # Appium + UiAutomator2
├── artifacts/input_screenshots/ # e.g. Login.png
├── demo_mobile_apps/            # mda-2.2.0-25.apk
├── requirements.txt
├── .env.example
└── conftest.py
```

---

## Prerequisites

| Software | Purpose |
|----------|---------|
| Python 3.11+ (3.12 recommended) | Pipeline + Appium client |
| Node.js 18+ / npm | Appium server |
| JDK 17 | Android tooling |
| Android Studio + SDK + emulator (or real device) | Run My Demo App |
| Appium 2 + UiAutomator2 driver | Automation server |
| Git + GitHub CLI | Version control / push |
| OpenAI API key (optional) | Real vision instead of mock |

### One-shot Windows install

```powershell
cd Capstone-Minimal
powershell -ExecutionPolicy Bypass -File .\scripts\install_prereqs.ps1
# Open a NEW terminal after winget finishes, then:
powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\setup_appium.ps1
```

Manual Android steps after Android Studio install:

1. SDK Manager → Platform-Tools, API 34, emulator system image  
2. Device Manager → create an AVD and start it  
3. Add to PATH: `%LOCALAPPDATA%\Android\Sdk\platform-tools` and `...\emulator`  
4. Verify: `adb devices`

---

## Configure

```powershell
copy .env.example .env
# Edit .env — for offline demo keep:
#   VISION_AGENT_PROVIDER=mock
# For real vision:
#   VISION_AGENT_PROVIDER=openai
#   OPENAI_API_KEY=sk-...
```

Ensure `APP_PATH` points at `demo_mobile_apps/mda-2.2.0-25.apk` (resolved to an absolute path automatically during `execute`).

---

## Commands

Activate the venv:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 1) Generate script only (dummy locators — no Appium/device)

```powershell
python pipelines/run.py generate artifacts/input_screenshots/Login.png
```

Output:

- `artifacts/ssm_json_output/ssm_Login_*.json`
- `artifacts/generated_appium_scripts/test_login_screen.py` (dummy IDs like `com.example.dummy:id/username`)

### 2) Real execution (on-the-fly locators + report)

Terminal A — start Appium:

```powershell
appium
```

Terminal B — emulator/device online (`adb devices`), then:

```powershell
.\.venv\Scripts\Activate.ps1
python pipelines/run.py execute artifacts/input_screenshots/Login.png
# or without opening the browser:
python pipelines/run.py execute artifacts/input_screenshots/Login.png --no-browser
```

Output:

- Runtime script under `artifacts/generated_appium_scripts/`
- Resolved locators dump: `artifacts/resolved_locators/`
- HTML report: `artifacts/test_execution_reports/<timestamp>/report.html`
- Failure screenshots (if any): `artifacts/test_screenshots/`

Demo login credentials used by the step builder: `bod@example.com` / `10203040`.

---

## How locators work

**generate:** scripts embed placeholder resource IDs (`com.example.dummy:id/...`) so you can inspect structure without a device.

**execute:** generated tests call `RuntimeLocatorResolver`, which:

1. Reads Appium `page_source` XML  
2. Scores nodes by label tokens vs `resource-id` / `content-desc` / `text`  
3. Boosts known SauceLabs My Demo App IDs when present (`nameET`, `passwordET`, `loginBtn`, `menuIV`, …)  
4. Caches and writes matches to `artifacts/resolved_locators/resolved_locators.json`

---

## Prompts

| File | Used by |
|------|---------|
| `prompts/vision_analysis.txt` | Vision agent (wireframe → SSM JSON) |
| `prompts/script_steps.txt` | Optional LLM step builder (`STEP_BUILDER_PROVIDER=openai`) |

Default step building is **heuristic** (no API call).

---

## Difference from full Capstone

| Full Capstone | Capstone-Minimal |
|---------------|------------------|
| 6 steps (vision, manual TC, locator, script, review, report) | 2 modes only |
| Separate locator + reviewer + navigation agents | Single pipeline + runtime resolver |
| LangChain / self-healing optional stack | Removed |
| Manual testcase artifacts | Removed |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `OPENAI_API_KEY is required` | Set key or use `VISION_AGENT_PROVIDER=mock` |
| Appium session fails | `appium` running? `adb devices` shows device? `APP_PATH` valid? |
| Cannot find elements on Login | App must reach login via menu; runtime navigates Menu → Log In first |
| Import errors for `runtime` | Run from project root so `ROOT` is on `sys.path` (pipeline does this) |

---

## License / demo app

SauceLabs My Demo App APK is included for local automation demos. Respect Sauce Labs licensing for redistribution.
