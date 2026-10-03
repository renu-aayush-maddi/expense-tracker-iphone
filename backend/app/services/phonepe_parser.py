"""Parse the OCR text of a PhonePe "Share Receipt" image.

The iPhone Shortcut sends raw OCR text; ALL interpretation happens here, so if
PhonePe changes its receipt layout only this file needs updating.

How it works
------------
1. Clean the text and split it into non-empty lines.
2. Find label lines ("Paid to", "Amount", "Date", "Transaction ID", "UTR",
   "Debited from", "Message"). The value is either on the same line after the
   label, or on one of the next few lines.
3. Each field has its own validator, so e.g. the amount search never picks up a
   transaction ID, UTR, account number or date.
4. Anything uncertain is reported in `issues` -> the importer asks for review
   instead of saving wrong data.

Typical OCR (₹ is often read as ¥):

    Paid to
    BLINK COMMERCE PRIVA...
    Amount:
    ¥183
    Date:
    3 October 2026
    1:11 PM
    PhonePe Transaction ID:
    T2610031311415776289288
    Debited from:
    XXXXXX096929
    UTR:
    706226593892
    Message:
    UPIIntent
"""

import re
import unicodedata
from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation

from app.services.parsing import ParsedTransaction, ParseResult

MAX_AMOUNT = Decimal("1000000")  # ₹10 lakh – anything bigger is almost certainly an OCR error
EARLIEST_YEAR = 2016  # PhonePe launched in 2016
VALUE_WINDOW = 3  # how many lines after a label we look for its value

# ---------------------------------------------------------------------------
# Label patterns (case-insensitive, tolerant of small OCR mistakes)
# ---------------------------------------------------------------------------
LABELS: dict[str, re.Pattern] = {
    "paid_to": re.compile(r"^(paid|sent|transferred)\s*t[o0]\b[:\s]*", re.I),
    "received_from": re.compile(r"^received\s*fr[o0]m\b[:\s]*", re.I),
    "amount": re.compile(r"^(total\s*)?(amount|amt)(\s*paid)?\b\s*[:.\-]?\s*", re.I),
    "date": re.compile(r"^date(\s*(&|and)\s*time)?\b\s*[:.\-]?\s*", re.I),
    "transaction_id": re.compile(
        r"^(phone\s*pe\s*)?(transaction|txn)\s*[i1l|]\s*d\b\s*[:.\-]?\s*", re.I
    ),
    "debited_from": re.compile(r"^(debited|paid)\s*fr[o0]m\b\s*[:.\-]?\s*", re.I),
    "utr": re.compile(r"^u\s*t\s*r(\s*n[o0]\.?|\s*number)?\b\s*[:.\-]?\s*", re.I),
    "upi_ref": re.compile(r"^upi\s*ref(erence)?\.?(\s*(n[o0]|number|id)\.?)?\s*[:.\-]?\s*", re.I),
    "message": re.compile(r"^(message|note|remarks?)\b\s*[:.\-]?\s*", re.I),
}

# ---------------------------------------------------------------------------
# Value patterns
# ---------------------------------------------------------------------------
# Currency markers including common OCR misreads of ₹ (¥ is the most common).
CURRENCY_MARKER = r"(?:₹|¥|₨|\bRs\.?|\bINR\b)"
# At most 9 integer digits, so long IDs/UTRs/account numbers can never look like an amount.
NUMBER = r"(?:\d{1,3}(?:,\d{2,3})+|\d{1,9})(?:\.\d{1,2})?(?!\d)"
MARKED_AMOUNT_RE = re.compile(CURRENCY_MARKER + r"\s*(" + NUMBER + r")", re.I)
# A labelled amount value may start with a misread currency symbol (Z, %, ?, *, F, R...).
LABELLED_AMOUNT_RE = re.compile(
    r"^(?:" + CURRENCY_MARKER + r"|[^\w\s]|[A-Za-z]{1,2})?\s*(" + NUMBER + r")\s*(?:/-)?$", re.I
)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
DATE_DMY_NAME_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*[-\s]\s*([A-Za-z0-9]{3,9})\.?,?\s*[-\s]\s*(\d{4})\b")
DATE_MDY_NAME_RE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
DATE_NUMERIC_RE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})\b")
TIME_12H_RE = re.compile(r"\b(\d{1,2})\s*[:.]\s*(\d{2})(?:\s*[:.]\s*\d{2})?\s*([AaPp])\.?\s*[Mm]\b")
TIME_24H_RE = re.compile(r"\b([01]?\d|2[0-3])\s*:\s*([0-5]\d)\b")

