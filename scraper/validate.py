"""Strict validation for LLM output and published JSON."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from scraper.extract import number_appears_in_text

ALLOWED_STATUS = {"ok", "partial", "uncertain", "failed"}
ALLOWED_APPLIES_TO = {
    "bonus",
    "deposit",
    "deposit_plus_bonus",
    "none",
    "unknown",
    "mixed",
    None,
}
REQUIRED_CASINO_KEYS = {
    "casino_name",
    "welcome_bonus",
    "wagering_requirement",
    "minimum_deposit",
    "source_url",
    "retrieved_at",
    "extraction_status",
}


class ValidationError(ValueError):
    """Raised when payload does not match the publishable schema."""


def parse_json_object(raw: str) -> dict[str, Any]:
    if raw is None:
        raise ValidationError("LLM response is empty.")
    text = raw.strip()
    if not text:
        raise ValidationError("LLM response is empty.")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = _extract_embedded_json(text)

    if not isinstance(payload, dict):
        raise ValidationError("LLM response is not a JSON object.")
    return payload


def _extract_embedded_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValidationError("Malformed LLM response: no JSON object found.")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Malformed LLM response: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Malformed LLM response: JSON root is not an object.")
    return payload


def validate_llm_payload(payload: dict[str, Any], source_texts: dict[str, str]) -> list[dict[str, Any]]:
    if "casinos" not in payload or not isinstance(payload["casinos"], list):
        raise ValidationError("LLM payload missing casinos array.")
    if len(payload["casinos"]) != 3:
        raise ValidationError("LLM payload must contain exactly 3 casino objects.")

    validated = []
    for index, item in enumerate(payload["casinos"]):
        if not isinstance(item, dict):
            raise ValidationError(f"Casino {index} is not an object.")
        validated.append(_validate_casino(item, source_texts))
    return validated


def _validate_casino(item: dict[str, Any], source_texts: dict[str, str]) -> dict[str, Any]:
    name = item.get("casino_name")
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("casino_name must be a non-empty string.")
    name = name.strip()

    status = item.get("extraction_status", "ok")
    if status not in ALLOWED_STATUS:
        raise ValidationError(f"Invalid extraction_status for {name}.")

    welcome = item.get("welcome_bonus")
    if welcome is not None and not isinstance(welcome, str):
        raise ValidationError(f"welcome_bonus for {name} must be a string or null.")
    if isinstance(welcome, str) and not welcome.strip():
        welcome = None

    wagering = _validate_wagering(item.get("wagering_requirement"), name)
    deposit = _validate_deposit(item.get("minimum_deposit"), name)

    source_url = item.get("source_url")
    if not _is_http_url(source_url):
        raise ValidationError(f"source_url for {name} must be an http(s) URL.")

    source_text = source_texts.get(name) or source_texts.get(name.casefold()) or ""
    # Also try fuzzy lookup by substring.
    if not source_text:
        for key, value in source_texts.items():
            if name.casefold() in key.casefold() or key.casefold() in name.casefold():
                source_text = value
                break

    notes: list[str] = []
    if welcome and source_text:
        # Dollar figures in the welcome headline must appear in the source.
        invented = _unsupported_amounts(welcome, source_text)
        if invented:
            notes.append("Welcome bonus amounts were not present in the source text.")
            welcome = None
            status = "uncertain"

    multiplier = wagering.get("multiplier")
    if multiplier is not None and source_text and not number_appears_in_text(multiplier, source_text):
        notes.append("Wagering multiplier was not present in the source text.")
        wagering["multiplier"] = None
        wagering["status"] = "uncertain"
        status = "uncertain"

    amount = deposit.get("amount")
    if amount not in (None, 0.0) and source_text and not number_appears_in_text(amount, source_text):
        notes.append("Minimum deposit was not present in the source text.")
        deposit["amount"] = None
        deposit["status"] = "uncertain"
        status = "uncertain"

    if wagering.get("applies_to") not in ALLOWED_APPLIES_TO:
        raise ValidationError(f"Invalid wagering applies_to for {name}.")

    if status == "ok":
        missing_core = welcome is None or multiplier is None or deposit.get("amount") is None
        if missing_core:
            status = "partial"

    result = {
        "casino_name": name,
        "welcome_bonus": welcome,
        "wagering_requirement": {
            "multiplier": wagering.get("multiplier"),
            "applies_to": wagering.get("applies_to"),
            "notes": wagering.get("notes"),
        },
        "minimum_deposit": {
            "amount": deposit.get("amount"),
            "currency": deposit.get("currency"),
            "notes": deposit.get("notes"),
        },
        "source_url": source_url,
        "extraction_status": status,
        "validation_notes": notes or None,
    }
    return result


def _validate_wagering(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {"multiplier": None, "applies_to": None, "notes": None, "status": "missing"}
    if isinstance(value, (int, float)):
        return {"multiplier": float(value), "applies_to": "unknown", "notes": None, "status": "ok"}
    if not isinstance(value, dict):
        raise ValidationError(f"wagering_requirement for {name} must be an object, number, or null.")
    multiplier = value.get("multiplier")
    if multiplier is not None:
        if not isinstance(multiplier, (int, float)) or isinstance(multiplier, bool):
            raise ValidationError(f"wagering multiplier for {name} must be a number or null.")
        if multiplier < 0:
            raise ValidationError(f"wagering multiplier for {name} cannot be negative.")
        multiplier = float(multiplier)
    applies_to = value.get("applies_to")
    if applies_to is not None and applies_to not in ALLOWED_APPLIES_TO:
        raise ValidationError(f"Invalid applies_to for {name}.")
    notes = value.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ValidationError(f"wagering notes for {name} must be a string or null.")
    return {
        "multiplier": multiplier,
        "applies_to": applies_to,
        "notes": notes,
        "status": value.get("status") or ("ok" if multiplier is not None else "missing"),
    }


def _validate_deposit(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {"amount": None, "currency": None, "notes": None, "status": "missing"}
    if isinstance(value, (int, float)):
        return {"amount": float(value), "currency": None, "notes": None, "status": "ok"}
    if not isinstance(value, dict):
        raise ValidationError(f"minimum_deposit for {name} must be an object, number, or null.")
    amount = value.get("amount")
    if amount is not None:
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise ValidationError(f"minimum deposit for {name} must be a number or null.")
        if amount < 0:
            raise ValidationError(f"minimum deposit for {name} cannot be negative.")
        amount = float(amount)
    currency = value.get("currency")
    if currency is not None:
        if not isinstance(currency, str) or not (2 <= len(currency) <= 4):
            raise ValidationError(f"currency for {name} is invalid.")
        currency = currency.upper()
    notes = value.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ValidationError(f"deposit notes for {name} must be a string or null.")
    return {
        "amount": amount,
        "currency": currency,
        "notes": notes,
        "status": value.get("status") or ("ok" if amount is not None else "missing"),
    }


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _unsupported_amounts(welcome: str, source_text: str) -> list[str]:
    found = []
    for match in __import__("re").finditer(r"\d+(?:,\d{3})*(?:\.\d+)?", welcome):
        number = match.group(0).replace(",", "")
        try:
            value = float(number)
        except ValueError:
            continue
        if not number_appears_in_text(value, source_text):
            found.append(number)
    return found


def is_publishable(document: dict[str, Any]) -> tuple[bool, str]:
    """A document is publishable only when 3 casinos were extracted from a real source."""
    if not isinstance(document, dict):
        return False, "Document is not an object."
    casinos = document.get("casinos")
    if not isinstance(casinos, list) or len(casinos) != 3:
        return False, "Document must contain exactly 3 casino records."
    if document.get("source", {}).get("blocked"):
        return False, "Source access was blocked."
    if document.get("status") in {"failed", "empty"}:
        return False, "Document status is not publishable."

    verified_like = 0
    for casino in casinos:
        if not isinstance(casino, dict):
            return False, "Casino record is not an object."
        missing = REQUIRED_CASINO_KEYS - set(casino)
        if missing:
            return False, f"Casino record missing keys: {sorted(missing)}"
        if not casino.get("casino_name"):
            return False, "Casino name missing."
        if not _is_http_url(casino.get("source_url")):
            return False, "Casino source URL is invalid."
        if casino.get("extraction_status") == "failed":
            continue
        if casino.get("welcome_bonus") or casino.get("wagering_requirement") or casino.get("minimum_deposit"):
            verified_like += 1

    if verified_like < 3:
        return False, "Fewer than 3 usable casino records."
    if document.get("fabricated"):
        return False, "Document is marked fabricated."
    return True, "ok"


def load_existing_json(path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Existing JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Existing JSON root is not an object.")
    return payload
