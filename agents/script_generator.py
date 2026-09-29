"""Generate Appium pytest scripts from SSM steps.

Modes:
  - dummy: write placeholder locators (script generation only)
  - runtime: scripts resolve locators on-the-fly against the live app
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DUMMY_LOCATORS = {
    "username": ("resource_id", "com.example.dummy:id/username"),
    "username_input": ("resource_id", "com.example.dummy:id/username"),
    "password": ("resource_id", "com.example.dummy:id/password"),
    "password_input": ("resource_id", "com.example.dummy:id/password"),
    "login": ("resource_id", "com.example.dummy:id/login_button"),
    "menu": ("resource_id", "com.example.dummy:id/menu"),
    "cart": ("resource_id", "com.example.dummy:id/cart"),
}


def _py(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _case_method_name(screen: str, case: Dict[str, Any]) -> str:
    category = str(case.get("category") or "case")
    name = str(case.get("name") or "scenario")
    return "test_" + _slug(f"{screen}_{category}_{name}")


def _case_doc(screen: str, case: Dict[str, Any]) -> str:
    category = str(case.get("category") or "case")
    name = str(case.get("name") or "scenario")
    expected = str(case.get("expected") or "").strip()
    text = f"{screen} {category}: {name}"
    if expected:
        text += f". {expected}"
    return text.replace('"', "'")


def _cases_from_payload(step_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    cases = step_payload.get("cases")
    if isinstance(cases, list) and cases:
        return [case for case in cases if isinstance(case, dict) and case.get("steps")]
    steps = step_payload.get("steps") or []
    if not steps:
        return []
    return [{"name": "happy_path", "category": "positive", "expected": "", "steps": steps}]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return slug or "screen"


def _normalize_key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")


def dummy_locator_for(label: str) -> tuple[str, str]:
    key = _normalize_key(label)
    if key in DUMMY_LOCATORS:
        return DUMMY_LOCATORS[key]
    for hint, locator in DUMMY_LOCATORS.items():
        if hint in key or key in hint:
            return locator
    return "resource_id", f"com.example.dummy:id/{key or 'element'}"


NAVIGATION = {
    "login": [
        ("tap", "Menu", "Open hamburger menu"),
        ("tap", "Log In", "Open login from menu"),
    ],
    "cart": [("tap", "Cart", "Open cart icon")],
}

# Wireframe often tags chrome / demo credential chips as tappable; skip those for Login.
LOGIN_SKIP_LABELS = {
    "menu",
    "cart",
    "mydemoapp",
    "log_in",
    "bod_example_com",
    "alice_example_com_locked_out",
    "visual_example_com",
    "10203040",
}


class ScriptGeneratorAgent:
    def __init__(self, project_root: Optional[Path | str] = None) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1])
        self.output_dir = self.project_root / "artifacts" / "generated_appium_scripts"

    def generate(
        self,
        step_payload: Dict[str, Any],
        mode: str = "dummy",
        output_dir: Optional[Path | str] = None,
    ) -> Path:
        mode = mode.lower().strip()
        if mode not in {"dummy", "runtime"}:
            raise ValueError("mode must be 'dummy' or 'runtime'")

        screen = str(step_payload.get("screen") or "Screen")
        cases = _cases_from_payload(step_payload)
        if not cases:
            raise ValueError("No steps to generate a script from.")

        content = (
            self._render_runtime_script(screen, cases)
            if mode == "runtime"
            else self._render_dummy_script(screen, cases)
        )

        dest = Path(output_dir or self.output_dir)
        dest.mkdir(parents=True, exist_ok=True)
        out_path = dest / f"test_{_slug(screen)}_screen.py"
        out_path.write_text(content, encoding="utf-8")
        logger.info("[ScriptGenerator] Wrote %s (%s mode)", out_path.name, mode)
        return out_path

    def _render_dummy_script(self, screen: str, cases: List[Dict[str, Any]]) -> str:
        class_name = "Test" + "".join(p.capitalize() for p in _slug(screen).split("_") if p)
        methods: List[str] = []
        for case in cases:
            test_name = _case_method_name(screen, case)
            body_lines: List[str] = [
                f'        """{_case_doc(screen, case)}"""',
                "        # WARNING: dummy locators are placeholders - use `execute` mode for real runs.",
                "",
            ]
            body_lines.extend(self._step_lines(screen, case.get("steps") or [], runtime=False))
            methods.append(f"    def {test_name}(self) -> None:\n" + "\n".join(body_lines).rstrip() + "\n")
        return self._base_template(screen, class_name, "\n".join(methods), runtime=False)

    def _render_runtime_script(self, screen: str, cases: List[Dict[str, Any]]) -> str:
        class_name = "Test" + "".join(p.capitalize() for p in _slug(screen).split("_") if p)
        methods: List[str] = []
        for case in cases:
            test_name = _case_method_name(screen, case)
            body_lines: List[str] = [
                f'        """{_case_doc(screen, case)}"""',
                "        dump_dir = Path(os.getenv('RESOLVED_LOCATORS_DIR', 'artifacts/resolved_locators'))",
                "        self.resolver = RuntimeLocatorResolver(self.driver, self.wait, dump_dir=dump_dir)",
                "",
            ]
            for nav_action, label, comment in NAVIGATION.get(screen.lower(), []):
                body_lines.append(f"        # Navigate: {comment}")
                if nav_action == "tap":
                    body_lines.append(f"        self.resolve_tap('{_py(label)}')")
                body_lines.append("")
            body_lines.extend(self._step_lines(screen, case.get("steps") or [], runtime=True))
            methods.append(f"    def {test_name}(self) -> None:\n" + "\n".join(body_lines).rstrip() + "\n")
        return self._base_template(screen, class_name, "\n".join(methods), runtime=True)

    def _step_lines(self, screen: str, steps: List[Dict[str, Any]], runtime: bool) -> List[str]:
        lines: List[str] = []
        filtered = self._filter_steps(screen, steps)
        for index, step in enumerate(filtered, start=1):
            label = _py(str(step.get("element") or f"Element {index}"))
            action = str(step.get("action") or "verify").lower()
            lines.append(f"        # Step {index}: {action} -> {label}")
            if runtime:
                if action == "type":
                    text = _py(str(step.get("input_value") or ""))
                    lines.append(f"        self.resolve_type('{label}', '{text}')")
                elif action == "scroll":
                    lines.append(f"        self.resolve_scroll('{label}')")
                elif action == "tap":
                    lines.append(f"        self.resolve_tap('{label}')")
                else:
                    lines.append(f"        self.resolve_verify('{label}')")
            else:
                strategy, value = dummy_locator_for(label)
                if action == "type":
                    text = _py(str(step.get("input_value") or ""))
                    lines.append(f"        self.type('{strategy}', '{value}', '{text}')")
                elif action == "scroll":
                    lines.append(f"        self.scroll('{strategy}', '{value}')")
                elif action == "tap":
                    lines.append(f"        self.tap('{strategy}', '{value}')")
                else:
                    lines.append(
                        "        self.wait.until(EC.visibility_of_element_located("
                        f"self._build_locator('{strategy}', '{value}')))"
                    )
            lines.append("")
        return lines

    def _filter_steps(self, screen: str, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if screen.lower() != "login":
            return list(steps)
        kept: List[Dict[str, Any]] = []
        for step in steps:
            label = str(step.get("element") or "")
            key = _normalize_key(label)
            if key in LOGIN_SKIP_LABELS or key.endswith("_example_com"):
                continue
            # Skip chrome already covered by NAVIGATION (Menu / Log In).
            if key in {"menu", "log_in"}:
                continue
            kept.append(step)
        return kept

    def _base_template(
        self,
        screen: str,
        class_name: str,
        methods: str,
        runtime: bool,
    ) -> str:
        if runtime:
            runtime_import = (
                "from pathlib import Path\n"
                "from runtime.locator_resolver import RuntimeLocatorResolver\n"
            )
            runtime_helpers = '''
    def resolve_tap(self, label: str) -> None:
        strategy, value = self.resolver.resolve(label)
        self.tap(strategy, value)

    def resolve_type(self, label: str, text: str) -> None:
        strategy, value = self.resolver.resolve(label, prefer_editable=True)
        self.type(strategy, value, text)

    def resolve_verify(self, label: str) -> None:
        strategy, value = self.resolver.resolve(label)
        self.wait.until(EC.visibility_of_element_located(self._build_locator(strategy, value)))

    def resolve_scroll(self, label: str) -> None:
        strategy, value = self.resolver.resolve(label)
        self.scroll(strategy, value)
'''
        else:
            runtime_import = ""
            runtime_helpers = ""

        return f'''"""Generated Appium pytest script for {screen}."""

from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

{runtime_import}

class {class_name}:
    """Appium test for the {screen} screen."""

    def setup_method(self) -> None:
        platform = os.getenv("PLATFORM_NAME", "Android")
        platform_version = os.getenv("PLATFORM_VERSION", "14.0")
        device_name = os.getenv("DEVICE_NAME", "Android Emulator")
        app_path = os.getenv("APP_PATH", "")
        appium_server = os.getenv("APPIUM_SERVER_URL", "http://127.0.0.1:4723")

        desired_caps: Dict[str, Any] = {{
            "platformName": platform,
            "deviceName": device_name,
            "app": app_path,
            "noReset": False,
        }}

        if platform.lower() == "ios":
            desired_caps["automationName"] = "XCUITest"
            desired_caps["wdaLaunchTimeout"] = 180000
            desired_caps["wdaConnectionTimeout"] = 180000
        else:
            desired_caps["automationName"] = "UiAutomator2"
            desired_caps["platformVersion"] = platform_version
            desired_caps["autoGrantPermissions"] = True
            desired_caps["appWaitActivity"] = "*"
            desired_caps["appWaitDuration"] = 60000
            desired_caps["androidInstallTimeout"] = 90000
            app_package = os.getenv("APP_PACKAGE")
            app_activity = os.getenv("APP_ACTIVITY")
            if app_package:
                desired_caps["appPackage"] = app_package
            if app_activity:
                desired_caps["appActivity"] = app_activity

        self.driver = self._create_driver(desired_caps, appium_server)
        self.wait = WebDriverWait(self.driver, int(os.getenv("EXPLICIT_WAIT_TIMEOUT", "15")))
        self.platform = platform
        self._dismiss_system_dialogs()

    def teardown_method(self) -> None:
        if getattr(self, "driver", None):
            self.driver.quit()

    def _dismiss_system_dialogs(self) -> None:
        """Dismiss Android system alerts (e.g. 16KB page-size compatibility)."""
        if self.platform.lower() != "android":
            return
        for _ in range(3):
            dismissed = False
            for text in ("Don't Show Again", "OK", "Allow", "While using the app"):
                try:
                    el = self.driver.find_element(
                        AppiumBy.ANDROID_UIAUTOMATOR,
                        f'new UiSelector().text("{{text}}")',
                    )
                    if el.is_displayed():
                        el.click()
                        dismissed = True
                        break
                except Exception:
                    continue
            if not dismissed:
                break

    def tap(self, locator_strategy: str, locator_value: str) -> None:
        locator = self._build_locator(locator_strategy, locator_value)
        element = self.wait.until(EC.element_to_be_clickable(locator))
        element.click()

    def type(self, locator_strategy: str, locator_value: str, text: str) -> None:
        locator = self._build_locator(locator_strategy, locator_value)
        element = self.wait.until(EC.element_to_be_clickable(locator))
        element.clear()
        element.send_keys(text)

    def scroll(self, locator_strategy: str, locator_value: str) -> None:
        if self.platform.lower() == "android":
            selector = self._build_uiautomator_selector(locator_strategy, locator_value)
            command = (
                "new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView("
                + selector
                + ")"
            )
            self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, command)
        self.wait.until(
            EC.visibility_of_element_located(self._build_locator(locator_strategy, locator_value))
        )

    def _create_driver(self, desired_caps: Dict[str, Any], server_url: str) -> Any:
        from appium import webdriver

        platform = desired_caps.get("platformName", "Android")
        if platform.lower() == "ios":
            from appium.options.ios import XCUITestOptions

            options = XCUITestOptions().load_capabilities(desired_caps)
        else:
            from appium.options.android import UiAutomator2Options

            options = UiAutomator2Options().load_capabilities(desired_caps)
        return webdriver.Remote(server_url, options=options)

    def _build_locator(self, locator_strategy: str, locator_value: str) -> Tuple[str, str]:
        if locator_strategy == "resource_id":
            return (AppiumBy.ID, locator_value)
        if locator_strategy == "accessibility_id":
            return (AppiumBy.ACCESSIBILITY_ID, locator_value)
        if locator_strategy == "xpath":
            return (AppiumBy.XPATH, locator_value)
        if self.platform.lower() == "android":
            return (
                AppiumBy.ANDROID_UIAUTOMATOR,
                self._build_uiautomator_selector(locator_strategy, locator_value),
            )
        return (AppiumBy.NAME, locator_value)

    def _build_uiautomator_selector(self, locator_strategy: str, locator_value: str) -> str:
        strategy = (locator_strategy or "text").strip().lower()
        if strategy == "accessibility_id":
            return f'new UiSelector().description("{{locator_value}}")'
        if strategy == "resource_id":
            return f'new UiSelector().resourceId("{{locator_value}}")'
        return f'new UiSelector().text("{{locator_value}}")'
{runtime_helpers}
{methods}
'''
