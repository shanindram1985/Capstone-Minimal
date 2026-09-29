"""Resolve UI locators on-the-fly from a live Appium session."""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Exact SauceLabs My Demo App IDs / text. Prefer these over fuzzy page-source scoring.
SAUCELABS_HINTS: Dict[str, Tuple[str, str]] = {
    "username": ("resource_id", "com.saucelabs.mydemoapp.android:id/nameET"),
    "username_input": ("resource_id", "com.saucelabs.mydemoapp.android:id/nameET"),
    "password": ("resource_id", "com.saucelabs.mydemoapp.android:id/passwordET"),
    "password_input": ("resource_id", "com.saucelabs.mydemoapp.android:id/passwordET"),
    "login": ("resource_id", "com.saucelabs.mydemoapp.android:id/loginBtn"),
    "login_button": ("resource_id", "com.saucelabs.mydemoapp.android:id/loginBtn"),
    # Drawer menu entry (NOT the login form button)
    "log_in": ("text", "Log In"),
    "menu": ("resource_id", "com.saucelabs.mydemoapp.android:id/menuIV"),
    "hamburger": ("resource_id", "com.saucelabs.mydemoapp.android:id/menuIV"),
    "cart": ("resource_id", "com.saucelabs.mydemoapp.android:id/cartIV"),
}

# Clickable-only bonus must not win when the real control is hidden behind a dialog.
MIN_PAGE_SOURCE_SCORE = 20


@dataclass
class ResolvedLocator:
    label: str
    strategy: str
    value: str
    score: int
    source: str


class RuntimeLocatorResolver:
    def __init__(self, driver: Any, wait: Any = None, dump_dir: Optional[Path] = None) -> None:
        self.driver = driver
        self.wait = wait
        self.dump_dir = dump_dir
        self._cache: Dict[str, ResolvedLocator] = {}

    def resolve(self, label: str, prefer_editable: bool = False) -> Tuple[str, str]:
        key = f"{label}|{prefer_editable}"
        if key in self._cache:
            cached = self._cache[key]
            return cached.strategy, cached.value

        page_source = self.driver.page_source
        if self.dump_dir:
            self.dump_dir.mkdir(parents=True, exist_ok=True)
            dump_path = self.dump_dir / f"page_source_{_slug(label)}.xml"
            dump_path.write_text(page_source, encoding="utf-8")

        # 1) Prefer known SauceLabs locator when that node is actually on screen.
        hint = self._hint_for(label)
        if hint and self._hint_present(page_source, hint):
            resolved = ResolvedLocator(label, hint[0], hint[1], 200, "saucelabs_hint_present")
        else:
            # 2) Fuzzy match from page source (require meaningful token score).
            resolved = self._resolve_from_page_source(
                label, page_source, prefer_editable=prefer_editable
            )
            # 3) Fall back to hint even if not yet visible (caller wait may still succeed).
            if resolved is None and hint:
                resolved = ResolvedLocator(label, hint[0], hint[1], 50, "saucelabs_hint")

        if resolved is None:
            raise LookupError(f"Could not resolve live locator for label '{label}'")

        self._cache[key] = resolved
        self._persist(resolved)
        logger.info(
            "[RuntimeLocator] '%s' -> %s=%s (%s, score=%d)",
            label,
            resolved.strategy,
            resolved.value,
            resolved.source,
            resolved.score,
        )
        return resolved.strategy, resolved.value

    def _hint_present(self, page_source: str, hint: Tuple[str, str]) -> bool:
        strategy, value = hint
        if strategy == "resource_id":
            return value in page_source
        if strategy == "accessibility_id":
            return f'content-desc="{value}"' in page_source or value in page_source
        if strategy == "text":
            return f'text="{value}"' in page_source
        return value in page_source

    def _resolve_from_page_source(
        self, label: str, page_source: str, prefer_editable: bool
    ) -> Optional[ResolvedLocator]:
        try:
            root = ET.fromstring(page_source)
        except ET.ParseError:
            logger.warning("[RuntimeLocator] Failed to parse page source XML")
            return None

        tokens = _tokens(label)
        candidates: List[ResolvedLocator] = []
        hint = self._hint_for(label)

        for node in root.iter():
            attrs = node.attrib
            resource_id = attrs.get("resource-id") or attrs.get("resourceId") or ""
            content_desc = attrs.get("content-desc") or attrs.get("contentDescription") or ""
            text = attrs.get("text") or ""
            class_name = attrs.get("class") or attrs.get("className") or ""
            clickable = (attrs.get("clickable") or "").lower() == "true"
            password = (attrs.get("password") or "").lower() == "true"

            # Ignore system alert chrome (16KB compat dialog, etc.)
            if resource_id.startswith("android:id/") and "saucelabs" not in resource_id:
                continue

            score = 0
            strategy = None
            value = None
            source = "page_source"

            blob = f"{resource_id} {content_desc} {text}".lower()
            token_hits = 0
            for token in tokens:
                if token and token in blob:
                    score += 10
                    token_hits += 1
                if token and token in resource_id.lower():
                    score += 15
                if token and token in content_desc.lower():
                    score += 12
                if token and token in text.lower():
                    score += 8

            if prefer_editable:
                if "edittext" in class_name.lower() or password:
                    score += 20
                elif "textview" in class_name.lower() and not clickable:
                    score -= 10

            if not prefer_editable and clickable:
                score += 5

            if hint and hint[0] == "resource_id" and resource_id == hint[1]:
                score += 100
                strategy, value = hint
                source = "saucelabs_page_match"
            elif hint and hint[0] == "text" and text == hint[1]:
                score += 100
                strategy, value = hint
                source = "saucelabs_page_match"
            elif hint and hint[0] == "accessibility_id" and content_desc == hint[1]:
                score += 100
                strategy, value = hint
                source = "saucelabs_page_match"

            # Reject pure clickable noise (e.g. dialog OK with score 5).
            if score < MIN_PAGE_SOURCE_SCORE and source == "page_source":
                continue
            if token_hits == 0 and source == "page_source":
                continue

            if strategy is None:
                if resource_id:
                    strategy, value = "resource_id", resource_id
                elif content_desc:
                    strategy, value = "accessibility_id", content_desc
                elif text:
                    strategy, value = "text", text
                else:
                    continue

            candidates.append(ResolvedLocator(label, strategy, value, score, source))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[0]

    def _hint_for(self, label: str) -> Optional[Tuple[str, str]]:
        key = _slug(label)
        return SAUCELABS_HINTS.get(key)

    def _persist(self, resolved: ResolvedLocator) -> None:
        if not self.dump_dir:
            return
        out = self.dump_dir / "resolved_locators.json"
        payload: Dict[str, Any] = {}
        if out.exists():
            try:
                payload = json.loads(out.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        payload[resolved.label] = {
            "strategy": resolved.strategy,
            "value": resolved.value,
            "score": resolved.score,
            "source": resolved.source,
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _tokens(label: str) -> List[str]:
    parts = re.findall(r"[a-z0-9]+", label.lower())
    stop = {"input", "field", "button", "label", "the", "a", "an"}
    return [p for p in parts if p not in stop and len(p) > 1]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
