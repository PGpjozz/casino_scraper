"""HTML extraction and deterministic parsers for bonus terms."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

SOURCE_URL = "https://www.askgamblers.com/casino-bonuses/welcome"
REQUIRED_OFFERS = 3

_CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "R": "ZAR",
    "C$": "CAD",
    "A$": "AUD",
}

# Matches 35x, 10xb (bonus), 5xd (deposit), and 7x(d+b).
_WAGER_TOKEN_RE = re.compile(
    r"(?<!\d)(?P<mult>\d+(?:\.\d+)?)\s*x(?:\s*\(\s*(?P<paren>[^)]{1,16})\s*\)|(?P<suffix>[bd])\b)?",
    re.IGNORECASE,
)

_DEPOSIT_RE = re.compile(
    r"(?:min(?:imum)?\s+deposit|deposit(?:\s+of)?|deposits?)\s*"
    r"(?:at\s+least\s+|of\s+)?"
    r"(C\$|A\$|R|\$|€|£)\s*(\d+(?:,\d{3})*(?:\.\d+)?)"
    r"|"
    r"(?:min(?:imum)?\s+deposit)[^\d]{0,12}"
    r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(USD|EUR|GBP|ZAR|CAD|AUD)",
    re.IGNORECASE,
)

_AMOUNT_CCY_RE = re.compile(
    r"(C\$|A\$|R|\$|€|£)\s*(\d+(?:,\d{3})*(?:\.\d+)?)"
    r"|"
    r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(USD|EUR|GBP|ZAR|CAD|AUD)"
)

_PROMO_HINTS = (
    "bonus",
    "spins",
    "deposit match",
    "welcome",
    "sign-up",
    "signup",
    "lossback",
    "free play",
)

_SKIP_HINTS = (
    "reason to avoid",
    "type of bonus",
    "example",
    "loyalty program",
)


@dataclass
class OfferSnippet:
    casino_name: str
    bonus_text: str
    terms_text: str
    source_url: str
    extra_text: str = ""
    raw_cells: list[str] = field(default_factory=list)

    def combined_text(self) -> str:
        parts = [self.casino_name, self.bonus_text, self.terms_text, self.extra_text]
        return "\n".join(p for p in parts if p).strip()


def parse_wagering_multiplier(text: str) -> dict[str, Any]:
    """Parse a wagering multiplier and which amount it applies to.

    Returns multiplier as float or None. Does not invent values.
    """
    if not text or not str(text).strip():
        return {
            "multiplier": None,
            "applies_to": None,
            "notes": "No wagering text provided.",
            "status": "missing",
        }

    lowered = text.lower()
    if re.search(r"\b(no wagering|wager[- ]free|0x|none)\b", lowered):
        if re.search(r"\bnone\b", lowered) and not re.search(r"\b0x\b", lowered):
            if "wager" not in lowered and "playthrough" not in lowered:
                # A cell that is just "None" is treated as no requirement stated.
                return {
                    "multiplier": None,
                    "applies_to": None,
                    "notes": "Source states None / no playthrough listed.",
                    "status": "missing",
                }
        return {
            "multiplier": 0.0,
            "applies_to": "none",
            "notes": "Source indicates no wagering requirement.",
            "status": "ok",
        }

    matches = []
    token_bases: list[str] = []
    for match in _WAGER_TOKEN_RE.finditer(text):
        try:
            matches.append(float(match.group("mult")))
        except ValueError:
            continue
        token_bases.append(_base_from_wager_token(match.group("paren"), match.group("suffix")))

    if not matches:
        return {
            "multiplier": None,
            "applies_to": None,
            "notes": "No unambiguous Nx multiplier found.",
            "status": "ambiguous",
        }

    unique = []
    for value in matches:
        if value not in unique:
            unique.append(value)

    applies_to = _single_token_base(token_bases) or _infer_wagering_base(lowered)
    if len(unique) == 1:
        return {
            "multiplier": unique[0],
            "applies_to": applies_to,
            "notes": None,
            "status": "ok",
        }

    return {
        "multiplier": None,
        "applies_to": applies_to,
        "notes": "Multiple multipliers found: " + ", ".join(f"{v:g}x" for v in unique),
        "status": "ambiguous",
        "candidates": unique,
    }


def _base_from_wager_token(paren: str | None, suffix: str | None) -> str | None:
    if paren:
        compact = re.sub(r"\s+", "", paren.lower())
        if "d+b" in compact or "deposit+bonus" in compact:
            return "deposit_plus_bonus"
        if compact in {"b", "bonus"}:
            return "bonus"
        if compact in {"d", "deposit"}:
            return "deposit"
        return "unknown"
    if suffix:
        return "bonus" if suffix.lower() == "b" else "deposit"
    return None


def _single_token_base(bases: list[str | None]) -> str | None:
    present = [base for base in bases if base]
    unique = []
    for base in present:
        if base not in unique:
            unique.append(base)
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        return "mixed"
    return None


def _infer_wagering_base(lowered: str) -> str:
    bonus_only = bool(
        re.search(r"\b(bonus only|on the bonus|bonus amount|bonus money|casino bonus)\b", lowered)
    )
    deposit_only = bool(re.search(r"\b(on the deposit|deposit amount|deposit only)\b", lowered))
    combined = bool(
        re.search(
            r"\b(deposit\s*\+\s*bonus|deposit plus bonus|d\s*\+\s*b|combined)\b",
            lowered,
        )
    )
    if combined and not (bonus_only or deposit_only):
        return "deposit_plus_bonus"
    if bonus_only and not deposit_only and not combined:
        return "bonus"
    if deposit_only and not bonus_only and not combined:
        return "deposit"
    if bonus_only or deposit_only or combined:
        return "mixed"
    return "unknown"


def parse_minimum_deposit(text: str) -> dict[str, Any]:
    """Parse a minimum deposit amount and currency. Does not invent values."""
    if not text or not str(text).strip():
        return {
            "amount": None,
            "currency": None,
            "status": "missing",
            "notes": "No deposit text provided.",
        }

    lowered = text.lower()
    if re.search(r"\b(no minimum|min(?:imum)? deposit\s*(is|:)?\s*none|n/?a)\b", lowered):
        return {
            "amount": 0.0,
            "currency": None,
            "status": "ok",
            "notes": "Source indicates no minimum deposit.",
        }

    # Prefer phrases that mention deposit.
    deposit_matches = list(_DEPOSIT_RE.finditer(text))
    parsed = []
    for match in deposit_matches:
        symbol, amount_a, amount_b, code = match.group(1), match.group(2), match.group(3), match.group(4)
        if symbol and amount_a:
            parsed.append((_to_float(amount_a), _CURRENCY_SYMBOLS.get(symbol)))
        elif amount_b and code:
            parsed.append((_to_float(amount_b), code.upper()))

    if not parsed:
        # Fallback: "Deposit $10" style already covered; try "Play $5" / "Wager $10" only
        # when the text is clearly an activation threshold.
        activation = re.search(
            r"(?i)(?:deposit|play|wager)\s+(?:at least\s+)?(C\$|A\$|R|\$|€|£)\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
            text,
        )
        if activation:
            parsed.append((_to_float(activation.group(2)), _CURRENCY_SYMBOLS.get(activation.group(1))))

    if not parsed:
        return {
            "amount": None,
            "currency": None,
            "status": "ambiguous",
            "notes": "No unambiguous minimum deposit found.",
        }

    amounts = {item[0] for item in parsed if item[0] is not None}
    currencies = {item[1] for item in parsed if item[1]}
    if len(amounts) == 1:
        amount = next(iter(amounts))
        currency = next(iter(currencies)) if len(currencies) == 1 else (
            next(iter(currencies)) if currencies else None
        )
        if len(currencies) > 1:
            return {
                "amount": amount,
                "currency": None,
                "status": "ambiguous",
                "notes": "Amount found but currency is ambiguous.",
            }
        return {"amount": amount, "currency": currency, "status": "ok", "notes": None}

    return {
        "amount": None,
        "currency": next(iter(currencies)) if len(currencies) == 1 else None,
        "status": "ambiguous",
        "notes": "Multiple deposit amounts found.",
        "candidates": sorted(amounts),
    }


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except (TypeError, ValueError):
        return None


def extract_casino_offers(html: str, page_url: str = SOURCE_URL) -> list[OfferSnippet]:
    """Extract casino names and bonus text from a comparison page."""
    if not html or not html.strip():
        return []

    soup = BeautifulSoup(html, "html.parser")
    card_offers = _extract_detail_cards(soup, page_url)
    if len(card_offers) >= REQUIRED_OFFERS:
        return card_offers[:REQUIRED_OFFERS]

    offers: list[OfferSnippet] = []
    seen: set[str] = set()

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        header_blob = " ".join(header_cells)
        if not _is_bonus_table(header_blob, rows):
            continue

        name_idx, bonus_idx, terms_idx, link_idx = _column_indexes(header_cells)

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            blob = " ".join(texts).lower()
            if any(hint in blob for hint in _SKIP_HINTS):
                continue
            if not any(hint in blob for hint in _PROMO_HINTS):
                continue

            name = _clean_casino_name(_cell(texts, name_idx) or texts[0])
            bonus = _cell(texts, bonus_idx) or (texts[1] if len(texts) > 1 else "")
            terms = _cell(texts, terms_idx)
            if not name or not bonus:
                continue
            if _looks_like_loyalty_only(bonus, terms):
                continue

            source = _row_source_url(cells, page_url, link_idx) or page_url
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            offers.append(
                OfferSnippet(
                    casino_name=name,
                    bonus_text=bonus,
                    terms_text=terms,
                    source_url=source,
                    raw_cells=texts,
                )
            )
            if len(offers) >= REQUIRED_OFFERS:
                return offers

    return offers


def _extract_detail_cards(soup: BeautifulSoup, page_url: str) -> list[OfferSnippet]:
    """Parse AskGamblers-style welcome cards. Skips /visit/ affiliate links."""
    offers: list[OfferSnippet] = []
    seen: set[str] = set()
    for card in soup.select("div.details-card"):
        name_el = card.select_one(".details-card-name")
        title_el = card.select_one("a.details-card-title")
        if name_el is None or title_el is None:
            continue
        labels: dict[str, str] = {}
        for item in card.select(".details-card-details__item"):
            label_el = item.select_one(".details-card-details__label")
            value_el = item.select_one(".details-card-details__value")
            if label_el is None or value_el is None:
                continue
            labels[label_el.get_text(" ", strip=True).lower()] = value_el.get_text(" ", strip=True)
        category = labels.get("category", "")
        if category and "welcome" not in category.lower():
            continue
        name = _clean_casino_name(name_el.get_text(" ", strip=True))
        bonus = title_el.get_text(" ", strip=True)
        if not name or not bonus or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        terms_parts = []
        if labels.get("minimum deposit"):
            terms_parts.append(f"Minimum Deposit {labels['minimum deposit']}")
        if labels.get("wagering requirements"):
            terms_parts.append(f"Wagering Requirements {labels['wagering requirements']}")
        href = (title_el.get("href") or "").strip()
        source = urljoin(page_url, href) if href else page_url
        if "/visit/" in source.lower():
            source = page_url
        offers.append(
            OfferSnippet(
                casino_name=name,
                bonus_text=bonus,
                terms_text=". ".join(terms_parts),
                source_url=source,
            )
        )
        if len(offers) >= REQUIRED_OFFERS:
            break
    return offers


def _is_bonus_table(header_blob: str, rows: list) -> bool:
    if "playthrough" in header_blob or "wager" in header_blob:
        return True
    if "welcome offer" in header_blob or "deposit bonus" in header_blob:
        return True
    if "bonus offer" in header_blob and "casino" in header_blob:
        return True
    # Some ninja tables put headers in the first data row styling only.
    sample = " ".join(c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["td", "th"]))
    return "welcome" in sample and "casino" in sample


def _column_indexes(headers: list[str]) -> tuple[int, int, int, int]:
    name_idx = bonus_idx = terms_idx = link_idx = -1
    for i, header in enumerate(headers):
        if name_idx < 0 and ("casino" in header or header in {"brand", "operator"}):
            name_idx = i
        if bonus_idx < 0 and any(word in header for word in ("welcome", "bonus", "offer")):
            bonus_idx = i
        if terms_idx < 0 and any(word in header for word in ("playthrough", "wager", "requirement")):
            terms_idx = i
        if link_idx < 0 and any(word in header for word in ("review", "link", "source")):
            link_idx = i
    if name_idx < 0:
        name_idx = 0
    if bonus_idx < 0:
        bonus_idx = 1 if len(headers) > 1 else 0
    return name_idx, bonus_idx, terms_idx, link_idx


def _cell(texts: list[str], index: int) -> str:
    if index < 0 or index >= len(texts):
        return ""
    return texts[index].strip()


def _clean_casino_name(raw: str) -> str:
    name = re.sub(r"(?i)promo code:.*", "", raw).strip()
    name = re.sub(r"(?i)\s+review$", "", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:120]


def _looks_like_loyalty_only(bonus: str, terms: str) -> bool:
    blob = f"{bonus} {terms}".lower()
    if terms.strip().lower() == "none" and any(
        word in blob for word in ("reward drops", "every wager earns", "tier credits")
    ):
        return True
    return False


def _row_source_url(cells, page_url: str, link_idx: int) -> str | None:
    candidates = []
    scan = cells if link_idx < 0 else [cells[link_idx]] + list(cells)
    for cell in scan:
        for anchor in cell.find_all("a", href=True):
            href = anchor["href"].strip()
            if href.startswith("#"):
                continue
            absolute = urljoin(page_url, href)
            lowered = absolute.lower()
            if any(part in lowered for part in ("/claim/", "/visit/", "/recommends/", "/search/")):
                continue
            if lowered.startswith("http"):
                candidates.append(absolute)
    if candidates:
        # Prefer a review/casino page over outbound affiliate domains.
        for url in candidates:
            if "playmichigan.com/online-casino/" in url and not url.rstrip("/").endswith("bonus"):
                return url
        return candidates[0]
    return None


def number_appears_in_text(value: float | int | None, text: str) -> bool:
    """True when a numeric extraction is supported by the source text."""
    if value is None:
        return True
    if not text:
        return False
    if float(value).is_integer():
        as_int = str(int(value))
        return bool(re.search(rf"(?<!\d){re.escape(as_int)}(?:\.0+)?(?:\s*x)?(?!\d)", text))
    rendered = f"{value:g}"
    return rendered in text.replace(",", "")
