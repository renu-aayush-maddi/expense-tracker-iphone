"""Real-world receipt layouts, and the LLM fallback (mocked – no network in tests)."""

from datetime import date, time
from decimal import Decimal

import pytest

from app.services import llm_extractor
from app.services.llm_extractor import LLMReceipt
from app.services.phonepe_parser import parse_phonepe_receipt

TODAY = date(2026, 10, 3)
URL = "/api/transactions/import/phonepe"

# Layout of a real PhonePe "Share Receipt": the amount sits on the merchant /
# account rows and there is no "Amount:" label.
REAL_LAYOUT = """Transaction Successful
1:11 pm on 03 Oct 2026
Paid to
BigBasket bigbasket@payuaxis
Transfer Details
Transaction ID
T2610031311415776289288
Debited from
XXXXXX096929 ¥183
UTR: 706226593892
Powered by UPI
"""

# Same receipt, but OCR turned ₹ into something unrecognisable.
UNREADABLE_SYMBOL = REAL_LAYOUT.replace("XXXXXX096929 ¥183", "XXXXXX096929\n§ ¡183!")


def parse(text):
    return parse_phonepe_receipt(text, today=TODAY)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.api.imports.today_local", lambda: TODAY)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the OpenAI call. Set `fake_llm.answer` to what the 'model' returns."""

    class Fake:
        answer = None
        calls = 0

        def __call__(self, text):
            self.calls += 1
            self.last_text = text
            return self.answer

    fake = Fake()
    # Patch only the network call, so redaction and error handling still run for real.
    monkeypatch.setattr(llm_extractor, "is_enabled", lambda: True)
    monkeypatch.setattr(llm_extractor, "_call_openai", fake)
    return fake


def answer(amount="183", merchant="BigBasket", day="2026-10-03", at="13:11", direction="paid"):
    return LLMReceipt(amount=amount, merchant_name=merchant, transaction_date=day, transaction_time=at, direction=direction)


# ---------------------------------------------------------------- parser on real layouts
def test_real_layout_amount_on_account_line():
    result = parse(REAL_LAYOUT)
    d = result.data
    assert d.amount == Decimal("183.00")
    assert d.merchant_name == "BigBasket"
    assert d.upi_id == "bigbasket@payuaxis"
    assert d.transaction_date == date(2026, 10, 3)
    assert d.transaction_time == time(13, 11)
    assert d.phonepe_transaction_id == "T2610031311415776289288"
    assert d.utr == "706226593892"
    assert d.account_last4 == "6929"
    assert result.issues == []


@pytest.mark.parametrize("symbol", ["¥", "￥", "円", "€", "£", "$", "Rs.", "Re", "Y", "Z", "F", "%", "*", "?", ""])
def test_any_misread_currency_symbol(symbol):
    text = REAL_LAYOUT.replace("XXXXXX096929 ¥183", f"XXXXXX096929\n{symbol}183")
    assert parse(text).data.amount == Decimal("183.00"), symbol


def test_amount_glued_to_merchant_line():
    text = REAL_LAYOUT.replace("BigBasket bigbasket@payuaxis", "BigBasket ¥183\nbigbasket@payuaxis").replace(
        "XXXXXX096929 ¥183", "XXXXXX096929"
    )
    result = parse(text)
    assert result.data.merchant_name == "BigBasket"
    assert result.data.amount == Decimal("183.00")


def test_truncated_handle_removed_from_merchant():
    text = REAL_LAYOUT.replace("BigBasket bigbasket@payuaxis", "UBER INDIA SYSTEMS... uberindiasystem187204.rzp")
    result = parse(text)
    assert result.data.merchant_name == "UBER INDIA SYSTEMS"
    assert result.data.upi_id == "uberindiasystem187204.rzp"


def test_lone_year_is_not_an_amount():
    text = REAL_LAYOUT.replace("XXXXXX096929 ¥183", "XXXXXX096929\n2026")
    assert parse(text).data.amount is None


def test_unreadable_symbol_needs_review_without_llm():
    result = parse(UNREADABLE_SYMBOL)
    assert result.data.amount is None
    assert result.needs_review


# ---------------------------------------------------------------- redaction
def test_redact_removes_identifiers():
    redacted = llm_extractor.redact(REAL_LAYOUT + "\nUTR: 7062 2659 3892")
    assert "T2610031311415776289288" not in redacted
    assert "706226593892" not in redacted
    assert "7062 2659 3892" not in redacted
    assert "096929" not in redacted
    assert "183" in redacted and "BigBasket" in redacted


def test_amount_numbers_exclude_dates_and_times():
    numbers = llm_extractor.amount_numbers_in(REAL_LAYOUT)
    assert Decimal("183") in numbers
    assert Decimal("3") not in numbers and Decimal("11") not in numbers and Decimal("2026") not in numbers


