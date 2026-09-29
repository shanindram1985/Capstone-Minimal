"""pytest hooks for Capstone-Minimal Appium runs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return

    instance = getattr(item, "instance", None)
    driver = getattr(instance, "driver", None) if instance else None
    if driver is None:
        return

    shots = Path("artifacts") / "test_screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = shots / f"{item.name}_{stamp}.png"
    try:
        driver.get_screenshot_as_file(str(path))
        print(f"[conftest] Failure screenshot -> {path}")
    except Exception as exc:  # pragma: no cover
        print(f"[conftest] Could not capture screenshot: {exc}")
