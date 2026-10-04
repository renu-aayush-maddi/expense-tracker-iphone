"""Parse the OCR text of a PhonePe "Share Receipt" image.

The iPhone Shortcut sends raw OCR text; ALL interpretation happens here, so if
PhonePe changes its receipt layout only this file needs updating.

How it works
------------
1. Clean the text and split it into non-empty lines.
2. Extract the identifiers first (transaction ID, UTR, account, date/time).
   The value of a label ("UTR:") is on the same line or one of the next lines.
3. Build a *masked* copy of the text where every identifier, date and time is
   blanked out. The amount is searched only in the masked text, so it can never
   be confused with an ID, UTR, account number or date – even when they share
   a line (e.g. "XXXXXX6929   ¥183").
4. Amount, in order of confidence:
      a) the value after an "Amount" label
      b) a number with a currency marker – ₹ and its usual OCR misreads
         (¥ 円 € £ $ Rs INR)
      c) a line that is only a number, possibly with one stray symbol/letter
         where ₹ was misread ("Z183", "%183", "183")
   If a level finds several different amounts, nothing is guessed.
5. `validate_result` turns anything uncertain into review issues.

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
"""

import re
import unicodedata
from datetime import date, time
from decimal import Decimal, InvalidOperation

from app.services.parsing import MAX_AMOUNT, ParsedTransaction, ParseResult, validate_result

VALUE_WINDOW = 3  # how many lines after a label we look for its value

# ---------------------------------------------------------------------------
# Label patterns (case-insensitive, tolerant of small OCR mistakes)
# ---------------------------------------------------------------------------
LABELS: dict[str, re.Pattern] = {
    "paid_to": re.compile(r"^(paid|sent|transferred)\s*t[o0]\b[:\s]*", re.I),
    "received_from": re.compile(r"^received\s*fr[o0]m\b[:\s]*", re.I),
    "amount": re.compile(r"^(total\s*)?(amount|amt)(\s*paid)?\b\s*[:.\-]?\s*", re.I),
    "date": re.compile(r"^date(\s*(&|and)\s*time)?\b\s*[:.\-]?\s*", re.I),
    "transaction_id": re.compile(r"^(phone\s*pe\s*)?(transaction|txn)\s*[i1l|]\s*d\b\s*[:.\-]?\s*", re.I),
    "debited_from": re.compile(r"^(debited|paid)\s*fr[o0]m\b\s*[:.\-]?\s*", re.I),
    "utr": re.compile(r"^u\s*t\s*r(\s*n[o0]\.?|\s*number)?\b\s*[:.\-]?\s*", re.I),
    "upi_ref": re.compile(r"^upi\s*ref(erence)?\.?(\s*(n[o0]|number|id)\.?)?\s*[:.\-]?\s*", re.I),
    "message": re.compile(r"^(message|note|remarks?)\b\s*[:.\-]?\s*", re.I),
}

# ---------------------------------------------------------------------------
# Value patterns
# ---------------------------------------------------------------------------
# ₹ plus the symbols OCR commonly turns it into ("□" = server OCR's "unknown glyph" box).
CURRENCY_MARKER = r"(?:₹|¥|円|₨|€|£|□|\$|\bRs\.?|\bRe\.?|\bINR\b)"
# At most 9 integer digits, so long IDs/UTRs/account numbers can never look like an amount.
NUMBER = r"(?:\d{1,3}(?:,\d{2,3})+|\d{1,9})(?:\.\d{1,2})?(?!\d)"
MARKED_AMOUNT_RE = re.compile(CURRENCY_MARKER + r"\s*(" + NUMBER + r")", re.I)
# A value that is just an amount, maybe with a misread ₹ in front (Z, %, ?, *, F, R...).
AMOUNT_ONLY_RE = re.compile(
    r"^(?P<prefix>" + CURRENCY_MARKER + r"|[^\w\s]{1,2}|[A-Za-z]{1,2})?\s*(?P<number>" + NUMBER + r")\s*(?:/-)?$", re.I
)
# PhonePe prints amounts with Indian digit grouping: 183 / 2,183 / 21,420.25 / 1,25,000
INDIAN_FORMAT_RE = re.compile(r"^(?:[1-9]\d{0,2}|[1-9]\d?(?:,\d{2})*,\d{3})(?:\.\d{1,2})?$")

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
# A UPI handle: "name@bank", or a lowercase handle whose "@bank" part was cut off ("uber187204.rzp").
UPI_HANDLE_RE = re.compile(r"^(?:[\w.\-]+@[\w.\-]+|(?=[a-z0-9._\-]*[\d.])[a-z0-9._\-]{6,})$")

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
    # NFKC also turns the full-width yen "￥" into a plain "¥".
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
    """For every occurrence of `label`, return the same-line remainder (if any)
    and the next few lines that aren't themselves labels, as (index, text)."""
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


