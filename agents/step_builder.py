"""Build ordered actionable steps from SSM (no manual testcases)."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from openai import OpenAI

logger = logging.getLogger(__name__)

DEMO_USERNAME = "bod@example.com"
DEMO_PASSWORD = "10203040"

ACTIONABLE_TYPES = {
    "textfield",
    "password_field",
    "email_field",
    "search_field",
    "button",
    "icon_button",
    "checkbox",
    "list",
    "dropdown",
    "link",
    "stepper",
}


class StepBuilder:
    """Derive Appium steps from SSM using heuristics or optional LLM."""

    def __init__(self, prompt_template: str | None = None) -> None:
        self.prompt_template = prompt_template
        self.provider = os.getenv("STEP_BUILDER_PROVIDER", "heuristic").lower().strip()

    def build_steps(self, ssm: Dict[str, Any]) -> Dict[str, Any]:
        if self.provider == "openai" and os.getenv("OPENAI_API_KEY"):
            try:
                return self._build_with_llm(ssm)
            except Exception as exc:
                logger.warning("[StepBuilder] LLM failed (%s); using heuristics", exc)
        return self._build_heuristic(ssm)

    def _build_heuristic(self, ssm: Dict[str, Any]) -> Dict[str, Any]:
        screen = ssm.get("screen_name") or "Screen"
        steps: List[Dict[str, Any]] = []
        for element in ssm.get("elements") or []:
            label = str(element.get("label") or "").strip()
            etype = str(element.get("type") or "unknown").lower().replace("-", "_")
            if not label or etype not in ACTIONABLE_TYPES:
                continue
            if etype in {"textfield", "password_field", "email_field", "search_field"}:
                steps.append(
                    {
                        "element": label,
                        "action": "type",
                        "input_value": self._default_input(label, etype),
                    }
                )
            elif etype == "list":
                steps.append({"element": label, "action": "scroll"})
            else:
                steps.append({"element": label, "action": "tap"})
        return {"screen": screen, "steps": steps}

    def _default_input(self, label: str, etype: str) -> str:
        lowered = label.lower()
        if "pass" in lowered or etype == "password_field":
            return DEMO_PASSWORD
        if "user" in lowered or "email" in lowered or "name" in lowered:
            return DEMO_USERNAME
        return "test"

    def _build_with_llm(self, ssm: Dict[str, Any]) -> Dict[str, Any]:
        prompt = (self.prompt_template or "") + "\n\nSSM JSON:\n" + json.dumps(ssm, indent=2)
        client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_API_BASE") or None,
        )
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.S)
            if not match:
                raise ValueError("StepBuilder LLM response was not JSON")
            parsed = json.loads(match.group(0))
        if "steps" not in parsed:
            raise ValueError("StepBuilder LLM JSON missing steps")
        parsed.setdefault("screen", ssm.get("screen_name") or "Screen")
        return parsed


def load_step_prompt(project_root: Path) -> str | None:
    path = project_root / "prompts" / "script_steps.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None
