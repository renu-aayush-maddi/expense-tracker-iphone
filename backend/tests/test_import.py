"""End-to-end tests of the PhonePe import API (parser + duplicates + DB)."""

from datetime import date

import pytest

from tests.conftest import SAMPLE_OCR, register

URL = "/api/transactions/import/phonepe"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.api.imports.today_local", lambda: date(2026, 10, 3))


def do_import(client, headers, text=SAMPLE_OCR):
    return client.post(URL, json={"ocr_text": text}, headers=headers)


def count(client, headers):
    return client.get("/api/transactions", headers=headers).json()["total"]


def test_import_creates_transaction(client, auth_headers):
    response = do_import(client, auth_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["success"] is True
    assert body["status"] == "created"
    assert body["message"] == "Expense added: ₹183 — BLINK COMMERCE PRIVA"
    t = body["transaction"]
    assert t["amount"] == "183.00"
    assert t["merchant_name"] == "BLINK COMMERCE PRIVA"
    assert t["category"] == "Groceries"
    assert t["phonepe_transaction_id"] == "T2610031311415776289288"
    assert t["utr"] == "706226593892"
    assert t["account_last4"] == "6929"
    assert t["source"] == "phonepe"
    assert t["payment_method"] == "UPI"
    assert t["notes"] is None  # "UPIIntent" is not a useful note

    detail = client.get(f"/api/transactions/{t['id']}", headers=auth_headers).json()
    assert detail["raw_ocr_text"] == SAMPLE_OCR


def test_sharing_same_receipt_twice_is_duplicate(client, auth_headers):
    first = do_import(client, auth_headers)
    second = do_import(client, auth_headers)
    assert second.status_code == 200
    body = second.json()
    assert body == {**body, "success": True, "status": "duplicate", "message": "Transaction already exists"}
    assert body["existing_transaction_id"] == first.json()["transaction"]["id"]
    assert count(client, auth_headers) == 1


def test_duplicate_detected_by_utr_even_if_ocr_differs(client, auth_headers):
    do_import(client, auth_headers)
    # Different OCR run: transaction ID unreadable, extra noise – same UTR.
    text = SAMPLE_OCR.replace("T2610031311415776289288", "unreadable") + "\nextra noise"
    response = do_import(client, auth_headers, text)
    assert response.json()["status"] == "duplicate"
    assert count(client, auth_headers) == 1


def test_duplicate_detected_by_transaction_id(client, auth_headers):
    do_import(client, auth_headers)
    text = SAMPLE_OCR.replace("706226593892", "")
    assert do_import(client, auth_headers, text).json()["status"] == "duplicate"


def test_duplicates_are_per_user(client, auth_headers):
    do_import(client, auth_headers)
    other = register(client, email="other@example.com")
    assert do_import(client, other).json()["status"] == "created"


def test_uncertain_receipt_requires_review(client, auth_headers):
    text = SAMPLE_OCR.replace("Amount:\n¥183\n", "")
    response = do_import(client, auth_headers, text)
    assert response.status_code == 202
    body = response.json()
    assert body["success"] is False
    assert body["status"] == "review_required"
    assert body["review_id"]
    assert body["parsed_data"]["phonepe_transaction_id"] == "T2610031311415776289288"
    assert body["parsed_data"]["amount"] is None
    assert any("Amount" in issue for issue in body["issues"])
    assert count(client, auth_headers) == 0  # nothing saved silently

    # Sharing the same uncertain receipt again doesn't create a second review.
    again = do_import(client, auth_headers, text).json()
    assert again["review_id"] == body["review_id"]
    pending = client.get("/api/imports/pending", headers=auth_headers).json()
    assert len(pending) == 1


def test_confirm_review_saves_transaction(client, auth_headers):
    text = SAMPLE_OCR.replace("Amount:\n¥183\n", "")
    review_id = do_import(client, auth_headers, text).json()["review_id"]

    pending = client.get(f"/api/imports/pending/{review_id}", headers=auth_headers).json()
    data = pending["parsed_data"]
    payload = {
        "amount": "183",
        "merchant_name": "Blinkit",
        "category": "Groceries",
        "transaction_date": data["transaction_date"],
        "transaction_time": data["transaction_time"],
        "payment_method": "UPI",
        "phonepe_transaction_id": data["phonepe_transaction_id"],
        "utr": data["utr"],
        "account_last4": data["account_last4"],
    }
    response = client.post(f"/api/imports/pending/{review_id}/confirm", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "phonepe"
    assert body["raw_ocr_text"] == text
    assert client.get("/api/imports/pending", headers=auth_headers).json() == []

    # Now the original receipt is recognised as a duplicate.
    assert do_import(client, auth_headers).json()["status"] == "duplicate"


def test_confirm_review_blocks_similar_unless_allowed(client, auth_headers):
    client.post(
        "/api/transactions",
        json={"amount": "183", "merchant_name": "Blinkit", "transaction_date": "2026-10-03"},
        headers=auth_headers,
    )
    text = SAMPLE_OCR.replace("Amount:\n¥183\n", "")
    review_id = do_import(client, auth_headers, text).json()["review_id"]
    payload = {"amount": "183", "merchant_name": "Blinkit", "transaction_date": "2026-10-03",
               "phonepe_transaction_id": "T2610031311415776289288"}

    response = client.post(f"/api/imports/pending/{review_id}/confirm", json=payload, headers=auth_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["similar"] is True

    response = client.post(
        f"/api/imports/pending/{review_id}/confirm?allow_similar=true", json=payload, headers=auth_headers
    )
    assert response.status_code == 201


def test_discard_review(client, auth_headers):
    text = SAMPLE_OCR.replace("Amount:\n¥183\n", "")
    review_id = do_import(client, auth_headers, text).json()["review_id"]
    assert client.delete(f"/api/imports/pending/{review_id}", headers=auth_headers).status_code == 204
    assert client.get("/api/imports/pending", headers=auth_headers).json() == []


def test_invalid_ocr(client, auth_headers):
    response = do_import(client, auth_headers, "just a random photo with no receipt")
    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "invalid"
    assert body["success"] is False
    assert count(client, auth_headers) == 0


def test_empty_ocr_rejected_by_validation(client, auth_headers):
    assert do_import(client, auth_headers, "").status_code == 422


def test_import_requires_auth(client):
    assert client.post(URL, json={"ocr_text": SAMPLE_OCR}).status_code == 401


def test_import_with_personal_token(client, auth_headers):
    token = client.post("/api/settings/tokens", json={"name": "iPhone"}, headers=auth_headers).json()["token"]
    assert token.startswith("etk_")
    shortcut_headers = {"Authorization": f"Bearer {token}"}

    response = do_import(client, shortcut_headers)
    assert response.status_code == 201
    assert count(client, auth_headers) == 1

    # The import token works ONLY for importing.
    assert client.get("/api/transactions", headers=shortcut_headers).status_code == 403

    tokens = client.get("/api/settings/tokens", headers=auth_headers).json()
    assert tokens[0]["last_used_at"] is not None
    assert "token" not in tokens[0]  # never shown again


def test_deleted_token_stops_working(client, auth_headers):
    created = client.post("/api/settings/tokens", json={}, headers=auth_headers).json()
    client.delete(f"/api/settings/tokens/{created['id']}", headers=auth_headers)
    response = do_import(client, {"Authorization": f"Bearer {created['token']}"})
    assert response.status_code == 401


def test_bank_mapping_fills_bank(client, auth_headers):
    client.post("/api/settings/accounts", json={"account_last4": "6929", "bank_name": "Kotak"}, headers=auth_headers)
    body = do_import(client, auth_headers).json()
    assert body["transaction"]["bank"] == "Kotak"


def test_category_learned_from_previous_choice(client, auth_headers):
    first = do_import(client, auth_headers).json()["transaction"]
    client.put(f"/api/transactions/{first['id']}", json={"category": "Shopping"}, headers=auth_headers)

    text = (
        SAMPLE_OCR.replace("T2610031311415776289288", "T2610041311415776289999")
        .replace("706226593892", "706226590000")
        .replace("3 October", "2 October")
    )
    second = do_import(client, auth_headers, text).json()
    assert second["status"] == "created"
    assert second["transaction"]["category"] == "Shopping"


def test_import_rate_limit(client, auth_headers, monkeypatch):
    from app.api.imports import import_limiter

    monkeypatch.setattr(import_limiter, "max_requests", 2)
    do_import(client, auth_headers)
    do_import(client, auth_headers)
    assert do_import(client, auth_headers).status_code == 429


def test_request_size_limit(client, auth_headers):
    response = client.post(URL, json={"ocr_text": "x" * 70_000}, headers=auth_headers)
    assert response.status_code == 413


def test_ocr_text_length_limit(client, auth_headers):
    response = client.post(URL, json={"ocr_text": "x" * 20_001}, headers=auth_headers)
    assert response.status_code == 422
    assert "x" * 100 not in response.text  # submitted text is not echoed back
