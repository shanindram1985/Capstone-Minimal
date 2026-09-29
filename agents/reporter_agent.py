"""Run generated Appium scripts and produce an HTML report."""

from __future__ import annotations

import logging
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ReporterAgent:
    def __init__(self, project_root: Optional[Path | str] = None) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1])
        self.scripts_dir = self.project_root / "artifacts" / "generated_appium_scripts"
        self.reports_base = self.project_root / "artifacts" / "test_execution_reports"

    def run(
        self,
        scripts_dir: Optional[Path | str] = None,
        open_browser: bool = True,
        extra_args: Optional[list[str]] = None,
    ) -> Path:
        source = Path(scripts_dir or self.scripts_dir)
        if not source.exists():
            raise FileNotFoundError(f"Scripts directory not found: {source}")

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = self.reports_base / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        report_html = run_dir / "report.html"

        logger.info("[Reporter] Running tests from %s", source)
        print(f"[Reporter] Running tests from: {source}")
        print(f"[Reporter] Saving report to:   {report_html}")

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(source),
            f"--html={report_html}",
            "--self-contained-html",
            "-v",
            "--tb=short",
        ]
        if extra_args:
            cmd.extend(extra_args)

        result = subprocess.run(cmd, cwd=str(self.project_root))
        status = "PASSED" if result.returncode == 0 else "FAILED/ERRORS"
        print(f"[Reporter] Test run complete - {status} (exit {result.returncode})")
        print(f"[Reporter] Report: {report_html}")

        if open_browser and report_html.exists():
            webbrowser.open(report_html.as_uri())
        return report_html
