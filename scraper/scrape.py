"""Fetch one public comparison page and extract three casino bonuses via Claude."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from dotenv import load_dotenv

from scraper.extract import REQUIRED_OFFERS, SOURCE_URL, OfferSnippet, extract_casino_offers
from scraper.validate import ValidationError, is_publishable, load_existing_json, parse_json_object, validate_llm_payload

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "public" / "data" / "casinos.json"
USER_AGENT = (
    "CasinoBonusScraper/1.0 (+educational screening task; Python requests) "
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 25
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1, 2, 4)
PREFERRED_MODEL_TOKENS = ("haiku", "sonnet", "claude")

LOGGER = logging.getLogger("casino_bonus_scraper")

EXTRACTION_PROMPT = """You extract casino welcome-bonus terms from source text.

Return a single JSON object with this exact shape:
{
  "casinos": [
    {
      "casino_name": "string",
      "welcome_bonus": "string or null",
      "wagering_requirement": {
        "multiplier": number or null,
        "applies_to": "bonus" | "deposit" | "deposit_plus_bonus" | "none" | "unknown" | "mixed" | null,
        "notes": "string or null"
      },
      "minimum_deposit": {
        "amount": number or null,
        "currency": "USD" | "EUR" | "GBP" | "ZAR" | "CAD" | "AUD" | null,
        "notes": "string or null"
      },
      "source_url": "https://...",
      "extraction_status": "ok" | "partial" | "uncertain"
    }
  ]
}

Rules:
- Use only facts present in the provided source text. Never invent amounts, multipliers, or deposits.
- If a value is missing or ambiguous, set it to null and use extraction_status "uncertain" or "partial".
- Preserve whether wagering applies to the bonus, the deposit, or deposit + bonus. If unclear, use "unknown" or "mixed".
- Source shorthand: "10xb" means 10x on the bonus amount, "5xd" means 5x on the deposit, and "7x(d+b)" means 7x on deposit plus bonus.
- welcome_bonus should be a short factual summary of the welcome offer, not marketing fluff.
- Keep casino_name and source_url from the input.
- Output JSON only. No markdown.
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def load_api_key() -> str | None:
    load_dotenv(ROOT / ".env")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key or None


def robots_url_for(page_url: str) -> str:
    parsed = urlparse(page_url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def check_robots(page_url: str, session: requests.Session) -> tuple[bool, str]:
    robots_url = robots_url_for(page_url)
    LOGGER.info("Checking robots.txt at %s", robots_url)
    try:
        response = _request_with_retries(session, robots_url)
    except requests.RequestException as exc:
        LOGGER.warning("Could not read robots.txt (%s); refusing to scrape.", exc)
        return False, f"robots.txt unavailable: {exc}"

    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    allowed = parser.can_fetch(USER_AGENT, page_url)
    delay = parser.crawl_delay(USER_AGENT)
    if delay:
        LOGGER.info("Respecting crawl-delay of %s seconds", delay)
        time.sleep(float(delay))
    if not allowed:
        return False, f"robots.txt disallows {page_url}"
    LOGGER.info("robots.txt allows fetching %s", page_url)
    return True, "allowed"


def _request_with_retries(session: requests.Session, url: str) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
                LOGGER.warning(
                    "Transient HTTP %s for %s (attempt %s/%s); retrying in %ss",
                    response.status_code,
                    url,
                    attempt,
                    MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt >= MAX_RETRIES:
                break
            wait = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
            LOGGER.warning(
                "Request error for %s (attempt %s/%s): %s; retrying in %ss",
                url,
                attempt,
                MAX_RETRIES,
                exc,
                wait,
            )
            time.sleep(wait)
        except requests.HTTPError as exc:
            raise exc
    assert last_error is not None
    raise last_error


def _looks_like_challenge(html: str) -> bool:
    lowered = html[:4000].lower()
    return "cf-mitigated" in lowered or "just a moment" in lowered or "challenge-platform" in lowered


def _fetch_with_urllib(url: str) -> tuple[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
    }
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                html = response.read().decode(charset, errors="replace")
                return html, response.geturl()
        except urllib.error.HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
                LOGGER.warning("Transient HTTP %s via urllib; retrying in %ss", exc.code, wait)
                time.sleep(wait)
                last_error = exc
                continue
            http_error = requests.HTTPError(str(exc))
            http_error.response = type("Resp", (), {"status_code": exc.code})()
            raise http_error from exc
        except urllib.error.URLError as exc:
            last_error = requests.Timeout(str(exc)) if "timed out" in str(exc).lower() else requests.ConnectionError(str(exc))
            if attempt >= MAX_RETRIES:
                break
            wait = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
            LOGGER.warning("urllib error (attempt %s/%s): %s; retrying in %ss", attempt, MAX_RETRIES, exc, wait)
            time.sleep(wait)
    assert last_error is not None
    raise last_error


def fetch_page(session: requests.Session, url: str) -> tuple[str, str]:
    """Fetch HTML with requests, then urllib if Cloudflare challenges the TLS fingerprint."""
    try:
        response = _request_with_retries(session, url)
        html = response.text
        final_url = str(response.url or url)
        if _looks_like_challenge(html):
            LOGGER.warning("requests returned a challenge page; retrying with urllib")
            return _fetch_with_urllib(url)
        return html, final_url
    except requests.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 403:
            LOGGER.warning("requests received HTTP 403; retrying with urllib (no CAPTCHA solve)")
            return _fetch_with_urllib(url)
        raise


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        }
    )
    return session


