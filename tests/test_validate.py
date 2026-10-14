import json

import pytest

from scraper.validate import (
    ValidationError,
    is_publishable,
    parse_json_object,
    validate_llm_payload,
)


def _casino(**overrides):
    base = {
        "casino_name": "FanDuel Casino",
        "welcome_bonus": "Deposit $5, get 1,000 bonus spins and $25 casino bonus",
        "wagering_requirement": {"multiplier": 1, "applies_to": "bonus", "notes": None},
        "minimum_deposit": {"amount": 5, "currency": "USD", "notes": None},
        "source_url": "https://www.playmichigan.com/online-casino/fanduel/",
        "extraction_status": "ok",
    }
    base.update(overrides)
    return base


def test_malformed_llm_response_is_rejected():
    with pytest.raises(ValidationError, match="empty"):
        parse_json_object("")
    with pytest.raises(ValidationError, match="Malformed"):
        parse_json_object("not json at all")
    with pytest.raises(ValidationError, match="not a JSON object"):
        parse_json_object("[1, 2, 3]")


def test_embedded_json_is_accepted():
    payload = parse_json_object('Here you go:\n{"casinos": []}\nThanks')
    assert payload == {"casinos": []}


def test_llm_payload_must_have_three_casinos():
    with pytest.raises(ValidationError, match="exactly 3"):
        validate_llm_payload({"casinos": [_casino()]}, {})


def test_invented_multiplier_is_nulled():
    source = {
        "FanDuel Casino": "FanDuel Casino\nDeposit $5, get 1,000 bonus spins and $25 casino bonus\n1x"
    }
    payload = {
        "casinos": [
            _casino(wagering_requirement={"multiplier": 40, "applies_to": "bonus"}),
            _casino(
                casino_name="BetMGM Casino",
                welcome_bonus="Deposit $10 for spins",
                wagering_requirement={"multiplier": 15, "applies_to": "bonus"},
                minimum_deposit={"amount": 10, "currency": "USD"},
                source_url="https://www.playmichigan.com/online-casino/betmgm/",
            ),
            _casino(
                casino_name="DraftKings Casino",
                welcome_bonus="1,000 Flex Spins after $5 wager",
                wagering_requirement={"multiplier": 1, "applies_to": "unknown"},
                minimum_deposit={"amount": 5, "currency": "USD"},
                source_url="https://www.playmichigan.com/online-casino/draftkings/",
            ),
        ]
    }
    source_texts = {
        **source,
        "BetMGM Casino": "BetMGM Casino\nDeposit $10 for spins\n15x for deposit bonus",
        "DraftKings Casino": "DraftKings Casino\n1,000 Flex Spins after $5 wager\n1x",
    }
    casinos = validate_llm_payload(payload, source_texts)
    fanduel = casinos[0]
    assert fanduel["wagering_requirement"]["multiplier"] is None
    assert fanduel["extraction_status"] == "uncertain"


def test_invalid_json_output_is_not_publishable():
    ok, reason = is_publishable({"casinos": []})
    assert ok is False
    assert "exactly 3" in reason

    incomplete = {
        "status": "ok",
        "casinos": [
            {
                "casino_name": "A",
                "welcome_bonus": None,
                "wagering_requirement": None,
                "minimum_deposit": None,
                "source_url": "https://example.com",
                "retrieved_at": "2026-01-01T00:00:00+00:00",
                "extraction_status": "failed",
            }
        ]
        * 3,
    }
    ok, reason = is_publishable(incomplete)
    assert ok is False


def test_fabricated_flag_blocks_publish():
    casinos = [
        {
            **_casino(casino_name=name),
            "retrieved_at": "2026-01-01T00:00:00+00:00",
        }
        for name in ("A Casino", "B Casino", "C Casino")
    ]
    for casino, url in zip(
        casinos,
        (
            "https://www.playmichigan.com/online-casino/a/",
            "https://www.playmichigan.com/online-casino/b/",
            "https://www.playmichigan.com/online-casino/c/",
        ),
    ):
        casino["source_url"] = url
        casino["casino_name"] = casino["casino_name"] if casino is casinos[0] else casino["casino_name"]
    casinos[0]["casino_name"] = "A Casino"
    casinos[1]["casino_name"] = "B Casino"
    casinos[2]["casino_name"] = "C Casino"
    document = {"status": "ok", "casinos": casinos, "fabricated": True}
    ok, reason = is_publishable(document)
    assert ok is False
    assert "fabricated" in reason


def test_valid_document_is_publishable():
    casinos = []
    for name, path in (
        ("Hard Rock Bet Casino", "hard-rock"),
        ("BetMGM Casino", "betmgm"),
        ("DraftKings Casino", "draftkings"),
    ):
        row = _casino(casino_name=name)
        row["source_url"] = f"https://www.playmichigan.com/online-casino/{path}/"
        row["retrieved_at"] = "2026-10-14T00:00:00+00:00"
        casinos.append(row)
    ok, reason = is_publishable({"status": "ok", "casinos": casinos})
    assert ok is True, reason


def test_round_trip_json_must_be_object():
    with pytest.raises(json.JSONDecodeError):
        json.loads("{")
