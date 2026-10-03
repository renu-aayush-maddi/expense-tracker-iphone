"""Unit tests for the PhonePe OCR parser (no database needed)."""

from datetime import date, time
from decimal import Decimal

import pytest

from app.services.phonepe_parser import parse_phonepe_receipt, useful_message
from tests.conftest import SAMPLE_OCR

TODAY = date(2026, 10, 3)


def parse(text):
    return parse_phonepe_receipt(text, today=TODAY)


# ---------------------------------------------------------------- sample receipt
def test_sample_receipt_all_fields():
    result = parse(SAMPLE_OCR)
    d = result.data
    assert d.merchant_name.startswith("BLINK COMMERCE")
    assert d.amount == Decimal("183.00")
    assert d.transaction_date == date(2026, 10, 3)
    assert d.transaction_time == time(13, 11)
    assert d.phonepe_transaction_id == "T2610031311415776289288"
    assert d.utr == "706226593892"
    assert d.account_last4 == "6929"
    assert d.payment_method == "UPI"
    assert d.message == "UPIIntent"
    assert result.issues == []
    assert not result.needs_review


def test_truncated_merchant_is_cleaned_and_flagged():
    result = parse(SAMPLE_OCR)
    assert result.data.merchant_name == "BLINK COMMERCE PRIVA"
    assert any("truncated" in w for w in result.warnings)


# ---------------------------------------------------------------- amount
@pytest.mark.parametrize(
    "amount_text, expected",
    [
        ("₹183", "183.00"),
        ("¥183", "183.00"),
        ("Rs 183", "183.00"),
        ("Rs. 183", "183.00"),
        ("INR 183", "183.00"),
        ("₹ 183", "183.00"),
        ("₹1,250.50", "1250.50"),
        ("₹1,25,000", "125000.00"),
        ("₹ 1, 250", "1250.00"),
        ("Z183", "183.00"),  # ₹ misread as a letter
        ("183", "183.00"),
    ],
)
def test_amount_variants(amount_text, expected):
    text = SAMPLE_OCR.replace("¥183", amount_text)
    assert parse(text).data.amount == Decimal(expected)


def test_amount_on_same_line_as_label():
    text = SAMPLE_OCR.replace("Amount:\n¥183", "Amount: ₹99.50")
    assert parse(text).data.amount == Decimal("99.50")


def test_amount_is_contextual_not_first_number():
    """IDs, UTR and account numbers come first – the amount must still be 183."""
    text = """PhonePe Transaction ID:
T2610031311415776289288

UTR:
706226593892

Debited from:
XXXXXX096929

¥183
"""
    result = parse(text)
    assert result.data.amount == Decimal("183.00")
    assert result.data.phonepe_transaction_id == "T2610031311415776289288"
    assert result.data.utr == "706226593892"
    assert result.data.account_last4 == "6929"


def test_amount_not_taken_from_date_or_time():
    text = SAMPLE_OCR.replace("Amount:\n¥183\n", "")
    result = parse(text)
    assert result.data.amount is None
    assert any("Amount" in issue for issue in result.issues)


def test_conflicting_unlabelled_amounts_need_review():
    text = SAMPLE_OCR.replace("Amount:\n¥183", "₹183\n₹1,830")
    result = parse(text)
    assert result.data.amount is None
    assert result.needs_review


def test_huge_amount_needs_review():
    text = SAMPLE_OCR.replace("¥183", "₹50,00,000")
    assert parse(text).needs_review


# ---------------------------------------------------------------- transaction ID
def test_transaction_id_with_spaces_and_ocr_mistakes():
    text = SAMPLE_OCR.replace("T2610031311415776289288", "T 2610O313 1141577 6289288")
    assert parse(text).data.phonepe_transaction_id == "T2610031311415776289288"


def test_transaction_id_leading_t_misread_as_7():
    text = SAMPLE_OCR.replace("T2610031311415776289288", "72610031311415776289288")
    assert parse(text).data.phonepe_transaction_id == "T2610031311415776289288"


def test_transaction_id_on_same_line():
    text = SAMPLE_OCR.replace("PhonePe Transaction ID:\nT2610031311415776289288", "Transaction ID: T2610031311415776289288")
    assert parse(text).data.phonepe_transaction_id == "T2610031311415776289288"


# ---------------------------------------------------------------- UTR
def test_utr_on_same_line():
    text = SAMPLE_OCR.replace("UTR:\n706226593892", "UTR: 706226593892")
    assert parse(text).data.utr == "706226593892"


def test_utr_with_spaces():
    text = SAMPLE_OCR.replace("706226593892", "7062 2659 3892")
    assert parse(text).data.utr == "706226593892"


def test_utr_label_does_not_steal_account_number():
    text = SAMPLE_OCR.replace("UTR:\n706226593892", "UTR:")
    text = text.replace("Message:\nUPIIntent", "XXXXXX096929")
    result = parse(text)
    assert result.data.utr is None


