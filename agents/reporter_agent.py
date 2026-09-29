"""Run generated Appium scripts and write a visual HTML report."""

from __future__ import annotations

import html
import logging
import subprocess
import sys
import webbrowser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PASS = "#0f9d6e"
FAIL = "#d64545"
ERROR = "#e07a2f"
SKIP = "#7b8794"
INK = "#1c2430"


@dataclass
class TestResult:
    name: str
    classname: str
    duration: float
    status: str
    message: str = ""
    details: str = ""
    screenshot: Optional[Path] = None
    category: str = "scenario"
    title: str = ""


@dataclass
class RunSummary:
    started: datetime
    duration: float = 0.0
    tests: list[TestResult] = field(default_factory=list)
    exit_code: int = 1

    @property
    def passed(self) -> int:
        return sum(1 for test in self.tests if test.status == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for test in self.tests if test.status == "failed")

    @property
    def errors(self) -> int:
        return sum(1 for test in self.tests if test.status == "error")

    @property
    def skipped(self) -> int:
        return sum(1 for test in self.tests if test.status == "skipped")

    @property
    def total(self) -> int:
        return len(self.tests)

    @property
    def pass_rate(self) -> int:
        if not self.total:
            return 0
        return round(100 * self.passed / self.total)


class ReporterAgent:
    def __init__(self, project_root: Optional[Path | str] = None) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1])
        self.scripts_dir = self.project_root / "artifacts" / "generated_appium_scripts"
        self.reports_base = self.project_root / "artifacts" / "test_execution_reports"
        self.screenshots_dir = self.project_root / "artifacts" / "test_screenshots"

    def run(
        self,
        scripts_dir: Optional[Path | str] = None,
        open_browser: bool = True,
        extra_args: Optional[list[str]] = None,
    ) -> Path:
        source = Path(scripts_dir or self.scripts_dir)
        if not source.exists():
            raise FileNotFoundError(f"Scripts directory not found: {source}")

        started = datetime.now()
        timestamp = started.strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = self.reports_base / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        report_html = run_dir / "report.html"
        junit_path = run_dir / "junit.xml"

        logger.info("[Reporter] Running tests from %s", source)
        print(f"[Reporter] Running tests from: {source}")
        print(f"[Reporter] Saving report to:   {report_html}")

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(source),
            f"--junitxml={junit_path}",
            "-v",
            "--tb=short",
        ]
        if extra_args:
            cmd.extend(extra_args)

        result = subprocess.run(cmd, cwd=str(self.project_root))
        summary = self._load_summary(junit_path, started, result.returncode)
        report_html.write_text(self._render(summary), encoding="utf-8")

        status = "PASSED" if summary.failed == 0 and summary.errors == 0 and summary.total else "FAILED"
        print(f"[Reporter] Test run complete - {status} (exit {result.returncode})")
        print(f"[Reporter] Report: {report_html}")

        if open_browser and report_html.exists():
            webbrowser.open(report_html.as_uri())
        return report_html

    def _load_summary(self, junit_path: Path, started: datetime, exit_code: int) -> RunSummary:
        summary = RunSummary(started=started, exit_code=exit_code)
        if not junit_path.exists():
            summary.tests.append(
                TestResult(
                    name="pytest",
                    classname="",
                    duration=0,
                    status="error",
                    title="Test run did not produce results",
                    message="pytest did not write a results file.",
                )
            )
            return summary

        root = ET.parse(junit_path).getroot()
        suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
        for suite in suites:
            summary.duration += float(suite.attrib.get("time") or 0)
            for case in suite.findall("testcase"):
                summary.tests.append(self._case_from_xml(case))
        if not summary.duration:
            summary.duration = sum(test.duration for test in summary.tests)
        return summary

    def _case_from_xml(self, case: ET.Element) -> TestResult:
        name = case.attrib.get("name") or "test"
        status = "passed"
        message = ""
        details = ""
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        node = failure if failure is not None else error if error is not None else skipped
        if failure is not None:
            status = "failed"
        elif error is not None:
            status = "error"
        elif skipped is not None:
            status = "skipped"
        if node is not None:
            message = (node.attrib.get("message") or "").strip()
            details = (node.text or "").strip()
        category, title = _present(name)
        return TestResult(
            name=name,
            classname=case.attrib.get("classname") or "",
            duration=float(case.attrib.get("time") or 0),
            status=status,
            message=message,
            details=details,
            screenshot=self._screenshot_for(name),
            category=category,
            title=title,
        )

    def _screenshot_for(self, test_name: str) -> Optional[Path]:
        if not self.screenshots_dir.exists():
            return None
        matches = sorted(self.screenshots_dir.glob(f"{test_name}_*.png"))
        return matches[-1] if matches else None

    def _render(self, summary: RunSummary) -> str:
        outcome = "Passed" if summary.failed == 0 and summary.errors == 0 and summary.total else "Needs attention"
        tone = "pass" if outcome == "Passed" else "fail"
        cards = [
            ("Total", str(summary.total), "ink"),
            ("Passed", str(summary.passed), "pass"),
            ("Failed", str(summary.failed), "fail"),
            ("Errors", str(summary.errors), "error"),
            ("Skipped", str(summary.skipped), "skip"),
            ("Duration", _clock(summary.duration), "ink"),
        ]
        card_html = "".join(
            f'<article class="stat {kind}"><p>{html.escape(label)}</p><strong>{html.escape(value)}</strong></article>'
            for label, value, kind in cards
        )
        rows = "".join(self._row(test) for test in summary.tests) or (
            '<tr><td colspan="4" class="empty">No tests were collected.</td></tr>'
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Test report · Mobile Script Generator</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@460;560;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --ink: {INK};
      --muted: #5d6b7b;
      --line: #e6ebf1;
      --card: #ffffff;
      --bg: #f3f6fa;
      --pass: {PASS};
      --fail: {FAIL};
      --error: {ERROR};
      --skip: {SKIP};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(1200px 400px at 10% -10%, #e7eefc, transparent), var(--bg);
      color: var(--ink);
      font-family: "Source Sans 3", "Segoe UI", sans-serif;
      font-size: 16px;
      line-height: 1.45;
    }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 64px; }}
    header.hero {{
      display: flex; justify-content: space-between; gap: 24px; align-items: flex-end;
      margin-bottom: 22px;
    }}
    h1 {{
      font-family: Outfit, "Segoe UI", sans-serif;
      font-weight: 700; font-size: 32px; letter-spacing: -0.03em; margin: 0 0 4px;
    }}
    .sub {{ color: var(--muted); margin: 0; }}
    .banner {{
      border-radius: 16px; padding: 14px 18px; color: white; font-family: Outfit, sans-serif;
      font-weight: 700; letter-spacing: 0.01em; min-width: 180px; text-align: right;
    }}
    .banner.pass {{ background: linear-gradient(135deg, #0f9d6e, #147a58); }}
    .banner.fail {{ background: linear-gradient(135deg, #d64545, #a93232); }}
    .banner span {{ display: block; font-family: "Source Sans 3", sans-serif; font-weight: 600; font-size: 14px; opacity: 0.9; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 18px 0 22px; }}
    .stat {{
      background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px;
      box-shadow: 0 8px 24px rgba(28, 36, 48, 0.04);
    }}
    .stat p {{ margin: 0; color: var(--muted); font-size: 13px; letter-spacing: 0.04em; text-transform: uppercase; }}
    .stat strong {{ display: block; margin-top: 4px; font-family: Outfit, sans-serif; font-size: 28px; }}
    .stat.pass strong {{ color: var(--pass); }}
    .stat.fail strong {{ color: var(--fail); }}
    .stat.error strong {{ color: var(--error); }}
    .stat.skip strong {{ color: var(--skip); }}
    .grid {{ display: grid; grid-template-columns: minmax(220px, 280px) 1fr; gap: 16px; margin-bottom: 18px; }}
    section.panel {{
      background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px 18px 8px;
      box-shadow: 0 8px 24px rgba(28, 36, 48, 0.04);
    }}
    section.panel h2 {{
      font-family: Outfit, sans-serif; font-size: 16px; margin: 0 0 8px;
    }}
    table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 16px; overflow: hidden; }}
    .table-wrap {{
      background: var(--card); border: 1px solid var(--line); border-radius: 16px;
      box-shadow: 0 8px 24px rgba(28, 36, 48, 0.04); overflow: hidden;
    }}
    th {{
      text-align: left; font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted);
      padding: 14px 16px; background: #f8fafc; border-bottom: 1px solid var(--line);
    }}
    td {{ padding: 14px 16px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    tr:last-child td {{ border-bottom: 0; }}
    .title {{ font-weight: 600; }}
    .meta {{ color: var(--muted); font-size: 13px; }}
    .pill {{
      display: inline-block; border-radius: 999px; padding: 3px 10px; font-size: 12px; font-weight: 700;
      letter-spacing: 0.04em; text-transform: uppercase;
    }}
    .pill.passed {{ background: #e7f7f0; color: var(--pass); }}
    .pill.failed {{ background: #fdecec; color: var(--fail); }}
    .pill.error {{ background: #fff1e6; color: var(--error); }}
    .pill.skipped {{ background: #eef1f4; color: var(--skip); }}
    .pill.cat {{ background: #eef3fb; color: #2450a4; margin-left: 6px; }}
    details {{ margin-top: 8px; }}
    summary {{ cursor: pointer; color: #2450a4; font-weight: 600; }}
    pre {{
      white-space: pre-wrap; background: #f7f9fb; border-radius: 10px; padding: 10px 12px;
      font-size: 13px; color: #243040;
    }}
    img.shot {{ margin-top: 8px; max-width: 220px; border-radius: 12px; border: 1px solid var(--line); }}
    .empty {{ color: var(--muted); text-align: center; padding: 28px; }}
    .bar-row {{ display: grid; grid-template-columns: 180px 1fr 52px; gap: 8px; align-items: center; margin: 0 0 10px; font-size: 13px; }}
    .track {{ height: 8px; background: #eef2f6; border-radius: 99px; overflow: hidden; }}
    .fill {{ height: 100%; border-radius: 99px; }}
    .legend {{ display: flex; gap: 12px; flex-wrap: wrap; color: var(--muted); font-size: 13px; margin: 4px 0 12px; }}
    .swatch {{ width: 8px; height: 8px; border-radius: 99px; display: inline-block; margin-right: 4px; }}
    @media (max-width: 720px) {{
      header.hero {{ display: block; }}
      .grid {{ grid-template-columns: 1fr; }}
      .banner {{ text-align: left; margin-top: 12px; }}
      .bar-row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="hero">
      <div>
        <h1>Test execution report</h1>
        <p class="sub">Mobile Script Generator - Wireframe · {html.escape(summary.started.strftime("%d %b %Y, %I:%M %p"))}</p>
      </div>
      <div class="banner {tone}">{html.escape(outcome)}<span>{summary.pass_rate}% passed</span></div>
    </header>
    <section class="stats">{card_html}</section>
    <div class="grid">
      <section class="panel">
        <h2>Results</h2>
        {self._donut(summary)}
        <div class="legend">
          <span><i class="swatch" style="background:{PASS}"></i>Passed</span>
          <span><i class="swatch" style="background:{FAIL}"></i>Failed</span>
          <span><i class="swatch" style="background:{ERROR}"></i>Errors</span>
          <span><i class="swatch" style="background:{SKIP}"></i>Skipped</span>
        </div>
      </section>
      <section class="panel">
        <h2>Time per test</h2>
        {self._bars(summary)}
      </section>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Test</th><th>Type</th><th>Status</th><th>Time</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </main>
</body>
</html>
"""

    def _row(self, test: TestResult) -> str:
        extra = ""
        if test.message or test.details or test.screenshot:
            shot = ""
            if test.screenshot and test.screenshot.exists():
                shot = f'<img class="shot" alt="Failure screenshot" src="{html.escape(test.screenshot.resolve().as_uri())}" />'
            extra = (
                "<details><summary>What happened</summary>"
                f"<pre>{html.escape((test.message + chr(10) + test.details).strip())}</pre>{shot}</details>"
            )
        return (
            "<tr>"
            f'<td><div class="title">{html.escape(test.title)}</div><div class="meta">{html.escape(test.name)}</div>{extra}</td>'
            f'<td><span class="pill cat">{html.escape(test.category)}</span></td>'
            f'<td><span class="pill {html.escape(test.status)}">{html.escape(test.status)}</span></td>'
            f"<td>{html.escape(_clock(test.duration))}</td>"
            "</tr>"
        )

    def _donut(self, summary: RunSummary) -> str:
        parts = [
            (summary.passed, PASS),
            (summary.failed, FAIL),
            (summary.errors, ERROR),
            (summary.skipped, SKIP),
        ]
        total = summary.total or 1
        radius = 54
        circ = 2 * 3.14159265 * radius
        offset = 0.0
        arcs = []
        for count, color in parts:
            if not count:
                continue
            length = circ * count / total
            arcs.append(
                f'<circle cx="70" cy="70" r="{radius}" fill="none" stroke="{color}" stroke-width="16" '
                f'stroke-dasharray="{length:.2f} {circ - length:.2f}" stroke-dashoffset="{-offset:.2f}" '
                'stroke-linecap="butt" transform="rotate(-90 70 70)" />'
            )
            offset += length
        if summary.total == 0:
            arcs.append(
                f'<circle cx="70" cy="70" r="{radius}" fill="none" stroke="#e6ebf1" stroke-width="16" />'
            )
        return (
            f'<svg viewBox="0 0 140 140" width="180" height="180" role="img" aria-label="Pass rate chart">'
            + "".join(arcs)
            + f'<text x="70" y="66" text-anchor="middle" font-family="Outfit, Segoe UI, sans-serif" font-size="26" font-weight="700" fill="{INK}">{summary.pass_rate}%</text>'
            + f'<text x="70" y="86" text-anchor="middle" font-family="Source Sans 3, Segoe UI, sans-serif" font-size="12" fill="#5d6b7b">pass rate</text>'
            + "</svg>"
        )

    def _bars(self, summary: RunSummary) -> str:
        if not summary.tests:
            return '<p class="empty">No timing data.</p>'
        peak = max(test.duration for test in summary.tests) or 1
        colors = {"passed": PASS, "failed": FAIL, "error": ERROR, "skipped": SKIP}
        rows = []
        for test in summary.tests:
            width = max(4, round(100 * test.duration / peak))
            color = colors.get(test.status, SKIP)
            rows.append(
                '<div class="bar-row">'
                f'<span>{html.escape(test.title)}</span>'
                f'<div class="track"><div class="fill" style="width:{width}%;background:{color}"></div></div>'
                f"<span>{html.escape(_clock(test.duration))}</span>"
                "</div>"
            )
        return "".join(rows)


def _present(name: str) -> tuple[str, str]:
    text = name[5:] if name.startswith("test_") else name
    category = "scenario"
    for kind in ("positive", "negative", "edge"):
        needle = f"_{kind}_"
        if needle in f"_{text}_":
            category = kind
            text = text.replace(needle, " ", 1)
            break
    title = " ".join(text.replace("_", " ").split()).title()
    return category, title or name


def _clock(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs}s"
