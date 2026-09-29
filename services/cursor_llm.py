"""Shared Cursor helpers.

Preferred path: Cursor Cloud Agents REST API (avoids broken local bridge on
Windows + Python 3.14). Falls back to local SDK when available.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional, Sequence

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


def _http_client():
    """HTTP client using the Windows/macOS system trust store when possible."""
    import ssl

    import httpx

    verify: Any = True
    # Prefer OS trust store (fixes corporate SSL / missing issuer errors on Windows)
    try:
        import truststore

        verify = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        try:
            import certifi

            verify = certifi.where()
        except Exception:
            verify = True

    if os.getenv("CURSOR_SSL_VERIFY", "true").lower() in {"0", "false", "no"}:
        verify = False
    return httpx.Client(timeout=120.0, verify=verify)


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def cursor_prompt(
    text: str,
    *,
    images: Optional[Sequence[object]] = None,
    cwd: Optional[Path | str] = None,
) -> str:
    """One-shot Cursor prompt. Returns assistant text. Uses CURSOR_API_KEY."""
    api_key = require_cursor_api_key()
    model = cursor_model()
    workdir = Path(cwd or Path.cwd()).resolve()

    image_payloads = _normalize_images(images)
    prefer = (os.getenv("CURSOR_RUNTIME", "auto") or "auto").lower().strip()

    errors: list[str] = []

    if prefer in {"auto", "cloud", "rest"}:
        try:
            return _cursor_cloud_rest(api_key, model, text, image_payloads, workdir)
        except Exception as exc:
            errors.append(f"cloud/rest: {exc}")
            logger.warning("[CursorLLM] Cloud/REST path failed: %s", exc)
            if prefer in {"cloud", "rest"}:
                raise RuntimeError("; ".join(errors)) from exc

    if prefer in {"auto", "local", "sdk"}:
        try:
            return _cursor_local_sdk(api_key, model, text, image_payloads, workdir)
        except Exception as exc:
            errors.append(f"local/sdk: {exc}")
            logger.warning("[CursorLLM] Local SDK path failed: %s", exc)
            if prefer in {"local", "sdk"}:
                raise RuntimeError("; ".join(errors)) from exc

    raise RuntimeError(
        "Cursor AI call failed. "
        + " | ".join(errors)
        + " Tip: on Windows use Python 3.12 venv, set CURSOR_API_KEY, "
        "and optionally CURSOR_GITHUB_REPO=owner/name for cloud runtime."
    )


def _normalize_images(images: Optional[Sequence[object]]) -> list[dict[str, str]]:
    payloads: list[dict[str, str]] = []
    if not images:
        return payloads
    for image in images:
        data = None
        mime = "image/png"
        if isinstance(image, dict):
            data = image.get("data")
            mime = image.get("mime_type") or image.get("mimeType") or mime
        else:
            data = getattr(image, "data", None)
            mime = getattr(image, "mime_type", None) or mime
        if data:
            payloads.append({"data": str(data), "mime_type": str(mime)})
    return payloads


def _cursor_local_sdk(
    api_key: str,
    model: str,
    text: str,
    image_payloads: list[dict[str, str]],
    workdir: Path,
) -> str:
    from cursor_sdk import (
        Agent,
        AgentOptions,
        CursorAgentError,
        LocalAgentOptions,
        SDKImage,
        UserMessage,
    )

    sdk_images = [
        SDKImage(data=item["data"], mime_type=item["mime_type"]) for item in image_payloads
    ]
    message: str | UserMessage
    if sdk_images:
        message = UserMessage(text=text, images=sdk_images)
    else:
        message = text

    logger.info("[CursorLLM][sdk] model=%s cwd=%s images=%d", model, workdir, len(sdk_images))
    try:
        result = Agent.prompt(
            message,
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=str(workdir)),
            ),
        )
    except CursorAgentError as exc:
        raise RuntimeError(
            f"Cursor Agent failed to start: {exc} (retryable={getattr(exc, 'is_retryable', None)})"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Cursor local bridge failed on this Python/OS ({exc}). "
            "Use Python 3.12 or set CURSOR_RUNTIME=cloud."
        ) from exc

    if getattr(result, "status", None) == "error":
        raise RuntimeError(f"Cursor Agent run failed: id={getattr(result, 'id', None)}")
    return (result.result or "").strip()


def _cursor_cloud_rest(
    api_key: str,
    model: str,
    text: str,
    image_payloads: list[dict[str, str]],
    workdir: Path,
) -> str:
    """Call https://api.cursor.com Cloud Agents API (no local bridge)."""
    prompt_obj: dict[str, Any] = {
        "text": text
        + "\n\nIMPORTANT: Respond with ONLY valid JSON matching the requested schema. "
        "No markdown fences, no repo edits, no tool chatter."
    }
    if image_payloads:
        prompt_obj["images"] = [
            {"data": item["data"], "mimeType": item["mime_type"]} for item in image_payloads
        ]

    body: dict[str, Any] = {
        "prompt": prompt_obj,
        "model": {"id": model},
        "name": "capstone-minimal-vision",
    }

    # Optional: bind a GitHub repo. Prefer no-repo agents for vision JSON tasks.
    repo = (os.getenv("CURSOR_GITHUB_REPO") or "").strip()
    if repo:
        repo_url = repo if repo.startswith("http") else f"https://github.com/{repo}"
        branch = (os.getenv("CURSOR_GITHUB_REF") or "master").strip()
        body["repos"] = [{"url": repo_url, "startingRef": branch}]
        body["autoCreatePR"] = False

    logger.info(
        "[CursorLLM][cloud] model=%s images=%d repo=%s",
        model,
        len(image_payloads),
        bool(repo),
    )
    with _http_client() as client:
        create = client.post(
            "https://api.cursor.com/v1/agents",
            headers=_auth_headers(api_key),
            json=body,
        )
        if create.status_code >= 400:
            raise RuntimeError(f"Create agent HTTP {create.status_code}: {create.text[:800]}")
        payload = create.json()
        agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else payload
        run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
        agent_id = (
            (agent or {}).get("id")
            or payload.get("id")
            or payload.get("agentId")
        )
        run_id = (run or {}).get("id") or payload.get("runId")
        if not agent_id:
            raise RuntimeError(f"Unexpected create-agent response: {payload}")

        # Immediate text if present
        for candidate in (
            (run or {}).get("result"),
            payload.get("result"),
            (agent or {}).get("result"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        deadline = time.monotonic() + float(os.getenv("CURSOR_CLOUD_TIMEOUT_SEC", "180"))
        last_status = None
        while time.monotonic() < deadline:
            # Prefer run status when available
            if run_id:
                status_resp = client.get(
                    f"https://api.cursor.com/v1/agents/{agent_id}/runs/{run_id}",
                    headers=_auth_headers(api_key),
                )
            else:
                status_resp = client.get(
                    f"https://api.cursor.com/v1/agents/{agent_id}",
                    headers=_auth_headers(api_key),
                )
            if status_resp.status_code >= 400:
                raise RuntimeError(
                    f"Get agent/run HTTP {status_resp.status_code}: {status_resp.text[:800]}"
                )
            info = status_resp.json()
            last_status = (
                info.get("status")
                or info.get("state")
                or (info.get("run") or {}).get("status")
            )
            if str(last_status).upper() in {"FINISHED", "COMPLETED", "DONE", "SUCCESS"}:
                text_out = _extract_agent_text(client, api_key, agent_id, info)
                if text_out:
                    return text_out
                # Also try conversation
                text_out = _extract_agent_text(client, api_key, agent_id, {"id": agent_id})
                if text_out:
                    return text_out
                raise RuntimeError(f"Agent finished but no text result: {info}")
            if str(last_status).upper() in {"ERROR", "FAILED", "CANCELLED", "CANCELED"}:
                raise RuntimeError(f"Cloud agent failed: {info}")
            time.sleep(3)

        raise TimeoutError(f"Cloud agent timed out (last status={last_status}, id={agent_id})")


def _extract_agent_text(client: Any, api_key: str, agent_id: str, info: dict[str, Any]) -> str:
    for key in ("result", "summary", "output", "text"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Conversation / messages endpoint fallbacks
    for path in (
        f"https://api.cursor.com/v1/agents/{agent_id}/conversation",
        f"https://api.cursor.com/v1/agents/{agent_id}/messages",
    ):
        try:
            resp = client.get(path, headers=_auth_headers(api_key))
            if resp.status_code >= 400:
                continue
            data = resp.json()
            text = _text_from_messages(data)
            if text:
                return text
        except Exception:
            continue
    return ""


def _text_from_messages(data: Any) -> str:
    if isinstance(data, dict):
        if isinstance(data.get("text"), str) and data["text"].strip():
            return data["text"].strip()
        messages = data.get("messages") or data.get("items") or data.get("conversation") or []
    elif isinstance(data, list):
        messages = data
    else:
        return ""

    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or message.get("type") or "").lower()
        if role not in {"assistant", "ai", "model", ""} and "assistant" not in role:
            # still accept if it looks like final content
            pass
        content = message.get("content") or message.get("text") or message.get("result")
        if isinstance(content, str) and content.strip():
            parts.append(content.strip())
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                    t = block.get("text") or block.get("content")
                    if isinstance(t, str) and t.strip():
                        parts.append(t.strip())
    return "\n".join(parts).strip()