def choose_model(api_key: str) -> str:
    override = os.environ.get("ANTHROPIC_MODEL", "").strip()
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        ids: list[str] = []
        page = client.models.list()
        for model in getattr(page, "data", []) or []:
            model_id = getattr(model, "id", None)
            if model_id:
                ids.append(model_id)
        LOGGER.info("Anthropic models available to this account: %s", ", ".join(ids) or "(none listed)")
        if override:
            if override in ids or not ids:
                LOGGER.info("Using ANTHROPIC_MODEL override: %s", override)
                return override
            LOGGER.warning("ANTHROPIC_MODEL=%s is not in the account model list; selecting another.", override)
        for token in PREFERRED_MODEL_TOKENS:
            for model_id in ids:
                lowered = model_id.lower()
                if token in lowered and "opus" not in lowered:
                    LOGGER.info("Selected Anthropic model %s", model_id)
                    return model_id
        if ids:
            LOGGER.info("Falling back to first listed model %s", ids[0])
            return ids[0]
    except Exception as exc:  # noqa: BLE001 - model discovery should not crash the run
        LOGGER.warning("Model listing failed (%s); using fallback identifier.", exc)
        if override:
            return override
    fallback = override or "claude-haiku-4-5"
    LOGGER.info("Using fallback model identifier %s", fallback)
    return fallback


def call_claude(api_key: str, model: str, offers: list[OfferSnippet]) -> str:
    from anthropic import Anthropic

    payload = []
    for offer in offers:
        payload.append(
            {
                "casino_name": offer.casino_name,
                "source_url": offer.source_url,
                "bonus_text": offer.bonus_text,
                "terms_text": offer.terms_text,
                "combined_text": offer.combined_text(),
            }
        )
    user_content = "Extract structured fields for these three offers:\n" + json.dumps(payload, indent=2)
    client = Anthropic(api_key=api_key)
    LOGGER.info("Sending one Claude request for %s offers using model %s", len(offers), model)
    message = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT + "\n\n" + user_content}],
    )
    parts = []
    for block in message.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    if not parts:
        raise ValidationError("Claude returned no text content.")
    return "\n".join(parts)


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    serialized = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    tmp_path.write_text(serialized, encoding="utf-8")
    tmp_path.replace(path)


