"""Company reimbursement: default rule, manual overrides, settings, filters, CSV."""

from datetime import date

import pytest

from tests.conftest import SAMPLE_OCR, register

# 2026-10-01 Thu, 10-02 Fri, 10-03 Sat, 10-04 Sun, 10-05 Mon
THU, FRI, SAT, SUN, MON = "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"


def add(client, headers, merchant, day, amount="200", **extra):
    response = client.post(
        "/api/transactions",
        json={"amount": amount, "merchant_name": merchant, "transaction_date": day, **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "merchant, day, expected",
    [
        ("Uber", THU, True),
        ("UBER INDIA SYSTEMS", FRI, True),
        ("Rapido", MON, True),
        ("Ola Cabs", THU, True),
        ("ANI TECHNOLOGIES PVT LTD", THU, True),  # Ola's company name
        ("Roppen Transportation Services", THU, True),  # Rapido's company name
        ("Uber", SAT, False),  # weekend
        ("Rapido", SUN, False),
        ("Coca Cola", THU, False),  # "ola" must match a whole word
        ("Zomato", THU, False),
    ],
)
def test_default_rule(client, auth_headers, merchant, day, expected):
    body = add(client, auth_headers, merchant, day)
    assert body["is_reimbursable"] is expected
    assert body["reimbursable_set_by"] == "rule"


def test_user_choice_on_create_wins(client, auth_headers):
    assert add(client, auth_headers, "Uber", THU, is_reimbursable=False)["is_reimbursable"] is False
    body = add(client, auth_headers, "Client lunch", SAT, is_reimbursable=True)
    assert body["is_reimbursable"] is True
    assert body["reimbursable_set_by"] == "user"


def test_toggle_and_reset_to_automatic(client, auth_headers):
    t = add(client, auth_headers, "Zomato", THU)
    url = f"/api/transactions/{t['id']}"
    body = client.put(url, json={"is_reimbursable": True}, headers=auth_headers).json()
    assert (body["is_reimbursable"], body["reimbursable_set_by"]) == (True, "user")
    body = client.put(url, json={"is_reimbursable": None}, headers=auth_headers).json()  # back to automatic
    assert (body["is_reimbursable"], body["reimbursable_set_by"]) == (False, "rule")


def test_editing_date_reruns_rule_unless_user_decided(client, auth_headers):
    auto = add(client, auth_headers, "Uber", THU)
    body = client.put(f"/api/transactions/{auto['id']}", json={"transaction_date": SAT}, headers=auth_headers).json()
    assert body["is_reimbursable"] is False  # moved to the weekend

    manual = add(client, auth_headers, "Uber", THU, is_reimbursable=True)
    body = client.put(f"/api/transactions/{manual['id']}", json={"transaction_date": SAT}, headers=auth_headers).json()
    assert body["is_reimbursable"] is True  # the user's choice is kept

    body = client.put(f"/api/transactions/{manual['id']}", json={"notes": "x"}, headers=auth_headers).json()
    assert body["is_reimbursable"] is True  # unrelated edits don't touch it


def test_phonepe_import_uses_rule(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.api.imports.today_local", lambda: date(2026, 10, 3))
    weekday_ride = SAMPLE_OCR.replace("BLINK COMMERCE PRIVA...", "UBER INDIA SYSTEMS").replace("3 October", "1 October")
    body = client.post("/api/transactions/import/phonepe", json={"ocr_text": weekday_ride}, headers=auth_headers).json()
    assert body["transaction"]["is_reimbursable"] is True
    assert body["transaction"]["category"] == "Transport"


def test_rule_settings_defaults_and_validation(client, auth_headers):
    rule = client.get("/api/settings/reimbursement", headers=auth_headers).json()
    assert rule["enabled"] is True
    assert {"uber", "ola", "rapido"} <= set(rule["keywords"])
    assert rule["weekdays"] == [0, 1, 2, 3, 4]

    bad = [{"enabled": True, "keywords": [], "weekdays": [0]},
           {"enabled": True, "keywords": ["x"], "weekdays": [0]},
           {"enabled": True, "keywords": ["uber"], "weekdays": [7]}]
    for payload in bad:
        assert client.put("/api/settings/reimbursement", json=payload, headers=auth_headers).status_code == 422

    saved = client.put(
        "/api/settings/reimbursement",
        json={"enabled": True, "keywords": [" Uber ", "uber", "BluSmart"], "weekdays": [5, 0, 0]},
        headers=auth_headers,
    ).json()
    assert saved == {"enabled": True, "keywords": ["uber", "blusmart"], "weekdays": [0, 5]}


def test_changed_rule_applies_to_new_and_reapplies_to_old(client, auth_headers):
    sat_ride = add(client, auth_headers, "Uber", SAT)
    thu_ride = add(client, auth_headers, "Uber", THU)
    manual = add(client, auth_headers, "Rapido", THU, is_reimbursable=True)
    assert (sat_ride["is_reimbursable"], thu_ride["is_reimbursable"]) == (False, True)

    # Now: only weekends count, and only Uber.
    client.put("/api/settings/reimbursement", json={"enabled": True, "keywords": ["uber"], "weekdays": [5, 6]},
               headers=auth_headers)
    assert add(client, auth_headers, "Uber", SUN)["is_reimbursable"] is True  # new ones follow the new rule

    result = client.post("/api/settings/reimbursement/apply", headers=auth_headers).json()
    assert result == {"updated": 2}
    get = lambda t: client.get(f"/api/transactions/{t['id']}", headers=auth_headers).json()["is_reimbursable"]
    assert get(sat_ride) is True
    assert get(thu_ride) is False
    assert get(manual) is True  # manual choice untouched


def test_disabled_rule(client, auth_headers):
    client.put("/api/settings/reimbursement", json={"enabled": False, "keywords": ["uber"], "weekdays": [0, 1, 2, 3, 4]},
               headers=auth_headers)
    assert add(client, auth_headers, "Uber", THU)["is_reimbursable"] is False


def test_rules_are_per_user(client, auth_headers):
    client.put("/api/settings/reimbursement", json={"enabled": False, "keywords": ["uber"], "weekdays": [0]},
               headers=auth_headers)
    other = register(client, email="other@example.com")
    assert add(client, other, "Uber", THU)["is_reimbursable"] is True


def test_filter_by_reimbursable(client, auth_headers):
    add(client, auth_headers, "Uber", THU)
    add(client, auth_headers, "Zomato", THU)
    names = lambda q: [t["merchant_name"] for t in client.get(f"/api/transactions?{q}", headers=auth_headers).json()["items"]]
    assert names("reimbursable=true") == ["Uber"]
    assert names("reimbursable=false") == ["Zomato"]


def test_csv_export(client, auth_headers):
    add(client, auth_headers, "Uber", THU, amount="250.50", notes="Office")
    add(client, auth_headers, "Rapido", FRI, amount="99")
    add(client, auth_headers, "=HYPERLINK(evil)", THU, is_reimbursable=True)
    add(client, auth_headers, "Zomato", THU)

    response = client.get("/api/transactions/export.csv?reimbursable=true&year=2026&month=10", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.lstrip("﻿").strip().splitlines()
    assert lines[0].startswith("Date,Time,Merchant")
    assert any("Uber" in line and "250.50" in line and "Office" in line for line in lines)
    assert not any("Zomato" in line for line in lines)
    assert any("'=HYPERLINK(evil)" in line for line in lines)  # formula injection neutralised
    assert lines[-1].endswith("549.50")  # total row: 250.50 + 99 + 200


def test_csv_export_requires_auth(client):
    assert client.get("/api/transactions/export.csv").status_code == 401