def _match_amount_only(value: str) -> re.Match | None:
    # OCR sometimes inserts spaces inside numbers: "1, 250" / "₹ 1 250.00"
    compact = re.sub(r"(?<=\d)\s+(?=[\d,.])|(?<=[,.])\s+(?=\d)", "", value.strip())
    return AMOUNT_ONLY_RE.match(compact)


def _parse_amount_only(value: str) -> Decimal | None:
    """'¥183', 'Z 1,250.50', '183' -> Decimal; anything else -> None."""
    match = _match_amount_only(value)
    return _to_decimal(match.group("number")) if match else None


def _amount_readings(value: str) -> set[Decimal]:
    """All plausible amounts for an amount-only value.

    PhonePe always prints ₹ before the amount. If OCR shows a symbol or letter
    there ('¥183', 'Z183') that's the ₹ and the number is unambiguous. If OCR
    shows NO symbol, the ₹ was most likely misread as a leading '2'. Indian
    digit grouping usually tells which reading is right:

        '2183'      -> {183}              (₹2,183 would be printed with a comma)
        '212,420'   -> {12420}            ('212,420' isn't valid Indian grouping)
        '2,183'     -> {2183}             (',183' can't be an amount)
        '21,420.25' -> {1420.25, 21420.25}  genuinely ambiguous -> ask the user
    """
    match = _match_amount_only(value)
    if not match:
        return set()
    number = match.group("number")
    literal = _to_decimal(number)
    if match.group("prefix") or not number.startswith("2") or len(number) < 2 or number[1] in ",.":
        return {literal}

    stripped = number[1:]
    as_is_ok = bool(INDIAN_FORMAT_RE.match(number))
    stripped_ok = bool(INDIAN_FORMAT_RE.match(stripped))
    readings = set()
    if as_is_ok:
        readings.add(literal)
    if stripped_ok:
        readings.add(_to_decimal(stripped))
    readings = readings or {literal, _to_decimal(stripped)}  # neither fits (commas lost): ambiguous
    # Prefer readings under the sanity limit: '22,15,000' -> ₹2,15,000, not ₹22,15,000.
    plausible = {r for r in readings if r <= MAX_AMOUNT}
    return plausible or readings


def _looks_like_date_or_time(value: str) -> bool:
    return bool(DATE_DMY_NAME_RE.search(value) or DATE_NUMERIC_RE.search(value) or TIME_12H_RE.search(value))


def _spaced_pattern(identifier: str) -> str:
    """'7062265' -> regex that also matches '706 2265' (OCR inserts spaces)."""
    return r"\s*".join(re.escape(ch) for ch in identifier)


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------
def _extract_transaction_id(lines: list[str], result: ParseResult) -> None:
    for _, value in _candidates_after(lines, "transaction_id"):
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
            return

    for line in lines:  # no label: look for a T + many digits token anywhere
        match = PHONEPE_TXN_ID_RE.search(re.sub(r"\s+", "", line))
        if match:
            result.data.phonepe_transaction_id = match.group(0)
            return


def _looks_like_reference(value: str) -> bool:
    """UPI UTRs are 12 digits; allow 10-22 digits, or bank-style alphanumeric refs
    that are mostly digits. Masked account numbers (XXXX1234) and PhonePe
    transaction IDs (T + digits) are rejected."""
    if re.fullmatch(r"\d{10,22}", value):
        return True
    if re.search(r"X{3,}", value) or PHONEPE_TXN_ID_RE.fullmatch(value):
        return False
    return bool(re.fullmatch(r"[A-Z0-9]{12,22}", value)) and sum(c.isdigit() for c in value) >= 8


def _extract_reference(lines: list[str], label: str) -> str | None:
    for _, value in _candidates_after(lines, label):
        compact = re.sub(r"[\s\-]", "", value).upper()
        if not re.search(r"X{3,}", compact):
            compact = _fix_digits(compact)
        if _looks_like_reference(compact):
            return compact
    return None


