from pathlib import Path

import pytest
import requests

from scraper import scrape as scrape_mod
from scraper.extract import extract_casino_offers
from scraper.validate import is_publishable


class DummyResponse:
    def __init__(self, text="", status_code=200, url="https://www.playmichigan.com/online-casino/bonus/"):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code}")
            error.response = self
            raise error


def test_http_timeout_preserves_existing_data(tmp_path, monkeypatch, sample_html):
    output = tmp_path / "casinos.json"
    existing = {
        "status": "ok",
        "casinos": [
            {
                "casino_name": "Existing Casino",
                "welcome_bonus": "100% up to $100",
                "wagering_requirement": {"multiplier": 10, "applies_to": "bonus", "notes": None},
                "minimum_deposit": {"amount": 10, "currency": "USD", "notes": None},
                "source_url": "https://www.playmichigan.com/online-casino/existing/",
                "retrieved_at": "2026-01-01T00:00:00+00:00",
                "extraction_status": "ok",
            }
            for _ in range(3)
        ],
    }
    existing["casinos"][1]["casino_name"] = "Second Casino"
    existing["casinos"][1]["source_url"] = "https://www.playmichigan.com/online-casino/second/"
    existing["casinos"][2]["casino_name"] = "Third Casino"
    existing["casinos"][2]["source_url"] = "https://www.playmichigan.com/online-casino/third/"
    output.write_text(__import__("json").dumps(existing), encoding="utf-8")
    monkeypatch.setattr(scrape_mod, "OUTPUT_PATH", output)

    class TimeoutSession:
        def get(self, url, timeout=None, allow_redirects=True):
            raise requests.Timeout("timed out")

        def headers(self):
            return {}

    # Bypass robots so the timeout path is exercised on the page fetch.
    monkeypatch.setattr(scrape_mod, "check_robots", lambda url, session: (True, "allowed"))
    monkeypatch.setattr(scrape_mod, "build_session", lambda: TimeoutSession())
    monkeypatch.setattr(scrape_mod, "configure_logging", lambda: None)
    monkeypatch.setattr(
        scrape_mod,
        "fetch_page",
        lambda session, url: (_ for _ in ()).throw(requests.Timeout("timed out")),
    )

    code = scrape_mod.run()
    assert code == 3
    saved = __import__("json").loads(output.read_text(encoding="utf-8"))
    assert saved["casinos"][0]["casino_name"] == "Existing Casino"


def test_http_error_does_not_publish(monkeypatch, tmp_path):
    output = tmp_path / "casinos.json"
    monkeypatch.setattr(scrape_mod, "OUTPUT_PATH", output)
    monkeypatch.setattr(scrape_mod, "check_robots", lambda url, session: (True, "allowed"))
    monkeypatch.setattr(scrape_mod, "configure_logging", lambda: None)

    class ErrorSession:
        def get(self, url, timeout=None, allow_redirects=True):
            response = DummyResponse(status_code=403)
            response.raise_for_status()

    monkeypatch.setattr(scrape_mod, "build_session", lambda: ErrorSession())

    def fail_http(session, url):
        response = DummyResponse(status_code=403)
        response.raise_for_status()

    monkeypatch.setattr(scrape_mod, "fetch_page", fail_http)
    code = scrape_mod.run()
    assert code == 3
    assert not output.exists()


def test_failed_llm_does_not_replace_valid_file(monkeypatch, tmp_path, sample_html):
    output = tmp_path / "casinos.json"
    existing = {
        "status": "ok",
        "casinos": [
            {
                "casino_name": f"Casino {i}",
                "welcome_bonus": "Keep me",
                "wagering_requirement": {"multiplier": 1, "applies_to": "bonus", "notes": None},
                "minimum_deposit": {"amount": 5, "currency": "USD", "notes": None},
                "source_url": f"https://www.playmichigan.com/online-casino/c{i}/",
                "retrieved_at": "2026-01-01T00:00:00+00:00",
                "extraction_status": "ok",
            }
            for i in range(3)
        ],
    }
    output.write_text(__import__("json").dumps(existing), encoding="utf-8")
    monkeypatch.setattr(scrape_mod, "OUTPUT_PATH", output)
    monkeypatch.setattr(scrape_mod, "configure_logging", lambda: None)
    monkeypatch.setattr(scrape_mod, "check_robots", lambda url, session: (True, "allowed"))
    monkeypatch.setattr(
        scrape_mod,
        "fetch_page",
        lambda session, url: (sample_html, "https://www.playmichigan.com/online-casino/bonus/"),
    )
    monkeypatch.setattr(scrape_mod, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(scrape_mod, "choose_model", lambda key: "claude-test")
    monkeypatch.setattr(scrape_mod, "call_claude", lambda *args, **kwargs: "THIS IS NOT JSON")

    code = scrape_mod.run()
    assert code == 3
    saved = __import__("json").loads(output.read_text(encoding="utf-8"))
    assert saved["casinos"][0]["welcome_bonus"] == "Keep me"


def test_robots_disallow_skips_fetch(monkeypatch, tmp_path):
    output = tmp_path / "casinos.json"
    monkeypatch.setattr(scrape_mod, "OUTPUT_PATH", output)
    monkeypatch.setattr(scrape_mod, "configure_logging", lambda: None)
    monkeypatch.setattr(scrape_mod, "check_robots", lambda url, session: (False, "disallowed"))
    fetched = {"called": False}

    def fail_fetch(*args, **kwargs):
        fetched["called"] = True
        raise AssertionError("must not fetch when robots disallows")

    monkeypatch.setattr(scrape_mod, "fetch_page", fail_fetch)
    code = scrape_mod.run()
    assert code == 3
    assert fetched["called"] is False


def test_incomplete_llm_result_is_not_verified(sample_html):
    offers = extract_casino_offers(sample_html, "https://www.playmichigan.com/online-casino/bonus/")
    document = {
        "status": "ok",
        "casinos": [
            {
                "casino_name": offers[0].casino_name,
                "welcome_bonus": None,
                "wagering_requirement": None,
                "minimum_deposit": None,
                "source_url": offers[0].source_url,
                "retrieved_at": "2026-01-01T00:00:00+00:00",
                "extraction_status": "failed",
            }
        ]
        * 3,
    }
    ok, _reason = is_publishable(document)
    assert ok is False
