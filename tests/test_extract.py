from scraper.extract import extract_casino_offers, parse_minimum_deposit, parse_wagering_multiplier


def test_extracts_three_casino_names_and_bonus_text(sample_html):
    offers = extract_casino_offers(
        sample_html,
        page_url="https://www.playmichigan.com/online-casino/bonus/",
    )
    assert len(offers) == 3
    names = [offer.casino_name for offer in offers]
    assert names == ["Hard Rock Bet Casino", "BetMGM Casino", "DraftKings Casino"]
    assert "500 Bonus Spins" in offers[0].bonus_text
    assert "1,000 Bonus Spins" in offers[1].bonus_text
    assert "Flex Spins" in offers[2].bonus_text
    assert "playthrough" in offers[1].terms_text.lower() or "15x" in offers[1].terms_text
    assert all(offer.source_url.startswith("https://www.playmichigan.com/") for offer in offers)
    assert "/claim/" not in "".join(offer.source_url for offer in offers)


def test_extracts_nothing_from_empty_html():
    assert extract_casino_offers("") == []
    assert extract_casino_offers("<html><body>No tables here</body></html>") == []


ASKGAMBLERS_HTML = """
<html><body>
<div class="details-card">
  <span class="details-card-name">Jackpot City Casino</span>
  <a class="details-card-title" href="/casino-bonuses/latest/jackpot-city">100% up to 4000 ZAR</a>
  <div class="details-card-details__item">
    <span class="details-card-details__label">Category</span>
    <span class="details-card-details__value">Welcome Bonus</span>
  </div>
  <div class="details-card-details__item">
    <span class="details-card-details__label">Minimum Deposit</span>
    <span class="details-card-details__value">50 ZAR</span>
  </div>
  <div class="details-card-details__item">
    <span class="details-card-details__label">Wagering Requirements</span>
    <span class="details-card-details__value">10xb</span>
  </div>
  <a href="/visit/bonus/jackpot-city">Claim bonus</a>
</div>
<div class="details-card">
  <span class="details-card-name">YesPlay Casino</span>
  <a class="details-card-title" href="/casino-bonuses/latest/yesplay">100% up to 3000 ZAR</a>
  <div class="details-card-details__item">
    <span class="details-card-details__label">Category</span>
    <span class="details-card-details__value">Welcome Bonus</span>
  </div>
  <div class="details-card-details__item">
    <span class="details-card-details__label">Minimum Deposit</span>
    <span class="details-card-details__value">20 ZAR</span>
  </div>
  <div class="details-card-details__item">
    <span class="details-card-details__label">Wagering Requirements</span>
    <span class="details-card-details__value">7x(d+b)</span>
  </div>
</div>
<div class="details-card">
  <span class="details-card-name">BetBeast Casino</span>
  <a class="details-card-title" href="/casino-bonuses/latest/betbeast">250% up to €1000 + 250 Free Spins</a>
  <div class="details-card-details__item">
    <span class="details-card-details__label">Category</span>
    <span class="details-card-details__value">Welcome Bonus</span>
  </div>
  <div class="details-card-details__item">
    <span class="details-card-details__label">Minimum Deposit</span>
    <span class="details-card-details__value">€20</span>
  </div>
  <div class="details-card-details__item">
    <span class="details-card-details__label">Wagering Requirements</span>
    <span class="details-card-details__value">25x(d+b)</span>
  </div>
</div>
<div class="details-card">
  <span class="details-card-name">Reload Example</span>
  <a class="details-card-title" href="/casino-bonuses/latest/reload">50% reload</a>
  <div class="details-card-details__item">
    <span class="details-card-details__label">Category</span>
    <span class="details-card-details__value">Reload Bonus</span>
  </div>
</div>
</body></html>
"""


def test_extracts_askgamblers_welcome_cards():
    offers = extract_casino_offers(
        ASKGAMBLERS_HTML,
        page_url="https://www.askgamblers.com/casino-bonuses/welcome",
    )
    assert [offer.casino_name for offer in offers] == [
        "Jackpot City Casino",
        "YesPlay Casino",
        "BetBeast Casino",
    ]
    assert "4000 ZAR" in offers[0].bonus_text
    assert "10xb" in offers[0].terms_text
    assert "7x(d+b)" in offers[1].terms_text
    assert offers[0].source_url == "https://www.askgamblers.com/casino-bonuses/latest/jackpot-city"
    assert "/visit/" not in offers[0].source_url
    deposit = parse_minimum_deposit(offers[0].terms_text)
    assert deposit["amount"] == 50.0
    assert deposit["currency"] == "ZAR"
    wager = parse_wagering_multiplier(offers[0].terms_text)
    assert wager["multiplier"] == 10.0
    assert wager["applies_to"] == "bonus"


def test_parse_wagering_multiplier_bonus_only():
    parsed = parse_wagering_multiplier("35x wagering on the bonus amount")
    assert parsed["multiplier"] == 35.0
    assert parsed["applies_to"] == "bonus"
    assert parsed["status"] == "ok"


def test_parse_wagering_multiplier_deposit_plus_bonus():
    parsed = parse_wagering_multiplier("25x on deposit + bonus")
    assert parsed["multiplier"] == 25.0
    assert parsed["applies_to"] == "deposit_plus_bonus"
    shorthand = parse_wagering_multiplier("7x(d+b)")
    assert shorthand["multiplier"] == 7.0
    assert shorthand["applies_to"] == "deposit_plus_bonus"
    bonus_suffix = parse_wagering_multiplier("10xb")
    assert bonus_suffix["multiplier"] == 10.0
    assert bonus_suffix["applies_to"] == "bonus"


def test_parse_wagering_multiplier_ambiguous_multiple_values():
    parsed = parse_wagering_multiplier("1x for no-deposit bonus, 15x for deposit bonus")
    assert parsed["multiplier"] is None
    assert parsed["status"] == "ambiguous"
    assert parsed["candidates"] == [1.0, 15.0]


def test_parse_wagering_missing_and_none():
    missing = parse_wagering_multiplier("")
    assert missing["multiplier"] is None
    assert missing["status"] == "missing"
    none = parse_wagering_multiplier("None")
    assert none["multiplier"] is None
    assert none["status"] == "missing"


def test_parse_minimum_deposit_and_currency():
    parsed = parse_minimum_deposit("Minimum deposit $20 to activate the bonus")
    assert parsed["amount"] == 20.0
    assert parsed["currency"] == "USD"
    assert parsed["status"] == "ok"

    euro = parse_minimum_deposit("Min deposit €15")
    assert euro["amount"] == 15.0
    assert euro["currency"] == "EUR"


def test_parse_minimum_deposit_from_deposit_phrase():
    parsed = parse_minimum_deposit("Deposit $10 for up to 1,000 Bonus Spins")
    assert parsed["amount"] == 10.0
    assert parsed["currency"] == "USD"


def test_parse_minimum_deposit_ambiguous_and_missing():
    missing = parse_minimum_deposit("Welcome package includes free spins")
    assert missing["amount"] is None
    assert missing["status"] == "ambiguous"
    empty = parse_minimum_deposit("")
    assert empty["status"] == "missing"
    many = parse_minimum_deposit("Deposit $10 or deposit $25 depending on the method")
    assert many["amount"] is None
    assert many["status"] == "ambiguous"