def _extract_account(lines: list[str], result: ParseResult) -> None:
    candidates = _candidates_after(lines, "debited_from")
    for index, value in candidates:
        match = MASKED_ACCOUNT_RE.search(value)
        if match:
            digits = _fix_digits(match.group(1))
            if digits.isdigit() and len(digits) >= 4:
                result.data.account_last4 = digits[-4:]
                # A bank name, if shown, sits right next to the account number.
                result.data.bank = _detect_bank([v for i, v in candidates if i <= index + 1])
                return

    for line in lines:  # no label: any masked number / "A/c XXXX1234"
        match = MASKED_ACCOUNT_RE.search(line) or ACCOUNT_FALLBACK_RE.search(line)
        if match:
            digits = _fix_digits(match.group(1))
            if digits.isdigit() and len(digits) >= 4:
                result.data.account_last4 = digits[-4:]
                return

    result.data.bank = _detect_bank([v for _, v in candidates[:2]])
    result.warnings.append("Account number could not be found.")


def _detect_bank(values: list[str]) -> str | None:
    text = " " + " ".join(values).lower() + " "
    for bank, keywords in KNOWN_BANKS.items():
        for keyword in keywords:
            if re.search(r"\b" + re.escape(keyword) + r"\b", text):
                return bank
    return None


# ---------------------------------------------------------------------------
# Date & time
# ---------------------------------------------------------------------------
def _month_from_word(word: str) -> int | None:
    word = word.lower().replace("0", "o")
    return MONTHS.get(word[:3]) if word[:3].isalpha() else None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


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


def _extract_date_time(lines: list[str], result: ParseResult) -> None:
    # Prefer the "Date" label's value; without a label, search every line.
    search_space = [v for _, v in _candidates_after(lines, "date")] or lines

    for value in search_space:
        if result.data.transaction_date is None:
            result.data.transaction_date = _parse_date(value)
        if result.data.transaction_time is None:
            result.data.transaction_time = _parse_time(value)

    if result.data.transaction_time is None:
        for line in lines:  # time may live elsewhere, e.g. "1:11 pm on 3 Oct 2026"
            if TIME_12H_RE.search(line):
                result.data.transaction_time = _parse_time(line)
                break

    if result.data.transaction_time is None:
        result.warnings.append("Transaction time could not be found.")


# ---------------------------------------------------------------------------
# Merchant
# ---------------------------------------------------------------------------
def _extract_merchant(lines: list[str], result: ParseResult) -> None:
    label = "paid_to"
    has_paid_to = any(LABELS["paid_to"].match(line) for line in lines)
    if not has_paid_to and any(LABELS["received_from"].match(line) for line in lines):
        label = "received_from"
        result.data.direction = "credit"
    elif not has_paid_to:
        return

    for _, value in _candidates_after(lines, label):
        if not re.search(r"[A-Za-z]{2,}", value):
            continue  # needs letters
        if _looks_like_date_or_time(value) or _parse_amount_only(value) is not None:
            continue
        name, handle = _split_upi_handle(value)
        if handle and not result.data.upi_id:
            result.data.upi_id = handle
        if not name:  # the line was only a UPI handle; a real name may follow
            continue
        result.data.merchant_name = _clean_merchant(name, result)
        break

    if not result.data.merchant_name and result.data.upi_id:
        result.data.merchant_name = result.data.upi_id  # person-to-person payment: the handle is all we have


def _split_upi_handle(value: str) -> tuple[str, str | None]:
    """'BigBasket bigbasket@payuaxis' -> ('BigBasket', 'bigbasket@payuaxis')."""
    # Drop a trailing amount OCR may have glued onto the line ("BigBasket ¥183").
    value = MARKED_AMOUNT_RE.sub("", value).strip()
    tokens = value.split()
    handle = None
    while tokens and UPI_HANDLE_RE.match(tokens[-1]) and (len(tokens) > 1 or "@" in tokens[-1]):
        handle = tokens.pop()
    return " ".join(tokens), handle


def _clean_merchant(value: str, result: ParseResult) -> str:
    truncated = bool(re.search(r"(\.{2,}|…)\s*$", value))
    name = re.sub(r"(\.{2,}|…)\s*$", "", value)
    name = re.sub(r"\s+", " ", name).strip(" -:,.'\"")
    if truncated:
        result.warnings.append("Merchant name looks truncated on the receipt.")
    return name[:255]


