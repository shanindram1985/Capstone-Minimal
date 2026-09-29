"""Vision agent: wireframe/screenshot -> Screen Semantic Model (SSM)."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict

from openai import OpenAI
from pydantic import ValidationError

from models.ssm import ScreenSemanticModel

logger = logging.getLogger(__name__)


class VisionAgent(ABC):
    def __init__(self, model_name: str | None = None):
        self.model_name = model_name

    @abstractmethod
    def analyze_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError


class OpenAIVisionAgent(VisionAgent):
    def __init__(self, prompt_template: str | None = None, model_name: str | None = None):
        super().__init__(model_name=model_name or os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.api_base = os.getenv("OPENAI_API_BASE")
        self.prompt_template = prompt_template
        self._client: OpenAI | None = None

    def validate_configuration(self) -> None:
        if not self.api_key:
            raise EnvironmentError("OPENAI_API_KEY is required for OpenAIVisionAgent.")

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.api_base or None)
        return self._client

    def _infer_screen_name(
        self,
        raw_name: str | None,
        image_path: str | None = None,
        screen_purpose: str | None = None,
    ) -> str | None:
        if raw_name:
            normalized = str(raw_name).strip()
            if normalized.lower() not in {"unknown", "unspecified", "n/a", "none", "screen", ""}:
                return normalized

        stem = Path(image_path).stem if image_path else ""
        normalized_stem = stem.lower().replace(" ", "_").replace("-", "_")
        mapping = [
            ("login", "Login"),
            ("cart", "Cart"),
            ("detail", "Product Details"),
            ("listing", "Product Listing"),
            ("product", "Product Listing"),
            ("menu", "Menu"),
            ("checkout", "Checkout"),
            ("home", "Home"),
            ("profile", "Profile"),
            ("settings", "Settings"),
        ]
        for key, name in mapping:
            if key in normalized_stem:
                return name

        if screen_purpose:
            purpose = screen_purpose.lower()
            if "login" in purpose or "authenticate" in purpose:
                return "Login"
            if "cart" in purpose:
                return "Cart"
        return raw_name or None

    def _build_prompt(self, image_b64: str, filename: str | None = None) -> str:
        if self.prompt_template:
            return (
                self.prompt_template.replace("{{image_b64}}", image_b64).replace(
                    "{{filename}}", filename or "image"
                )
            )
        return (
            "Analyze this mobile UI screenshot and return ONLY JSON with "
            "screen_name, screen_purpose, and elements[{label,type,actions,confidence}].\n"
            f"Filename hint: {filename or 'image'}\nIMAGE_BASE64:\n{image_b64}"
        )

    def analyze_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        self.validate_configuration()
        logger.info("[VisionAgent] Analyzing: %s", os.path.basename(image_path))
        with open(image_path, "rb") as handle:
            image_b64 = base64.b64encode(handle.read()).decode("utf-8")

        prompt = self._build_prompt(image_b64, filename=os.path.basename(image_path))
        client = self._get_client()
        request_kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0 if not str(self.model_name).lower().startswith("gpt-5") else 1,
        }
        try:
            resp = client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            if "temperature" in str(exc):
                request_kwargs.pop("temperature", None)
                resp = client.chat.completions.create(**request_kwargs)
            else:
                raise RuntimeError(f"Vision model call failed: {exc}") from exc

        text = (resp.choices[0].message.content or "").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.S)
            if not match:
                raise ValueError("Model response did not contain valid JSON")
            parsed = json.loads(match.group(0))

        try:
            ssm = ScreenSemanticModel.model_validate(parsed)
        except ValidationError as ve:
            raise ValueError(f"Response validation failed: {ve}") from ve

        inferred = self._infer_screen_name(ssm.screen_name, image_path, ssm.screen_purpose)
        if inferred:
            ssm.screen_name = inferred
        ssm.source = image_path
        logger.info(
            "[VisionAgent] SSM for '%s' (%d elements)", ssm.screen_name, len(ssm.elements)
        )
        return ssm.model_dump()


class MockVisionAgent(VisionAgent):
    """Deterministic SSM for offline demos - tuned for SauceLabs Login wireframe."""

    def analyze_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        stem = Path(image_path).stem.lower()
        logger.info("[VisionAgent][Mock] Generating SSM for: %s", Path(image_path).name)

        if "login" in stem:
            return {
                "screen_name": "Login",
                "screen_purpose": "Authenticate user with username and password",
                "source": image_path,
                "elements": [
                    {"label": "Username", "type": "label", "actions": ["verify"], "confidence": 0.9},
                    {
                        "label": "Username Input",
                        "type": "textfield",
                        "actions": ["enter_text"],
                        "confidence": 0.95,
                    },
                    {"label": "Password", "type": "label", "actions": ["verify"], "confidence": 0.9},
                    {
                        "label": "Password Input",
                        "type": "password_field",
                        "actions": ["enter_text"],
                        "confidence": 0.95,
                    },
                    {"label": "Login", "type": "button", "actions": ["tap"], "confidence": 0.95},
                ],
                "metadata": {"provider": "mock"},
            }

        return {
            "screen_name": Path(image_path).stem.replace("_", " ").title(),
            "screen_purpose": "Primary screen actions from wireframe",
            "source": image_path,
            "elements": [
                {"label": "Primary button", "type": "button", "actions": ["tap"], "confidence": 0.7},
                {"label": "Input field", "type": "textfield", "actions": ["enter_text"], "confidence": 0.65},
            ],
            "metadata": {"provider": "mock"},
        }


def create_vision_agent(provider: str = "openai", prompt_template: str | None = None) -> VisionAgent:
    provider = provider.lower().strip()
    if provider == "openai":
        return OpenAIVisionAgent(prompt_template=prompt_template)
    if provider == "mock":
        return MockVisionAgent()
    raise ValueError(f"Unsupported vision provider: {provider}")