PHONEPE_TXN_ID_RE = re.compile(r"T\d{15,30}")
MASKED_ACCOUNT_RE = re.compile(r"[Xx×*•·]{2,}[\s\-]*([\dOo]{3,})")
ACCOUNT_FALLBACK_RE = re.compile(r"\b(?:a/?c|acct|account)\s*(?:no\.?|number)?\s*[:\-]?\s*[Xx×*•]*\s*(\d{4,})", re.I)

KNOWN_BANKS = {
    "HDFC": ["hdfc"],
    "ICICI": ["icici"],
    "SBI": ["sbi", "state bank"],
    "Kotak": ["kotak"],
    "Axis": ["axis"],
    "Yes Bank": ["yes bank"],
    "IDFC First": ["idfc"],
    "IndusInd": ["indusind"],
    "PNB": ["pnb", "punjab national"],
    "Bank of Baroda": ["bank of baroda", "bob"],
    "Canara": ["canara"],
    "Union Bank": ["union bank"],
    "Bank of India": ["bank of india"],
    "Federal Bank": ["federal bank"],
    "AU Small Finance": ["au small", "au bank"],
    "RBL": ["rbl"],
    "IDBI": ["idbi"],
    "Indian Bank": ["indian bank"],
    "Paytm Payments Bank": ["paytm payments bank"],
    "Airtel Payments Bank": ["airtel payments bank"],
}