# ---------------------------------------------------------------------------
# Amount
# ---------------------------------------------------------------------------
def _mask_lines(lines: list[str], data: ParsedTransaction) -> list[str]:
    """Blank out identifiers, dates and times so only amount-like numbers remain."""
    known = [x for x in (data.phonepe_transaction_id, data.utr, data.upi_reference) if x]
    masked = []
    for line in lines:
        m = line
        for identifier in known:
            m = re.sub(_spaced_pattern(identifier), " ", m, flags=re.I)
        m = re.sub(r"\bT\s*\d[\d\s]{14,}", " ", m)  # any other PhonePe-style ID
        m = MASKED_ACCOUNT_RE.sub(" ", m)  # XXXXXX096929
        m = re.sub(r"\d{10,}", " ", m)  # UTRs, phone numbers, other long references
        for pattern in (DATE_DMY_NAME_RE, DATE_MDY_NAME_RE, DATE_NUMERIC_RE, TIME_12H_RE, TIME_24H_RE):
            m = pattern.sub(" ", m)
        masked.append(re.sub(r"\s+", " ", m).strip())
    return masked


def _pick(candidates: set[Decimal], result: ParseResult, warning: str | None = None) -> bool:
    """Accept a single distinct candidate; record ambiguity if there are several."""
    if len(candidates) == 1:
        result.data.amount = candidates.pop().quantize(Decimal("0.01"))
        if warning:
            result.warnings.append(warning)
        return True
    if len(candidates) > 1:
        result.amount_candidates = sorted(candidates)
        return True  # stop searching: don't guess between them
    return False


def _combine_readings(readings: list[set[Decimal]]) -> tuple[set[Decimal], bool]:
    """The same amount usually appears twice (merchant row and account row).
    Keep the readings every occurrence agrees on. Returns (candidates, rupee_ambiguous)."""
    if not readings:
        return set(), False
    common = set.intersection(*readings)
    candidates = common or set.union(*readings)
    rupee_ambiguous = bool(common) and len(common) > 1  # one number, two readings (₹ vs '2')
    return candidates, rupee_ambiguous


def _extract_amount(lines: list[str], result: ParseResult) -> None:
    masked = _mask_lines(lines, result.data)

    # a) Value right after an "Amount" label.
    for _, value in _candidates_after(masked, "amount"):
        readings = {r for r in _amount_readings(value) if r > 0}
        if readings:
            candidates, rupee_ambiguous = _combine_readings([readings])
            result.rupee_ambiguous = rupee_ambiguous
            _pick(candidates, result)
            return

    # b) Numbers with an explicit currency marker (₹ and its OCR look-alikes).
    marked = set()
    for line in masked:
        for match in MARKED_AMOUNT_RE.finditer(line):
            value = _to_decimal(match.group(1))
            if value:
                marked.add(value)
    if _pick(marked, result, "Amount was found without an 'Amount' label."):
        return

    # c) Lines that contain only a number, maybe with a misread ₹ in front.
    readings = []
    for line in masked:
        if _label_of(line):
            continue
        options = {r for r in _amount_readings(line) if r > 0}
        if not options:
            continue
        literal = _parse_amount_only(line)
        if literal < 10 and literal == literal.to_integral() and len(options) == 1:
            continue  # a lone digit is a logo/icon letter, not an amount ("Paid to / 7 / Delhivery")
        if 2000 <= literal <= 2100 and literal == literal.to_integral():
            continue  # a lone year
        readings.append(options)
    candidates, rupee_ambiguous = _combine_readings(readings)
    result.rupee_ambiguous = rupee_ambiguous
    _pick(candidates, result, "The currency symbol was unreadable; amount taken from a number-only line.")


def _extract_message(lines: list[str], result: ParseResult) -> None:
    for _, value in _candidates_after(lines, "message"):
        result.data.message = value[:500]
        return


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def parse_phonepe_receipt(ocr_text: str, today: date | None = None) -> ParseResult:
    """Turn raw OCR text from a PhonePe receipt into a validated ParseResult."""
    today = today or date.today()
    result = ParseResult(data=ParsedTransaction(payment_method="UPI"))
    lines = _clean_lines(ocr_text or "")
    if not lines:
        result.empty_text = True
        return validate_result(result, today)

    _extract_transaction_id(lines, result)
    upi_ref = _extract_reference(lines, "upi_ref")
    result.data.utr = _extract_reference(lines, "utr") or upi_ref
    result.data.upi_reference = upi_ref
    _extract_account(lines, result)
    _extract_date_time(lines, result)
    _extract_merchant(lines, result)
    _extract_amount(lines, result)  # last: needs the identifiers to mask them
    _extract_message(lines, result)

    return validate_result(result, today)


def useful_message(message: str | None) -> str | None:
    """Return the receipt message if it's something the user typed, else None."""
    if not message:
        return None
    if re.sub(r"[^a-z]", "", message.lower()) in GENERIC_MESSAGES:
        return None
    return message