def preserve_existing(reason: str, existing: dict[str, Any] | None) -> int:
    if existing and is_publishable(existing)[0]:
        LOGGER.error("%s Existing publishable data was left unchanged.", reason)
        return 3
    LOGGER.error("%s No publishable existing data to keep.", reason)
    return 3


def build_document(
    offers: list[OfferSnippet],
    casinos: list[dict[str, Any]],
    model: str,
    page_url: str,
) -> dict[str, Any]:
    retrieved = utc_now()
    records = []
    for offer, casino in zip(offers, casinos):
        record = dict(casino)
        record["source_url"] = record.get("source_url") or offer.source_url
        record["retrieved_at"] = retrieved
        record["raw_source_text"] = offer.combined_text()
        records.append(record)
    return {
        "source": {
            "url": page_url,
            "name": urlparse(page_url).netloc,
            "retrieved_at": retrieved,
            "robots_checked": True,
            "blocked": False,
        },
        "model": model,
        "status": "ok",
        "casinos": records,
    }


def run() -> int:
    configure_logging()
    existing = None
    try:
        existing = load_existing_json(OUTPUT_PATH)
    except ValidationError as exc:
        LOGGER.warning("Existing output is invalid and will not be reused: %s", exc)
        existing = None

    page_url = os.environ.get("SCRAPE_SOURCE_URL", SOURCE_URL).strip() or SOURCE_URL
    session = build_session()

    allowed, robots_reason = check_robots(page_url, session)
    if not allowed:
        LOGGER.error("Refusing to scrape: %s", robots_reason)
        return preserve_existing("Source is disallowed.", existing)

    LOGGER.info("Fetching %s", page_url)
    try:
        html, final_url = fetch_page(session, page_url)
    except requests.Timeout:
        LOGGER.error("Timed out fetching %s", page_url)
        return preserve_existing("HTTP timeout.", existing)
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        LOGGER.error("HTTP error fetching %s: %s", page_url, status or exc)
        return preserve_existing("HTTP error.", existing)
    except requests.RequestException as exc:
        LOGGER.error("Request failed for %s: %s", page_url, exc)
        return preserve_existing("Request failed.", existing)

    offers = extract_casino_offers(html, page_url=final_url or page_url)
    LOGGER.info("Extracted %s casino offer snippets", len(offers))
    if len(offers) < REQUIRED_OFFERS:
        LOGGER.error("Page did not yield %s extractable offers.", REQUIRED_OFFERS)
        return preserve_existing("Insufficient offers on source page.", existing)

    offers = offers[:REQUIRED_OFFERS]
    for offer in offers:
        LOGGER.info("Offer: %s", offer.casino_name)

    api_key = load_api_key()
    if not api_key:
        LOGGER.error("ANTHROPIC_API_KEY is not set. Refusing to fabricate structured fields.")
        return preserve_existing("Missing API key.", existing)

    model = choose_model(api_key)
    try:
        raw_llm = call_claude(api_key, model, offers)
        parsed = parse_json_object(raw_llm)
        source_texts = {offer.casino_name: offer.combined_text() for offer in offers}
        casinos = validate_llm_payload(parsed, source_texts)
    except ValidationError as exc:
        LOGGER.error("LLM validation failed: %s", exc)
        return preserve_existing("Invalid LLM output.", existing)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Claude API call failed: %s", exc)
        return preserve_existing("Claude API failure.", existing)

    document = build_document(offers, casinos, model, final_url or page_url)
    publishable, reason = is_publishable(document)
    if not publishable:
        LOGGER.error("Refusing to publish incomplete data: %s", reason)
        return preserve_existing("Output failed publish checks.", existing)

    atomic_write_json(OUTPUT_PATH, document)
    LOGGER.info("Wrote %s", OUTPUT_PATH)
    return 0


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        LOGGER.error("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
