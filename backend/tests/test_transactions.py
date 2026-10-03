from tests.conftest import register

ZOMATO = {
    "amount": "500",
    "merchant_name": "Zomato",
    "category": "Food",
    "transaction_date": "2026-10-03",
    "transaction_time": "20:15",
    "payment_method": "UPI",
    "bank": "Kotak",
    "notes": "Dinner",
}


def create(client, headers, **overrides):
    response = client.post("/api/transactions", json={**ZOMATO, **overrides}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_manual_transaction(client, auth_headers):
    body = create(client, auth_headers)
    assert body["amount"] == "500.00"  # exact decimal, serialised as string
    assert body["merchant_name"] == "Zomato"
    assert body["category"] == "Food"
    assert body["source"] == "manual"
    assert body["bank"] == "Kotak"
    assert body["transaction_time"] == "20:15:00"


def test_create_requires_auth(client):
    assert client.post("/api/transactions", json=ZOMATO).status_code == 401


def test_create_validates_input(client, auth_headers):
    for bad in ({"amount": "0"}, {"amount": "-5"}, {"amount": "10.999"}, {"category": "Gambling"}, {"merchant_name": "  "}):
        response = client.post("/api/transactions", json={**ZOMATO, **bad}, headers=auth_headers)
        assert response.status_code == 422, bad


def test_category_is_case_insensitive(client, auth_headers):
    assert create(client, auth_headers, category="food")["category"] == "Food"


def test_decimal_amounts_are_exact(client, auth_headers):
    create(client, auth_headers, amount="0.10", merchant_name="A")
    create(client, auth_headers, amount="0.20", merchant_name="B")
    response = client.get("/api/stats/dashboard?year=2026&month=10", headers=auth_headers)
    assert response.json()["month_total"] == "0.30"


def test_get_transaction(client, auth_headers):
    created = create(client, auth_headers)
    response = client.get(f"/api/transactions/{created['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["merchant_name"] == "Zomato"
    assert "raw_ocr_text" in response.json()


def test_get_missing_transaction_is_404(client, auth_headers):
    response = client.get("/api/transactions/00000000-0000-0000-0000-000000000000", headers=auth_headers)
    assert response.status_code == 404


def test_users_cannot_see_each_others_transactions(client, auth_headers):
    created = create(client, auth_headers)
    other = register(client, email="other@example.com")
    assert client.get(f"/api/transactions/{created['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/transactions/{created['id']}", headers=other).status_code == 404
    assert client.get("/api/transactions", headers=other).json()["total"] == 0


def test_update_transaction(client, auth_headers):
    created = create(client, auth_headers)
    response = client.put(
        f"/api/transactions/{created['id']}",
        json={"category": "Entertainment", "amount": "450.50", "notes": ""},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "Entertainment"
    assert body["amount"] == "450.50"
    assert body["notes"] is None
    assert body["merchant_name"] == "Zomato"  # untouched


def test_update_cannot_clear_required_fields(client, auth_headers):
    created = create(client, auth_headers)
    response = client.put(f"/api/transactions/{created['id']}", json={"amount": None}, headers=auth_headers)
    assert response.status_code == 422


def test_delete_transaction(client, auth_headers):
    created = create(client, auth_headers)
    assert client.delete(f"/api/transactions/{created['id']}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/transactions/{created['id']}", headers=auth_headers).status_code == 404


def test_duplicate_utr_is_rejected(client, auth_headers):
    create(client, auth_headers, utr="706226593892")
    response = client.post("/api/transactions", json={**ZOMATO, "utr": "706226593892"}, headers=auth_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["existing_transaction_id"]


def test_list_filters_search_and_pagination(client, auth_headers):
    create(client, auth_headers)
    create(client, auth_headers, merchant_name="Uber", category="Transport", amount="250", bank="HDFC", notes=None,
           transaction_date="2026-09-15")
    create(client, auth_headers, merchant_name="Netflix", category="Subscriptions", amount="649",
           payment_method="Credit Card", transaction_date="2025-12-01", notes=None)

    def ids(query):
        response = client.get(f"/api/transactions?{query}", headers=auth_headers)
        assert response.status_code == 200, response.text
        return [t["merchant_name"] for t in response.json()["items"]]

    assert ids("") == ["Zomato", "Uber", "Netflix"]  # newest first
    assert ids("category=Transport") == ["Uber"]
    assert ids("bank=hdfc") == ["Uber"]
    assert ids("payment_method=Credit%20Card") == ["Netflix"]
    assert ids("merchant=zom") == ["Zomato"]
    assert ids("search=dinner") == ["Zomato"]
    assert ids("year=2026") == ["Zomato", "Uber"]
    assert ids("year=2026&month=9") == ["Uber"]
    assert ids("date=2026-10-03") == ["Zomato"]
    assert ids("min_amount=300&max_amount=600") == ["Zomato"]
    assert ids("sort_by=amount&sort_order=asc") == ["Uber", "Zomato", "Netflix"]

    page = client.get("/api/transactions?page=2&page_size=2", headers=auth_headers).json()
    assert page["total"] == 3
    assert page["pages"] == 2
    assert [t["merchant_name"] for t in page["items"]] == ["Netflix"]


def test_filter_options(client, auth_headers):
    create(client, auth_headers)
    body = client.get("/api/transactions/filter-options", headers=auth_headers).json()
    assert "Food" in body["categories"]
    assert body["banks"] == ["Kotak"]
    assert "UPI" in body["payment_methods"]


def test_raw_ocr_not_in_list_response(client, auth_headers, sample_ocr):
    client.post("/api/transactions/import/phonepe", json={"ocr_text": sample_ocr}, headers=auth_headers)
    item = client.get("/api/transactions", headers=auth_headers).json()["items"][0]
    assert "raw_ocr_text" not in item
