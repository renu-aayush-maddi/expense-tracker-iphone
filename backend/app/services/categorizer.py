"""Rule-based automatic categorisation.

The category is only a *suggestion* at import time; the user can change it at
any time. Add your own merchants to CATEGORY_RULES.

Matching is by whole words, and the longest matching keyword wins, so
"Amazon Prime" -> Subscriptions even though "Amazon" -> Shopping.
"""

import re

from app.core.constants import DEFAULT_CATEGORY

CATEGORY_RULES: dict[str, list[str]] = {
    "Food": [
        "zomato", "swiggy", "dominos", "domino's", "pizza hut", "mcdonald", "mcdonalds", "kfc",
        "burger king", "starbucks", "cafe", "restaurant", "dunkin", "subway", "eatsure", "box8",
        "faasos", "haldiram", "haldirams", "chaayos", "chai point", "bakery", "barbeque nation",
        "theobroma", "food", "biryani",
    ],
    "Groceries": [
        "blinkit", "blink commerce", "zepto", "kiranakart", "bigbasket", "big basket", "instamart",
        "jiomart", "dmart", "avenue supermarts", "grofers", "more retail", "reliance fresh",
        "reliance retail", "nature's basket", "supermarket", "grocery", "groceries", "kirana",
        "country delight", "milkbasket", "dunzo", "swiggy instamart",
    ],
    "Shopping": [
        "amazon", "flipkart", "myntra", "ajio", "meesho", "nykaa", "tata cliq", "snapdeal",
        "decathlon", "ikea", "croma", "reliance digital", "lifestyle", "shoppers stop", "h&m",
        "zara", "uniqlo", "lenskart", "westside", "pantaloons",
    ],
    "Transport": [
        "uber", "ola", "ola cabs", "rapido", "ani technologies", "roppen", "namma yatri", "blusmart", "metro", "fastag",
        "petrol", "fuel", "indian oil", "iocl", "bharat petroleum", "bpcl", "hpcl",
        "hindustan petroleum", "shell", "parking", "auto",
    ],
    "Travel": [
        "irctc", "makemytrip", "goibibo", "cleartrip", "yatra", "indigo", "interglobe",
        "air india", "vistara", "spicejet", "akasa", "redbus", "airbnb", "oyo", "booking.com",
        "agoda", "ixigo", "hotel", "hotels", "resort",
    ],
    "Subscriptions": [
        "netflix", "spotify", "hotstar", "jiohotstar", "disney", "prime video", "amazon prime",
        "youtube premium", "youtube", "google one", "apple.com", "apple services", "icloud",
        "jiosaavn", "gaana", "sonyliv", "zee5", "chatgpt", "openai", "anthropic", "claude",
        "linkedin", "audible", "notion", "github",
    ],
    "Entertainment": [
        "bookmyshow", "pvr", "inox", "cinepolis", "paytm insider", "district", "steam",
        "playstation", "xbox", "dream11", "cinema", "movies",
    ],
    "Bills": [
        "airtel", "jio", "vodafone", "vodafone idea", "bsnl", "act fibernet", "hathway",
        "tata play", "dish tv", "recharge", "postpaid", "prepaid", "broadband", "cred",
        "credit card", "insurance", "lic", "policybazaar", "emi", "loan",
    ],
    "Utilities": [
        "electricity", "bescom", "tata power", "adani electricity", "msedcl", "bses",
        "torrent power", "water", "water board", "gas", "indane", "hp gas", "bharat gas",
        "mahanagar gas", "igl", "piped gas", "power",
    ],
    "Health": [
        "apollo", "pharmeasy", "1mg", "tata 1mg", "netmeds", "medplus", "practo", "hospital",
        "clinic", "pharmacy", "medical", "medicals", "chemist", "diagnostic", "diagnostics",
        "lab", "labs", "cult.fit", "cultfit", "healthkart", "dental", "gym",
    ],
    "Education": [
        "udemy", "coursera", "byju", "byjus", "unacademy", "upgrad", "school", "college",
        "university", "tuition", "simplilearn", "vedantu", "physics wallah", "academy",
        "institute", "books", "bookstore",
    ],
    "Rent": ["rent", "nobroker", "nestaway", "housing.com", "landlord"],
}


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9&.' ]+", " ", text)
    return " " + re.sub(r"\s+", " ", text).strip() + " "


# Pre-compile: (keyword length, compiled pattern, category), longest first.
_COMPILED = sorted(
    (
        (len(keyword), re.compile(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"), category)
        for category, keywords in CATEGORY_RULES.items()
        for keyword in keywords
    ),
    key=lambda item: -item[0],
)


def categorize(merchant_name: str | None) -> str:
    """Suggest a category for a merchant name. Falls back to 'Other'."""
    if not merchant_name:
        return DEFAULT_CATEGORY
    text = _normalize(merchant_name)
    for _, pattern, category in _COMPILED:
        if pattern.search(text):
            return category
    return DEFAULT_CATEGORY