# Messages that PhonePe fills in automatically – not useful as notes.
GENERIC_MESSAGES = {"upiintent", "upi", "payment", "pay", "paymentfromphonepe", "sentusingphonepe", "na", "none"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clean_lines(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text)
    lines = []
    for raw in text.replace("\r", "\n").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _label_of(line: str) -> str | None:
    for name, pattern in LABELS.items():
        if pattern.match(line):
            return name
    return None


def _candidates_after(lines: list[str], label: str) -> list[tuple[int, str]]:
    """For every occurrence of `label`, yield the same-line remainder (if any)
    and the next few lines that aren't themselves labels. Returns (index, text)."""
    pattern = LABELS[label]
    found: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        remainder = line[match.end():].strip(" :.-")
        if remainder:
            found.append((i, remainder))
        for j in range(i + 1, min(i + 1 + VALUE_WINDOW, len(lines))):
            if _label_of(lines[j]):
                continue
            found.append((j, lines[j]))
    return found


def _fix_digits(value: str) -> str:
    """Undo common OCR letter/digit confusions inside things that must be digits."""
    return value.translate(str.maketrans({"O": "0", "o": "0", "D": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"}))


def _to_decimal(number: str) -> Decimal | None:
    try:
        return Decimal(number.replace(",", ""))
    except InvalidOperation:
        return None


def _parse_labelled_amount(value: str) -> Decimal | None:
    # OCR sometimes inserts spaces inside numbers: "1, 250" / "₹ 1 250.00"
    compact = re.sub(r"(?<=\d)[\s]+(?=[\d,.])|(?<=[,.])\s+(?=\d)", "", value.strip())
    match = LABELLED_AMOUNT_RE.match(compact)
    return _to_decimal(match.group(1)) if match else None


def _looks_like_date_or_time(value: str) -> bool:
    return bool(DATE_DMY_NAME_RE.search(value) or DATE_NUMERIC_RE.search(value) or TIME_12H_RE.search(value))


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------
def _extract_merchant(lines: list[str], result: ParseResult) -> None:
    label = "paid_to"
    if not any(LABELS["paid_to"].match(line) for line in lines) and any(
        LABELS["received_from"].match(line) for line in lines
    ):
        label = "received_from"
        result.data.direction = "credit"

    if not any(LABELS[label].match(line) for line in lines):
        return

    upi_id_fallback = None
    for _, value in _candidates_after(lines, label):
        if not re.search(r"[A-Za-z]{2,}", value):
            continue  # needs letters
        if MARKED_AMOUNT_RE.search(value) or _looks_like_date_or_time(value):
            continue
        if "@" in value:  # a UPI ID like name@okaxis – use only if nothing better
            upi_id_fallback = upi_id_fallback or value
            continue
        result.data.merchant_name = _clean_merchant(value, result)
        return
    if upi_id_fallback:
        result.data.merchant_name = upi_id_fallback.strip()


def _clean_merchant(value: str, result: ParseResult) -> str:
    truncated = bool(re.search(r"(\.{2,}|…)\s*$", value))
    name = re.sub(r"(\.{2,}|…)\s*$", "", value)
    name = re.sub(r"\s+", " ", name).strip(" -:,.'\"")
    if truncated:
        result.warnings.append("Merchant name looks truncated on the receipt.")
    return name[:255]


def _extract_amount(lines: list[str], skip_lines: set[int], result: ParseResult) -> None:
    # 1) Contextual: the value right after an "Amount" label.
    for index, value in _candidates_after(lines, "amount"):
        if index in skip_lines:
            continue
        amount = _parse_labelled_amount(value)
        if amount is not None:
            result.data.amount = amount
            break

    # 2) Otherwise: numbers with an explicit currency marker (₹ ¥ Rs INR), on lines
    #    that are not the value of an ID / UTR / account / date label.
    if result.data.amount is None:
        marked = set()
        for i, line in enumerate(lines):
            if i in skip_lines:
                continue
            for match in MARKED_AMOUNT_RE.finditer(line):
                value = _to_decimal(match.group(1))
                if value is not None:
                    marked.add(value)
        if len(marked) == 1:
            result.data.amount = marked.pop()
            result.warnings.append("Amount was found without an 'Amount' label.")
        elif len(marked) > 1:
            result.issues.append(
                "Several different amounts were found: " + ", ".join(str(a) for a in sorted(marked)) + "."
            )
            return

    amount = result.data.amount
    if amount is None:
        result.issues.append("Amount could not be found.")
    elif amount <= 0:
        result.issues.append("Amount must be greater than zero.")
        result.data.amount = None
    elif amount > MAX_AMOUNT:
        result.issues.append(f"Amount {amount} is unusually large; please confirm it.")
    else:
        result.data.amount = amount.quantize(Decimal("0.01"))


def _parse_date(value: str) -> date | None:
    value = re.sub(r"(?<=\d)[Oo](?=\d)", "0", value)

    for match in DATE_DMY_NAME_RE.finditer(value):
        day, month_word, year = match.groups()
        month = _month_from_word(month_word)
        if month:
            return _safe_date(int(year), month, int(day))
    for match in DATE_MDY_NAME_RE.finditer(value):
        month_word, day, year = match.groups()
        month = _month_from_word(month_word)
        if month:
            return _safe_date(int(year), month, int(day))
    for match in DATE_NUMERIC_RE.finditer(value):
        day, month, year = (int(g) for g in match.groups())  # Indian format: DD/MM/YYYY
        if year < 100:
            year += 2000
        return _safe_date(year, month, day)
    return None


def _month_from_word(word: str) -> int | None:
    word = word.lower().replace("0", "o")
    return MONTHS.get(word[:3]) if word[:3].isalpha() else None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_time(value: str) -> time | None:
    match = TIME_12H_RE.search(value)
    if match:
        hour, minute, meridiem = int(match.group(1)), int(match.group(2)), match.group(3).lower()
        if 1 <= hour <= 12 and minute < 60:
            if meridiem == "p" and hour != 12:
                hour += 12
            if meridiem == "a" and hour == 12:
                hour = 0
            return time(hour, minute)
    match = TIME_24H_RE.search(value)
    if match:
        return time(int(match.group(1)), int(match.group(2)))
    return None


def _extract_date_time(lines: list[str], result: ParseResult, today: date) -> set[int]:
    used: set[int] = set()
    candidates = _candidates_after(lines, "date")
    # If there's no "Date" label, search every line.
    search_space = candidates or list(enumerate(lines))

    for index, value in search_space:
        if result.data.transaction_date is None:
            parsed = _parse_date(value)
            if parsed:
                result.data.transaction_date = parsed
                used.add(index)
        if result.data.transaction_time is None:
            parsed_time = _parse_time(value)
            if parsed_time:
                result.data.transaction_time = parsed_time
                used.add(index)

    if result.data.transaction_time is None:
        for i, line in enumerate(lines):  # time may live elsewhere, e.g. "on 3 Oct, 1:11 pm"
            if TIME_12H_RE.search(line):
                result.data.transaction_time = _parse_time(line)
                used.add(i)
                break

    txn_date = result.data.transaction_date
    if txn_date is None:
        result.issues.append("Transaction date could not be found.")
    elif txn_date > today + timedelta(days=1):
        result.issues.append(f"Transaction date {txn_date.isoformat()} is in the future.")
    elif txn_date.year < EARLIEST_YEAR:
        result.issues.append(f"Transaction date {txn_date.isoformat()} looks wrong.")
    if result.data.transaction_time is None:
        result.warnings.append("Transaction time could not be found.")
    return used


def _extract_transaction_id(lines: list[str], result: ParseResult) -> set[int]:
    for index, value in _candidates_after(lines, "transaction_id"):
        compact = re.sub(r"\s+", "", value)
        if not compact:
            continue
        candidate = compact[0].upper() + _fix_digits(compact[1:])
        # OCR sometimes reads the leading "T" as "7" or "1".
        if candidate[0] in "71" and candidate.isdigit() and 21 <= len(candidate) <= 24:
            candidate = "T" + candidate[1:]
            result.warnings.append("Transaction ID started with a digit; corrected the leading 'T'.")
        if PHONEPE_TXN_ID_RE.fullmatch(candidate):
            result.data.phonepe_transaction_id = candidate
            return {index}

    # No label: look for a T + many digits token anywhere.
    for i, line in enumerate(lines):
        match = PHONEPE_TXN_ID_RE.search(re.sub(r"\s+", "", line))
        if match:
            result.data.phonepe_transaction_id = match.group(0)
            return {i}
    return set()


def _looks_like_reference(value: str) -> bool:
    """UPI UTRs are 12 digits; allow 10-22 digits, or bank-style alphanumeric refs
    that are mostly digits. Masked account numbers (XXXX1234) and PhonePe
    transaction IDs (T + digits) are rejected."""
    if re.fullmatch(r"\d{10,22}", value):
        return True
    if re.search(r"X{3,}", value) or PHONEPE_TXN_ID_RE.fullmatch(value):
        return False
    return bool(re.fullmatch(r"[A-Z0-9]{12,22}", value)) and sum(c.isdigit() for c in value) >= 8


def _extract_reference(lines: list[str], label: str) -> tuple[str | None, set[int]]:
    for index, value in _candidates_after(lines, label):
        compact = re.sub(r"[\s\-]", "", value).upper()
        if not re.search(r"X{3,}", compact):
            compact = _fix_digits(compact)
        if _looks_like_reference(compact):
            return compact, {index}
    return None, set()


def _extract_account(lines: list[str], result: ParseResult) -> set[int]:
    candidates = _candidates_after(lines, "debited_from")
    for index, value in candidates:
        match = MASKED_ACCOUNT_RE.search(value)
        if match:
            digits = _fix_digits(match.group(1))
            if digits.isdigit() and len(digits) >= 4:
                result.data.account_last4 = digits[-4:]
                # A bank name, if shown, sits right next to the account number.
                result.data.bank = _detect_bank([v for i, v in candidates if i <= index + 1])
                return {index}

    for i, line in enumerate(lines):  # no label: any masked number / "A/c XXXX1234"
        match = MASKED_ACCOUNT_RE.search(line) or ACCOUNT_FALLBACK_RE.search(line)
        if match:
            digits = _fix_digits(match.group(1))
            if digits.isdigit() and len(digits) >= 4:
                result.data.account_last4 = digits[-4:]
                return {i}

    result.data.bank = _detect_bank([v for _, v in candidates[:2]])
    result.warnings.append("Account number could not be found.")
    return set()


def _detect_bank(values: list[str]) -> str | None:
    text = " " + " ".join(values).lower() + " "
    for bank, keywords in KNOWN_BANKS.items():
        for keyword in keywords:
            if re.search(r"\b" + re.escape(keyword) + r"\b", text):
                return bank
    return None


def _extract_message(lines: list[str], result: ParseResult) -> None:
    for _, value in _candidates_after(lines, "message"):
        result.data.message = value[:500]
        return


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def parse_phonepe_receipt(ocr_text: str, today: date | None = None) -> ParseResult:
    """Turn raw OCR text from a PhonePe receipt into a ParseResult."""
    today = today or date.today()
    result = ParseResult(data=ParsedTransaction(payment_method="UPI"))
    lines = _clean_lines(ocr_text or "")
    if not lines:
        result.issues.append("The receipt text is empty.")
        return result

    # Extract identifiers first and remember their lines, so the amount search
    # never mistakes an ID, UTR, account number or date for the amount.
    skip: set[int] = set()
    skip |= _extract_transaction_id(lines, result)

    utr, utr_lines = _extract_reference(lines, "utr")
    upi_ref, upi_lines = _extract_reference(lines, "upi_ref")
    result.data.utr = utr or upi_ref
    result.data.upi_reference = upi_ref
    skip |= utr_lines | upi_lines

    skip |= _extract_account(lines, result)
    skip |= _extract_date_time(lines, result, today)

    _extract_merchant(lines, result)
    _extract_amount(lines, skip, result)
    _extract_message(lines, result)

    if result.data.direction == "credit":
        result.issues.append("This receipt is for money received, not an expense.")
    if not result.data.merchant_name:
        result.issues.append("Merchant could not be found.")
    if not result.data.phonepe_transaction_id and not result.data.utr:
        result.issues.append("No PhonePe transaction ID or UTR found, so duplicates can't be detected reliably.")
    return result


def useful_message(message: str | None) -> str | None:
    """Return the receipt message if it's something the user typed, else None."""
    if not message:
        return None
    if re.sub(r"[^a-z]", "", message.lower()) in GENERIC_MESSAGES:
        return None
    return message