# ---------------------------------------------------------------- import API with LLM
def test_llm_fills_unreadable_amount(client, auth_headers, fake_llm):
    fake_llm.answer = answer(amount="183")
    response = client.post(URL, json={"ocr_text": UNREADABLE_SYMBOL}, headers=auth_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["message"] == "Expense added: ₹183 — BigBasket"
    assert body["transaction"]["extraction_method"] == "ai"
    assert body["transaction"]["phonepe_transaction_id"] == "T2610031311415776289288"  # from the parser, not the LLM
    # The LLM never saw the identifiers.
    assert "T2610031311415776289288" not in fake_llm.last_text
    assert "706226593892" not in fake_llm.last_text


def test_llm_amount_not_in_text_is_rejected(client, auth_headers, fake_llm):
    fake_llm.answer = answer(amount="999")  # hallucinated
    body = client.post(URL, json={"ocr_text": UNREADABLE_SYMBOL}, headers=auth_headers).json()
    assert body["status"] == "review_required"


def test_llm_cannot_use_date_as_amount(client, auth_headers, fake_llm):
    fake_llm.answer = answer(amount="3")  # the day of the month
    body = client.post(URL, json={"ocr_text": UNREADABLE_SYMBOL}, headers=auth_headers).json()
    assert body["status"] == "review_required"


def test_llm_must_pick_one_of_the_parsers_candidates(client, auth_headers, fake_llm):
    text = REAL_LAYOUT.replace("XXXXXX096929 ¥183", "XXXXXX096929\n¥183\n¥1,830")
    fake_llm.answer = answer(amount="1,830")
    body = client.post(URL, json={"ocr_text": text}, headers=auth_headers).json()
    assert body["status"] == "created"
    assert body["transaction"]["amount"] == "1830.00"


def test_llm_says_money_received(client, auth_headers, fake_llm):
    fake_llm.answer = answer(direction="received")
    body = client.post(URL, json={"ocr_text": UNREADABLE_SYMBOL}, headers=auth_headers).json()
    assert body["status"] == "review_required"


def test_llm_unavailable_falls_back_to_review(client, auth_headers, fake_llm):
    fake_llm.answer = None  # disabled, timeout, quota...
    body = client.post(URL, json={"ocr_text": UNREADABLE_SYMBOL}, headers=auth_headers).json()
    assert body["status"] == "review_required"


def test_llm_not_called_when_parser_succeeds(client, auth_headers, fake_llm):
    client.post(URL, json={"ocr_text": REAL_LAYOUT}, headers=auth_headers)
    assert fake_llm.calls == 0


def test_llm_not_called_for_duplicates(client, auth_headers, fake_llm):
    client.post(URL, json={"ocr_text": REAL_LAYOUT}, headers=auth_headers)
    body = client.post(URL, json={"ocr_text": UNREADABLE_SYMBOL}, headers=auth_headers).json()
    assert body["status"] == "duplicate"
    assert fake_llm.calls == 0


def test_extract_returns_none_on_api_error(monkeypatch):
    import openai

    from app.core.config import settings

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")

    class Broken:
        def __init__(self, **kwargs):
            raise openai.APIConnectionError(request=None)

    monkeypatch.setattr(openai, "OpenAI", Broken)
    assert llm_extractor.extract(REAL_LAYOUT) is None


# ---------------------------------------------------------------- pending reviews
def test_same_receipt_with_different_ocr_gives_one_review(client, auth_headers, fake_llm):
    first = UNREADABLE_SYMBOL.replace("uberindia", "")
    second = UNREADABLE_SYMBOL.replace("Powered by UPI", "Powered by UPl")  # OCR differs slightly
    a = client.post(URL, json={"ocr_text": first}, headers=auth_headers).json()
    b = client.post(URL, json={"ocr_text": second}, headers=auth_headers).json()
    assert a["review_id"] == b["review_id"]
    assert len(client.get("/api/imports/pending", headers=auth_headers).json()) == 1


def test_saving_receipt_clears_its_pending_review(client, auth_headers, fake_llm):
    client.post(URL, json={"ocr_text": UNREADABLE_SYMBOL}, headers=auth_headers)
    assert len(client.get("/api/imports/pending", headers=auth_headers).json()) == 1
    client.post(URL, json={"ocr_text": REAL_LAYOUT}, headers=auth_headers)  # a clean re-share
    assert client.get("/api/imports/pending", headers=auth_headers).json() == []


def test_reprocess_pending(client, auth_headers, fake_llm):
    client.post(URL, json={"ocr_text": UNREADABLE_SYMBOL}, headers=auth_headers)
    other = UNREADABLE_SYMBOL.replace("T2610031311415776289288", "T2610031311415776280000").replace(
        "706226593892", "706226590000"
    )
    client.post(URL, json={"ocr_text": other}, headers=auth_headers)
    assert len(client.get("/api/imports/pending", headers=auth_headers).json()) == 2

    fake_llm.answer = answer()  # e.g. the LLM fallback was just switched on
    counts = client.post("/api/imports/pending/reprocess", headers=auth_headers).json()
    # The second receipt has the same date/amount/merchant/time, so it's a fallback duplicate.
    assert counts == {"created": 1, "duplicate": 1, "review_required": 0, "invalid": 0}
    assert client.get("/api/imports/pending", headers=auth_headers).json() == []


def test_confirmed_review_marked_as_reviewed(client, auth_headers, fake_llm):
    review_id = client.post(URL, json={"ocr_text": UNREADABLE_SYMBOL}, headers=auth_headers).json()["review_id"]
    payload = {"amount": "183", "merchant_name": "BigBasket", "transaction_date": "2026-10-03",
               "phonepe_transaction_id": "T2610031311415776289288"}
    body = client.post(f"/api/imports/pending/{review_id}/confirm", json=payload, headers=auth_headers).json()
    assert body["extraction_method"] == "reviewed"
