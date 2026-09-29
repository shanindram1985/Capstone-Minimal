"""Shared Cursor SDK helpers (billed via CURSOR_API_KEY, not OpenAI)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger(__name__)


def require_cursor_api_key() -> str:
    key = (os.getenv("CURSOR_API_KEY") or "").strip()
    if not key:
        raise EnvironmentError(
            "CURSOR_API_KEY is required for Cursor AI. "
            "Create one at https://cursor.com/dashboard/integrations and set it in .env"
        )
    return key


def cursor_model() -> str:
    return (os.getenv("CURSOR_MODEL") or "composer-2.5").strip()


def cursor_prompt(
    text: str,
    *,
    images: Optional[Sequence[object]] = None,
    cwd: Optional[Path | str] = None,
) -> str:
    """One-shot Cursor Agent prompt. Returns assistant text. Uses CURSOR_API_KEY."""
    from cursor_sdk import (
        Agent,
        AgentOptions,
        CursorAgentError,
        LocalAgentOptions,
        SDKImage,
        UserMessage,
    )

    api_key = require_cursor_api_key()
    model = cursor_model()
    workdir = str(Path(cwd or Path.cwd()).resolve())

    sdk_images = []
    for image in images or []:
        if isinstance(image, SDKImage):
            sdk_images.append(image)
        elif isinstance(image, dict):
            sdk_images.append(SDKImage(**image))
        else:
            raise TypeError(f"Unsupported image type: {type(image)}")

    message: str | UserMessage
    if sdk_images:
        message = UserMessage(text=text, images=sdk_images)
    else:
        message = text

    logger.info("[CursorLLM] model=%s cwd=%s images=%d", model, workdir, len(sdk_images))
    try:
        result = Agent.prompt(
            message,
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=workdir),
            ),
        )
    except CursorAgentError as exc:
        raise RuntimeError(
            f"Cursor Agent failed to start: {exc} (retryable={getattr(exc, 'is_retryable', None)})"
        ) from exc

    if getattr(result, "status", None) == "error":
        raise RuntimeError(f"Cursor Agent run failed: id={getattr(result, 'id', None)}")

    return (result.result or "").strip()
