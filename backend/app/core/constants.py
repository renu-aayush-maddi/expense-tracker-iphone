"""Shared constants. Categories live here (not in the database column type),
so adding a new category later is a one-line change."""

CATEGORIES = [
    "Food",
    "Groceries",
    "Shopping",
    "Transport",
    "Bills",
    "Entertainment",
    "Health",
    "Travel",
    "Education",
    "Subscriptions",
    "Rent",
    "Utilities",
    "Other",
]

DEFAULT_CATEGORY = "Other"

PAYMENT_METHODS = [
    "UPI",
    "Debit Card",
    "Credit Card",
    "Cash",
    "Net Banking",
    "Wallet",
    "Other",
]

# Where a transaction came from. New importers (gmail, csv, bank statements...)
# just add a new value here.
SOURCE_MANUAL = "manual"
SOURCE_PHONEPE = "phonepe"
SOURCES = [SOURCE_MANUAL, SOURCE_PHONEPE]
