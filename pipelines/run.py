"""Minimal Capstone pipeline - two modes only.

  generate  Wireframe -> SSM -> Appium script with DUMMY locators
  execute   Wireframe -> SSM -> Appium script with on-the-fly locators -> run -> HTML report

Usage:
  python pipelines/run.py generate artifacts/input_screenshots
  python pipelines/run.py execute  artifacts/input_screenshots/Login.png
  python pipelines/run.py execute  artifacts/input_screenshots --no-browser
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.config import load_environment

load_environment(ROOT / ".env")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("pipeline")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _reset_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        try:
            if child.is_file():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            logger.warning("Could not remove %s", child)


def _collect_images(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"Not an image file: {path}")
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"Path not found: {path}")
    images = sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    if not images:
        raise FileNotFoundError(f"No images found in {path}")
    return images


def _prepare_app_path() -> None:
    app_path = os.getenv("APP_PATH", "demo_mobile_apps/mda-2.2.0-25.apk")
    candidate = Path(app_path)
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    os.environ["APP_PATH"] = str(candidate)


def run_generate(images: list[Path]) -> list[Path]:
    from agents.script_generator import ScriptGeneratorAgent
    from agents.step_builder import StepBuilder, load_step_prompt
    from agents.vision_agent import create_vision_agent
    from models.ssm import ScreenSemanticModel

    ssm_dir = ROOT / "artifacts" / "ssm_json_output"
    scripts_dir = ROOT / "artifacts" / "generated_appium_scripts"
    _reset_dir(ssm_dir)
    _reset_dir(scripts_dir)

    provider = os.getenv("VISION_AGENT_PROVIDER", "cursor")
    prompt_path = ROOT / "prompts" / "vision_analysis.txt"
    vision_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else None
    vision = create_vision_agent(provider=provider, prompt_template=vision_prompt)
    steps_agent = StepBuilder(prompt_template=load_step_prompt(ROOT))
    generator = ScriptGeneratorAgent(project_root=ROOT)

    generated: list[Path] = []
    print("\n=== GENERATE: Wireframe -> Appium script (dummy locators) ===")
    for image in images:
        print(f"\n[1/3] Vision analyze -> {image.name}")
        raw = vision.analyze_image(str(image))
        ssm = ScreenSemanticModel.model_validate(raw)
        out = ssm_dir / f"ssm_{ssm.screen_name}_{int(time.time())}.json"
        out.write_text(ssm.model_dump_json(indent=2), encoding="utf-8")
        print(f"      SSM saved -> {out.name}")

        print("[2/3] Build actionable steps")
        step_payload = steps_agent.build_steps(ssm.model_dump())
        print(f"      {len(step_payload.get('steps') or [])} steps for '{step_payload.get('screen')}'")

        print("[3/3] Generate Appium script with DUMMY locators")
        script_path = generator.generate(step_payload, mode="dummy", output_dir=scripts_dir)
        print(f"      Script -> {script_path}")
        generated.append(script_path)

    print("\nGenerate complete. Scripts use dummy locators and are not meant for device runs.")
    return generated


def run_execute(images: list[Path], open_browser: bool = True) -> Path:
    from agents.reporter_agent import ReporterAgent
    from agents.script_generator import ScriptGeneratorAgent
    from agents.step_builder import StepBuilder, load_step_prompt
    from agents.vision_agent import create_vision_agent
    from models.ssm import ScreenSemanticModel

    _prepare_app_path()

    ssm_dir = ROOT / "artifacts" / "ssm_json_output"
    scripts_dir = ROOT / "artifacts" / "generated_appium_scripts"
    resolved_dir = ROOT / "artifacts" / "resolved_locators"
    _reset_dir(ssm_dir)
    _reset_dir(scripts_dir)
    _reset_dir(resolved_dir)
    os.environ["RESOLVED_LOCATORS_DIR"] = str(resolved_dir)

    provider = os.getenv("VISION_AGENT_PROVIDER", "cursor")
    prompt_path = ROOT / "prompts" / "vision_analysis.txt"
    vision_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else None
    vision = create_vision_agent(provider=provider, prompt_template=vision_prompt)
    steps_agent = StepBuilder(prompt_template=load_step_prompt(ROOT))
    generator = ScriptGeneratorAgent(project_root=ROOT)

    print("\n=== EXECUTE: Wireframe -> runtime script -> Appium run -> report ===")
    for image in images:
        print(f"\n[1/3] Vision analyze -> {image.name}")
        raw = vision.analyze_image(str(image))
        ssm = ScreenSemanticModel.model_validate(raw)
        out = ssm_dir / f"ssm_{ssm.screen_name}_{int(time.time())}.json"
        out.write_text(ssm.model_dump_json(indent=2), encoding="utf-8")
        print(f"      SSM saved -> {out.name}")

        print("[2/3] Build steps + generate RUNTIME script (locators fetched on device)")
        step_payload = steps_agent.build_steps(ssm.model_dump())
        script_path = generator.generate(step_payload, mode="runtime", output_dir=scripts_dir)
        print(f"      Script -> {script_path}")

    print("\n[3/3] Run Appium tests + HTML report")
    print(f"      APP_PATH={os.getenv('APP_PATH')}")
    print(f"      APPIUM_SERVER_URL={os.getenv('APPIUM_SERVER_URL', 'http://127.0.0.1:4723')}")
    reporter = ReporterAgent(project_root=ROOT)
    report = reporter.run(scripts_dir=scripts_dir, open_browser=open_browser)
    print(f"\nExecute complete. Report -> {report}")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Minimal Capstone: wireframe -> Appium (generate | execute)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Create Appium scripts with dummy locators")
    gen.add_argument("input", help="Screenshot/wireframe file or folder")

    exe = sub.add_parser("execute", help="Generate runtime scripts, fetch locators live, run, report")
    exe.add_argument("input", help="Screenshot/wireframe file or folder")
    exe.add_argument("--no-browser", action="store_true", help="Do not open HTML report")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    images = _collect_images(Path(args.input))

    if args.command == "generate":
        run_generate(images)
        return 0
    if args.command == "execute":
        run_execute(images, open_browser=not args.no_browser)
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