def test_upi_ref_used_when_no_utr():
    text = SAMPLE_OCR.replace("UTR:\n706226593892", "UPI Ref. No:\n706226593892")
    result = parse(text)
    assert result.data.upi_reference == "706226593892"
    assert result.data.utr == "706226593892"


# ---------------------------------------------------------------- account
@pytest.mark.parametrize("account", ["XXXXXX096929", "xxxx 6929", "XX XX 096929", "****6929", "XXXXXX09692O"])
def test_account_last4_variants(account):
    expected = "6929" if not account.endswith("O") else "6920"
    text = SAMPLE_OCR.replace("XXXXXX096929", account)
    assert parse(text).data.account_last4 == expected


def test_bank_name_next_to_account():
    text = SAMPLE_OCR.replace("XXXXXX096929", "Kotak Mahindra Bank\nXXXXXX096929")
    result = parse(text)
    assert result.data.bank == "Kotak"
    assert result.data.account_last4 == "6929"


# ---------------------------------------------------------------- date & time
@pytest.mark.parametrize(
    "date_text, expected_date, expected_time",
    [
        ("3 October 2026\n1:11 PM", date(2026, 10, 3), time(13, 11)),
        ("03 Oct 2026, 01:11 pm", date(2026, 10, 3), time(13, 11)),
        ("3 Oct 2026 at 12:05 AM", date(2026, 10, 3), time(0, 5)),
        ("Oct 3, 2026\n9:45 AM", date(2026, 10, 3), time(9, 45)),
        ("03/10/2026 21:30", date(2026, 10, 3), time(21, 30)),
        ("3 0ctober 2O26\n1:11 PM", date(2026, 10, 3), time(13, 11)),
    ],
)
def test_date_and_time_variants(date_text, expected_date, expected_time):
    text = SAMPLE_OCR.replace("3 October 2026\n1:11 PM", date_text)
    result = parse(text)
    assert result.data.transaction_date == expected_date
    assert result.data.transaction_time == expected_time


def test_future_date_needs_review():
    text = SAMPLE_OCR.replace("3 October 2026", "3 October 2027")
    result = parse(text)
    assert result.needs_review
    assert any("future" in issue for issue in result.issues)


def test_missing_time_is_only_a_warning():
    text = SAMPLE_OCR.replace("1:11 PM\n", "")
    result = parse(text)
    assert result.data.transaction_time is None
    assert not result.needs_review


# ---------------------------------------------------------------- noise & layout
def test_tolerates_noise_and_extra_lines():
    text = (
        "9:41 ⚫ 5G 87%\nTransaction Successful\n"
        + SAMPLE_OCR.replace("Paid to\n", "Paid to\n\n  ")
        + "\nPowered by UPI\nContact PhonePe Support\n"
    )
    result = parse(text)
    assert result.data.amount == Decimal("183.00")
    assert result.data.merchant_name.startswith("BLINK COMMERCE")
    assert result.data.transaction_time == time(13, 11)


def test_merchant_on_same_line_as_label():
    text = SAMPLE_OCR.replace("Paid to\nBLINK COMMERCE PRIVA...", "Paid to BLINK COMMERCE PRIVATE LIMITED")
    assert parse(text).data.merchant_name == "BLINK COMMERCE PRIVATE LIMITED"


def test_upi_id_used_as_merchant_fallback():
    text = SAMPLE_OCR.replace("BLINK COMMERCE PRIVA...", "rahul.sharma@okaxis")
    assert parse(text).data.merchant_name == "rahul.sharma@okaxis"


def test_windows_line_endings():
    assert parse(SAMPLE_OCR.replace("\n", "\r\n")).data.amount == Decimal("183.00")


# ---------------------------------------------------------------- invalid / review
def test_empty_ocr_is_invalid():
    result = parse("   \n  ")
    assert result.is_empty
    assert result.needs_review


def test_garbage_ocr_is_invalid():
    result = parse("Hello world\nThis is a photo of a cat")
    assert result.is_empty


def test_missing_merchant_needs_review():
    text = SAMPLE_OCR.replace("Paid to\nBLINK COMMERCE PRIVA...\n", "")
    result = parse(text)
    assert result.needs_review
    assert any("Merchant" in issue for issue in result.issues)


def test_missing_identifiers_needs_review():
    text = SAMPLE_OCR.replace("PhonePe Transaction ID:\nT2610031311415776289288\n", "").replace(
        "UTR:\n706226593892\n", ""
    )
    result = parse(text)
    assert result.needs_review
    assert any("duplicates" in issue for issue in result.issues)


def test_money_received_needs_review():
    text = SAMPLE_OCR.replace("Paid to", "Received from")
    result = parse(text)
    assert result.data.direction == "credit"
    assert result.needs_review


def test_useful_message_filters_generic_values():
    assert useful_message("UPIIntent") is None
    assert useful_message("Payment from PhonePe") is None
    assert useful_message("Rent for October") == "Rent for October"
