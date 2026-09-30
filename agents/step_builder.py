"""Build ordered actionable steps from SSM, plus a manual test-case document."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

DEMO_USERNAME = "bod@example.com"
DEMO_PASSWORD = "10203040"
MISMATCH = "Provided credentials do not match any user in this service."
LOCKED_OUT = "Sorry, this user has been locked out."

INPUT_TYPES = {"textfield", "password_field", "email_field", "search_field"}
TAP_TYPES = {"button", "icon_button", "checkbox", "dropdown", "link", "stepper"}
ACTIONABLE_TYPES = INPUT_TYPES | TAP_TYPES | {"list"}

CHROME_WORDS = {"menu", "hamburger", "back", "logo", "cart", "mydemoapp", "home", "close"}
PRIMARY_WORDS = (
    "login",
    "log in",
    "sign in",
    "signin",
    "submit",
    "continue",
    "next",
    "checkout",
    "check out",
    "pay",
    "place order",
    "add to cart",
    "add",
    "apply",
    "save",
    "search",
    "register",
    "sign up",
    "create",
    "confirm",
    "done",
    "buy",
    "update",
    "send",
)


class StepBuilder:
    """Derive Appium steps from SSM using heuristics or optional LLM (Cursor preferred)."""

    def __init__(self, prompt_template: str | None = None) -> None:
        self.prompt_template = prompt_template
        self.provider = os.getenv("STEP_BUILDER_PROVIDER", "heuristic").lower().strip()
        self.project_root = Path(__file__).resolve().parents[1]

    def build_steps(self, ssm: Dict[str, Any]) -> Dict[str, Any]:
        """Return the steps-only payload the script generator already consumes."""
        if self.provider in {"cursor", "cursor_sdk", "cursor-ai"} and os.getenv("CURSOR_API_KEY"):
            try:
                return self._build_with_cursor(ssm)
            except Exception as exc:
                logger.warning("[StepBuilder] Cursor LLM failed (%s); using heuristics", exc)
        if self.provider == "openai" and os.getenv("OPENAI_API_KEY"):
            try:
                return self._build_with_openai(ssm)
            except Exception as exc:
                logger.warning("[StepBuilder] OpenAI failed (%s); using heuristics", exc)
        return self._build_heuristic(ssm)

    def write_artifacts(self, step_payload: Dict[str, Any], output_root: Path | None = None) -> Dict[str, Path]:
        """Save the steps payload and a manual test-case document for the same cases."""
        root = output_root or self.project_root
        screen = str(step_payload.get("screen") or "Screen")
        slug = _slug(screen)
        steps_dir = root / "artifacts" / "step_output"
        manual_dir = root / "artifacts" / "manual_test_cases"
        steps_dir.mkdir(parents=True, exist_ok=True)
        manual_dir.mkdir(parents=True, exist_ok=True)

        steps_path = steps_dir / f"{slug}_steps.json"
        manual_path = manual_dir / f"{slug}_manual_test_cases.md"
        steps_path.write_text(json.dumps(step_payload, indent=2) + "\n", encoding="utf-8")
        manual_path.write_text(render_manual_cases(step_payload), encoding="utf-8")
        logger.info("[StepBuilder] Wrote %s and %s", steps_path.name, manual_path.name)
        return {"steps": steps_path, "manual": manual_path}

    def _build_heuristic(self, ssm: Dict[str, Any]) -> Dict[str, Any]:
        screen = str(ssm.get("screen_name") or "Screen")
        return {"screen": screen, "cases": self._coverage_cases(ssm)}

    def _coverage_cases(self, ssm: Dict[str, Any]) -> List[Dict[str, Any]]:
        screen = str(ssm.get("screen_name") or "Screen")
        fields, actions, lists, verify = _analyze(ssm)
        if _looks_like_login(screen, fields, actions):
            return self._login_cases(ssm)
        cases = _form_cases(screen, fields, actions, verify)
        cases.extend(_action_cases(screen, actions, lists, verify, already=cases))
        cases.extend(_retail_bounds(screen, fields, actions, verify))
        cases = _ensure_categories(screen, cases, actions, lists, verify)
        if not cases:
            cases.append(
                _case(
                    "screen_visible",
                    "positive",
                    f"{screen} is shown",
                    [{"element": verify or screen, "action": "verify"}] if verify or screen else [],
                )
            )
        return [case for case in cases if case.get("steps")]

    def _login_cases(self, ssm: Dict[str, Any]) -> List[Dict[str, Any]]:
        fields, actions, _lists, _verify = _analyze(ssm)
        user = _field_label(fields, ("username", "email", "user"), "Username Input")
        password = _field_label(fields, ("password", "pass"), "Password Input")
        submit = _action_label(actions, ("login", "log in", "sign in", "submit"), "Login")

        def flow(username: str, secret: str, verify: str) -> List[Dict[str, Any]]:
            return [
                {"element": user, "action": "type", "input_value": username},
                {"element": password, "action": "type", "input_value": secret},
                {"element": submit, "action": "tap"},
                {"element": verify, "action": "verify"},
            ]

        return [
            _case("valid_standard_user", "positive", "Catalog opens for the standard demo user", flow(DEMO_USERNAME, DEMO_PASSWORD, "Products")),
            _case("valid_visual_user", "positive", "Catalog opens for the visual demo user", flow("visual@example.com", DEMO_PASSWORD, "Products")),
            _case("locked_out_user", "negative", "Locked-out account is rejected", flow("alice@example.com", DEMO_PASSWORD, LOCKED_OUT)),
            _case("invalid_password", "negative", "Wrong password is rejected", flow(DEMO_USERNAME, "invalid-pass", MISMATCH)),
            _case("unknown_user", "negative", "Unknown account is rejected", flow("nobody@example.com", DEMO_PASSWORD, MISMATCH)),
            _case("empty_credentials", "negative", "Empty username is rejected", flow("", "", "Username is required")),
            _case("missing_password", "negative", "Missing password is rejected", flow(DEMO_USERNAME, "", "Password is required")),
            _case("missing_username", "negative", "Missing username is rejected", flow("", DEMO_PASSWORD, "Username is required")),
            _case("whitespace_username", "edge", "Whitespace username does not authenticate", flow("   ", DEMO_PASSWORD, MISMATCH)),
            _case("whitespace_password", "edge", "Whitespace password does not authenticate", flow(DEMO_USERNAME, "   ", MISMATCH)),
            _case("oversized_credentials", "edge", "Oversized input does not authenticate", flow("a" * 120, "b" * 120, MISMATCH)),
            _case("special_characters", "edge", "Special characters do not authenticate", flow("user<>&@", "p@ss w0rd!", MISMATCH)),
        ]

    def _parse_steps_json(self, text: str, ssm: Dict[str, Any]) -> Dict[str, Any]:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.S)
            if not match:
                raise ValueError("StepBuilder LLM response was not JSON")
            parsed = json.loads(match.group(0))
        screen = str(parsed.get("screen") or ssm.get("screen_name") or "Screen")
        cases = parsed.get("cases")
        if not isinstance(cases, list):
            cases = []
        cases = _keep_ssm_controls(cases, ssm)
        categories = {str(case.get("category") or "") for case in cases if isinstance(case, dict)}
        if not {"positive", "negative", "edge"} <= categories or len(cases) < 4:
            logger.warning("[StepBuilder] Coverage was thin for '%s'; using SSM retail cases", screen)
            cases = self._coverage_cases(ssm)
        return {"screen": screen, "cases": cases}

    def _build_with_cursor(self, ssm: Dict[str, Any]) -> Dict[str, Any]:
        from services.cursor_llm import cursor_prompt

        prompt = (self.prompt_template or "") + "\n\nSSM JSON:\n" + json.dumps(ssm, indent=2)
        text = cursor_prompt(prompt, cwd=self.project_root)
        return self._parse_steps_json(text, ssm)

    def _build_with_openai(self, ssm: Dict[str, Any]) -> Dict[str, Any]:
        from openai import OpenAI

        prompt = (self.prompt_template or "") + "\n\nSSM JSON:\n" + json.dumps(ssm, indent=2)
        client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_API_BASE") or None,
        )
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        return self._parse_steps_json(text, ssm)


def _retail_bounds(
    screen: str,
    fields: List[Dict[str, str]],
    actions: List[Dict[str, str]],
    verify: str,
) -> List[Dict[str, Any]]:
    """Extra shopper boundaries that a generic form pass does not name."""
    qty = [field for field in fields if field["kind"] == "qty"]
    if not qty:
        return []
    primary = _primary_action(actions)
    stay = verify or screen

    def fill(value: str) -> List[Dict[str, Any]]:
        steps = [{"element": field["label"], "action": "type", "input_value": value} for field in qty]
        for field in fields:
            if field["kind"] != "qty":
                steps.append({"element": field["label"], "action": "type", "input_value": field["valid"]})
        if primary:
            steps.append({"element": primary, "action": "tap"})
        if stay:
            steps.append({"element": stay, "action": "verify"})
        return steps

    return [
        _case("quantity_upper_bound", "edge", f"{screen} handles a large item quantity", fill("99")),
    ]


def _ensure_categories(
    screen: str,
    cases: List[Dict[str, Any]],
    actions: List[Dict[str, str]],
    lists: List[str],
    verify: str,
) -> List[Dict[str, Any]]:
    present = {str(case.get("category") or "") for case in cases}
    stay = verify or screen
    if "positive" not in present and stay:
        cases.append(_case("screen_visible", "positive", f"{screen} is shown", [{"element": stay, "action": "verify"}]))
    if "negative" not in present:
        guarded = _action_label(actions, ("checkout", "pay", "place order", "remove", "delete", "add to cart"), "")
        if guarded:
            steps: List[Dict[str, Any]] = [{"element": guarded, "action": "tap"}]
            if stay:
                steps.append({"element": stay, "action": "verify"})
            cases.append(
                _case(
                    "action_without_required_setup",
                    "negative",
                    f"{screen} does not complete {guarded} without the required shopper input",
                    steps,
                )
            )
    if "edge" not in present and lists:
        steps = [{"element": lists[0], "action": "scroll"}]
        if stay:
            steps.append({"element": stay, "action": "verify"})
        cases.append(_case("scroll_to_end", "edge", f"{screen} catalog still renders after a long scroll", steps))
    return cases


def _keep_ssm_controls(cases: List[Any], ssm: Dict[str, Any]) -> List[Dict[str, Any]]:
    allowed = {str(element.get("label") or "").strip() for element in ssm.get("elements") or [] if element.get("label")}
    if not allowed:
        return [case for case in cases if isinstance(case, dict)]
    kept: List[Dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        steps = []
        for step in case.get("steps") or []:
            action = str(step.get("action") or "")
            element = str(step.get("element") or "")
            if action in {"type", "tap", "scroll"} and element not in allowed:
                continue
            steps.append(step)
        if steps:
            copied = dict(case)
            copied["steps"] = steps
            kept.append(copied)
    return kept


def _case(name: str, category: str, expected: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"name": name, "category": category, "expected": expected, "steps": steps}


def _analyze(ssm: Dict[str, Any]) -> tuple[List[Dict[str, str]], List[Dict[str, str]], List[str], str]:
    screen = str(ssm.get("screen_name") or "Screen")
    fields: List[Dict[str, str]] = []
    actions: List[Dict[str, str]] = []
    lists: List[str] = []
    labels: List[str] = []
    for element in ssm.get("elements") or []:
        label = str(element.get("label") or "").strip()
        etype = str(element.get("type") or "unknown").lower().replace("-", "_")
        if not label:
            continue
        if etype == "label":
            labels.append(label)
            continue
        if _is_chrome(label, screen):
            continue
        if etype in INPUT_TYPES:
            kind = _field_kind(label, etype)
            fields.append({"label": label, "kind": kind, "valid": _valid_value(kind, label), "invalid": _invalid_value(kind)})
        elif etype == "list":
            lists.append(label)
        elif etype in TAP_TYPES:
            actions.append({"label": label, "type": etype})
    verify = _verify_target(screen, labels)
    return fields, actions, lists, verify


def _form_cases(
    screen: str,
    fields: List[Dict[str, str]],
    actions: List[Dict[str, str]],
    verify: str,
) -> List[Dict[str, Any]]:
    if not fields:
        return []
    primary = _primary_action(actions)
    stay = verify or screen

    def fill(overrides: Dict[str, str], include_primary: bool = True) -> List[Dict[str, Any]]:
        steps = [
            {"element": field["label"], "action": "type", "input_value": overrides.get(field["label"], field["valid"])}
            for field in fields
        ]
        if include_primary and primary:
            steps.append({"element": primary, "action": "tap"})
        if stay:
            steps.append({"element": stay, "action": "verify"})
        return steps

    cases = [
        _case("valid_input", "positive", f"{screen} accepts valid field values", fill({})),
        _case("empty_inputs", "negative", f"{screen} rejects empty fields", fill({field["label"]: "" for field in fields})),
    ]
    for field in fields[:6]:
        slug = _slug(field["label"])
        missing = {field["label"]: ""}
        cases.append(
            _case(f"missing_{slug}", "negative", f"{screen} rejects an empty {field['label']}", fill(missing))
        )
        if field["invalid"]:
            cases.append(
                _case(
                    f"invalid_{slug}",
                    "negative",
                    f"{screen} rejects invalid {field['label']}",
                    fill({field["label"]: field["invalid"]}),
                )
            )
    cases.append(
        _case(
            "whitespace_inputs",
            "edge",
            f"{screen} handles whitespace-only input",
            fill({field["label"]: "   " for field in fields}),
        )
    )
    cases.append(
        _case(
            "oversized_inputs",
            "edge",
            f"{screen} handles oversized input",
            fill({field["label"]: "x" * 120 for field in fields}),
        )
    )
    cases.append(
        _case(
            "special_characters",
            "edge",
            f"{screen} handles special characters",
            fill({field["label"]: "a<>&@#" for field in fields}),
        )
    )
    numeric = [field for field in fields if field["kind"] in {"number", "phone", "qty", "zip"}]
    if numeric:
        cases.append(
            _case(
                "numeric_boundary_zero",
                "edge",
                f"{screen} handles a zero boundary",
                fill({field["label"]: "0" for field in numeric}),
            )
        )
        cases.append(
            _case(
                "numeric_boundary_large",
                "edge",
                f"{screen} handles a large boundary",
                fill({field["label"]: "999999" for field in numeric}),
            )
        )
    return cases


def _action_cases(
    screen: str,
    actions: List[Dict[str, str]],
    lists: List[str],
    verify: str,
    already: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    used = {step.get("element") for case in already for step in case.get("steps") or [] if step.get("action") == "tap"}
    stay = verify or screen
    extras = [action for action in actions if action["label"] not in used]
    for action in extras[:4]:
        steps: List[Dict[str, Any]] = [{"element": action["label"], "action": "tap"}]
        if stay:
            steps.append({"element": stay, "action": "verify"})
        cases.append(
            _case(
                f"tap_{_slug(action['label'])}",
                "positive",
                f"{screen} exposes {action['label']}",
                steps,
            )
        )
    for label in lists[:2]:
        steps = [{"element": label, "action": "scroll"}]
        if stay:
            steps.append({"element": stay, "action": "verify"})
        cases.append(_case(f"scroll_{_slug(label)}", "positive", f"{screen} list can be scrolled", steps))
    if not already and stay:
        cases.insert(0, _case("screen_visible", "positive", f"{screen} is shown", [{"element": stay, "action": "verify"}]))
    return cases


def _looks_like_login(screen: str, fields: List[Dict[str, str]], actions: List[Dict[str, str]]) -> bool:
    kinds = {field["kind"] for field in fields}
    labels = " ".join(action["label"].lower() for action in actions)
    has_secret = "password" in kinds
    has_identity = bool(kinds & {"email", "username"})
    has_submit = any(word in labels for word in ("login", "log in", "sign in", "submit"))
    named_login = "login" in screen.lower() or "sign in" in screen.lower()
    return has_secret and has_identity and (has_submit or named_login)


def _field_kind(label: str, etype: str) -> str:
    text = label.lower()
    if etype == "password_field" or "pass" in text:
        return "password"
    if etype == "email_field" or "email" in text or "e-mail" in text:
        return "email"
    if any(word in text for word in ("promo", "coupon", "voucher")):
        return "promo"
    if "cvv" in text or "cvc" in text:
        return "cvv"
    if "card" in text:
        return "card"
    if any(word in text for word in ("qty", "quantity")):
        return "qty"
    if any(word in text for word in ("zip", "postal")):
        return "zip"
    if any(word in text for word in ("phone", "mobile", "tel")):
        return "phone"
    if "user" in text:
        return "username"
    if etype == "search_field" or "search" in text or "query" in text:
        return "search"
    if any(word in text for word in ("address", "street")):
        return "address"
    if "city" in text:
        return "city"
    if any(word in text for word in ("price", "amount", "number", "pin")):
        return "number"
    if text.strip() in {"name", "full name"} or "full name" in text or text.endswith(" name"):
        return "name"
    return "text"


def _valid_value(kind: str, label: str) -> str:
    samples = {
        "password": "Test1234!",
        "email": "user@example.com",
        "username": "testuser",
        "search": "backpack",
        "phone": "5551234567",
        "number": "1",
        "qty": "1",
        "zip": "10001",
        "promo": "SAVE10",
        "card": "4111111111111111",
        "cvv": "123",
        "address": "1 Market Street",
        "city": "New York",
        "name": "Jordan Lee",
    }
    return samples.get(kind, f"Sample {label}".strip())


def _invalid_value(kind: str) -> str:
    return {
        "email": "not-an-email",
        "password": "x",
        "phone": "12ab",
        "number": "abc",
        "qty": "0",
        "zip": "12ab",
        "promo": "NOT-A-CODE",
        "card": "1234",
        "cvv": "1",
        "search": "zzzz-no-such-item",
        "username": " ",
    }.get(kind, "")


def _primary_action(actions: List[Dict[str, str]]) -> str:
    best_label = ""
    best_score = -1
    for index, action in enumerate(actions):
        if action["type"] not in {"button", "icon_button"}:
            continue
        label = action["label"]
        lowered = label.lower()
        score = 1 + index
        for rank, word in enumerate(PRIMARY_WORDS):
            if word in lowered:
                score = 100 - rank
                break
        if score > best_score:
            best_score = score
            best_label = label
    return best_label


def _verify_target(screen: str, labels: List[str]) -> str:
    screen_key = screen.strip().lower()
    for label in labels:
        if label.strip().lower() == screen_key:
            return label
    for label in labels:
        if screen_key and screen_key in label.lower():
            return label
    return labels[0] if labels else ""


def _is_chrome(label: str, screen: str) -> bool:
    key = _slug(label)
    if key not in CHROME_WORDS and not any(word == key or key.startswith(word + "_") for word in CHROME_WORDS):
        return False
    return key not in _slug(screen)


def _field_label(fields: List[Dict[str, str]], needles: tuple[str, ...], fallback: str) -> str:
    for field in fields:
        lowered = field["label"].lower()
        if any(needle in lowered for needle in needles):
            return field["label"]
    return fallback


def _action_label(actions: List[Dict[str, str]], needles: tuple[str, ...], fallback: str) -> str:
    for action in actions:
        lowered = action["label"].lower()
        if any(needle in lowered for needle in needles):
            return action["label"]
    return fallback


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return slug or "item"


def render_manual_cases(step_payload: Dict[str, Any]) -> str:
    """Turn the steps payload into a tester-facing case list. The payload itself is unchanged."""
    screen = str(step_payload.get("screen") or "Screen")
    cases = [case for case in (step_payload.get("cases") or []) if isinstance(case, dict)]
    lines = [
        f"# {screen} — manual test cases",
        "",
        "Written from the same cases the script generator uses. Each case is independent.",
        "",
        "## Preconditions",
        "",
    ]
    for item in _manual_preconditions(screen):
        lines.append(f"- {item}")
    lines.extend(["", "## Index", "", "| ID | Category | Case | Expected result |", "|---|---|---|---|"])
    for index, case in enumerate(cases, start=1):
        lines.append(
            "| {id} | {category} | {name} | {expected} |".format(
                id=f"TC-{index:03d}",
                category=_md_cell(_category_label(case.get("category"))),
                name=_md_cell(_title_from_name(str(case.get("name") or "scenario"))),
                expected=_md_cell(str(case.get("expected") or "")),
            )
        )
    lines.append("")
    for index, case in enumerate(cases, start=1):
        lines.extend(_manual_case_section(index, screen, case))
    return "\n".join(lines).rstrip() + "\n"


def _manual_case_section(index: int, screen: str, case: Dict[str, Any]) -> List[str]:
    name = _title_from_name(str(case.get("name") or "scenario"))
    category = _category_label(case.get("category"))
    expected = str(case.get("expected") or f"{screen} behaves as designed for this case.").strip()
    lines = [
        f"## TC-{index:03d} — {name}",
        "",
        f"- **Screen:** {screen}",
        f"- **Category:** {category}",
        f"- **Expected result:** {expected}",
        "",
        "| Step | Action |",
        "|---|---|",
    ]
    steps = case.get("steps") or []
    if not steps:
        lines.append("| 1 | No steps were produced for this case. |")
    for step_index, step in enumerate(steps, start=1):
        lines.append(f"| {step_index} | {_md_cell(_manual_action(step))} |")
    lines.append("")
    return lines


def _manual_action(step: Dict[str, Any]) -> str:
    element = str(step.get("element") or "the control").strip()
    action = str(step.get("action") or "verify").strip().lower()
    if action == "type":
        value = step.get("input_value")
        text = "" if value is None else str(value)
        if text == "":
            return f"Clear {element} and leave it empty."
        if text.strip() == "":
            return f"Enter only spaces in {element}."
        return f"Enter `{text}` in {element}."
    if action == "tap":
        return f"Tap {element}."
    if action == "scroll":
        return f"Scroll until {element} is visible."
    return f"Confirm {element} is visible."


def _manual_preconditions(screen: str) -> List[str]:
    key = screen.strip().lower()
    if "login" in key or "sign in" in key:
        return [
            "The demo shop app is installed and open.",
            "From the catalog, open the menu and choose Log In so the login screen is showing.",
        ]
    if "cart" in key:
        return [
            "The demo shop app is installed and open.",
            "Open the cart from the shop header.",
        ]
    return [
        "The demo shop app is installed and open.",
        f"The shopper is on the {screen} screen.",
    ]


def _category_label(value: Any) -> str:
    text = str(value or "case").strip().lower()
    return text[:1].upper() + text[1:] if text else "Case"


def _title_from_name(name: str) -> str:
    words = name.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else "Scenario"


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def load_step_prompt(project_root: Path) -> str | None:
    path = project_root / "prompts" / "script_steps.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None
