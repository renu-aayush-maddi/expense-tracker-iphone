import pytest

from app.services.categorizer import categorize


@pytest.mark.parametrize(
    "merchant, category",
    [
        ("Zomato", "Food"),
        ("SWIGGY LIMITED", "Food"),
        ("Blinkit", "Groceries"),
        ("BLINK COMMERCE PRIVA", "Groceries"),
        ("Zepto Marketplace", "Groceries"),
        ("Uber India", "Transport"),
        ("Rapido", "Transport"),
        ("Netflix", "Subscriptions"),
        ("Amazon", "Shopping"),
        ("Amazon Prime", "Subscriptions"),  # longest keyword wins
        ("IRCTC", "Travel"),
        ("Apollo Pharmacy", "Health"),
        ("Coca Cola", "Other"),  # "ola" must not match inside "cola"
        ("", "Other"),
        (None, "Other"),
    ],
)
def test_categorize(merchant, category):
    assert categorize(merchant) == category
