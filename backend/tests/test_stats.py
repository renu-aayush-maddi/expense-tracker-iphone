def add(client, headers, amount, merchant, category, day, bank=None, method="UPI"):
    response = client.post(
        "/api/transactions",
        json={
            "amount": amount,
            "merchant_name": merchant,
            "category": category,
            "transaction_date": day,
            "bank": bank,
            "payment_method": method,
        },
        headers=headers,
    )
    assert response.status_code == 201


def test_dashboard(client, auth_headers):
    add(client, auth_headers, "500", "Zomato", "Food", "2026-10-03", "Kotak")
    add(client, auth_headers, "250.50", "Uber", "Transport", "2026-10-01", "HDFC", "Credit Card")
    add(client, auth_headers, "100", "Swiggy", "Food", "2026-10-01", "Kotak")
    add(client, auth_headers, "1000", "Rent", "Rent", "2026-09-05")
    add(client, auth_headers, "50", "Old", "Other", "2025-01-05")

    body = client.get("/api/stats/dashboard?year=2026&month=10", headers=auth_headers).json()
    assert body["month_total"] == "850.50"
    assert body["month_count"] == 3
    assert body["month_average"] == "283.50"
    assert body["largest_transaction"]["merchant_name"] == "Zomato"
    assert body["by_category"][0] == {"label": "Food", "total": "600.00", "count": 2}
    assert {g["label"] for g in body["by_bank"]} == {"Kotak", "HDFC"}
    assert {g["label"] for g in body["by_payment_method"]} == {"UPI", "Credit Card"}
    assert len(body["daily"]) == 31
    assert body["daily"][0]["total"] == "350.50"
    assert len(body["monthly_trend"]) == 12
    assert body["monthly_trend"][-1] == {"year": 2026, "month": 10, "label": "Oct 2026", "total": "850.50"}
    assert body["monthly_trend"][-2]["total"] == "1000.00"
    assert body["yearly"] == [{"year": 2025, "total": "50.00"}, {"year": 2026, "total": "1850.50"}]
    assert len(body["recent_transactions"]) == 5
    assert body["pending_reviews"] == 0


def test_dashboard_empty_month(client, auth_headers):
    body = client.get("/api/stats/dashboard?year=2020&month=2", headers=auth_headers).json()
    assert body["month_total"] == "0.00"
    assert body["month_average"] == "0.00"
    assert body["largest_transaction"] is None
    assert len(body["daily"]) == 29  # leap year
