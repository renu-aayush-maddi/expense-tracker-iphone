"""Company reimbursement rule.

A transaction is reimbursable when:
  * the user marked it so (their choice always wins), or
  * the rule is enabled AND the merchant matches one of the keywords (whole
    words, case-insensitive) AND it happened on one of the chosen weekdays.

Default: rides by Uber / Ola / Rapido on Monday–Friday. Ola and Rapido often
appear under their company names on UPI receipts, so those are included.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReimbursementSettings, Transaction

DEFAULT_KEYWORDS = [
    "uber",
    "ola",
    "rapido",
    "ani technologies",  # Ola's company name
    "roppen",  # Rapido's company name (Roppen Transportation Services)
]
DEFAULT_WEEKDAYS = [0, 1, 2, 3, 4]  # Monday–Friday

SET_BY_RULE = "rule"
SET_BY_USER = "user"


@dataclass
class Rule:
    enabled: bool
    keywords: list[str]
    weekdays: list[int]


def get_rule(db: Session, user_id: uuid.UUID) -> Rule:
    row = db.get(ReimbursementSettings, user_id)
    if row is None:
        return Rule(enabled=True, keywords=list(DEFAULT_KEYWORDS), weekdays=list(DEFAULT_WEEKDAYS))
    return Rule(enabled=row.enabled, keywords=list(row.keywords), weekdays=list(row.weekdays))


def save_rule(db: Session, user_id: uuid.UUID, rule: Rule) -> Rule:
    row = db.get(ReimbursementSettings, user_id)
    if row is None:
        row = ReimbursementSettings(user_id=user_id)
        db.add(row)
    row.enabled, row.keywords, row.weekdays = rule.enabled, rule.keywords, rule.weekdays
    db.commit()
    return rule


def _keyword_matches(keyword: str, merchant: str) -> bool:
    # Whole words only: "ola" matches "Ola Cabs" but not "Coca Cola".
    return re.search(r"(?<![a-z0-9])" + re.escape(keyword.lower()) + r"(?![a-z0-9])", merchant.lower()) is not None


def rule_matches(rule: Rule, merchant_name: str | None, transaction_date: date | None) -> bool:
    if not rule.enabled or not merchant_name or transaction_date is None:
        return False
    if transaction_date.weekday() not in rule.weekdays:
        return False
    return any(_keyword_matches(keyword, merchant_name) for keyword in rule.keywords)


def apply_to_new(db: Session, user_id: uuid.UUID, data: dict) -> dict:
    """For a transaction about to be created: keep an explicit True/False from the
    user, otherwise decide with the rule."""
    data = dict(data)
    if data.get("is_reimbursable") is not None:
        data["reimbursable_set_by"] = SET_BY_USER
    else:
        rule = get_rule(db, user_id)
        data["is_reimbursable"] = rule_matches(rule, data.get("merchant_name"), data.get("transaction_date"))
        data["reimbursable_set_by"] = SET_BY_RULE
    return data


def apply_to_update(db: Session, transaction: Transaction, changes: dict) -> dict:
    """For an edit: an explicit True/False is the user's choice. `None` means
    "back to automatic". Changing merchant/date re-runs the rule unless the user
    decided manually."""
    changes = dict(changes)
    if "is_reimbursable" in changes and changes["is_reimbursable"] is not None:
        changes["reimbursable_set_by"] = SET_BY_USER
        return changes

    back_to_auto = "is_reimbursable" in changes  # explicit null
    relevant_change = "merchant_name" in changes or "transaction_date" in changes
    if back_to_auto or (relevant_change and transaction.reimbursable_set_by != SET_BY_USER):
        rule = get_rule(db, transaction.user_id)
        changes["is_reimbursable"] = rule_matches(
            rule,
            changes.get("merchant_name", transaction.merchant_name),
            changes.get("transaction_date", transaction.transaction_date),
        )
        changes["reimbursable_set_by"] = SET_BY_RULE
    else:
        changes.pop("is_reimbursable", None)
    return changes


def reapply_rule(db: Session, user_id: uuid.UUID) -> int:
    """Re-evaluate every transaction the user hasn't decided manually.
    Returns how many changed."""
    rule = get_rule(db, user_id)
    changed = 0
    transactions = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user_id,
            (Transaction.reimbursable_set_by != SET_BY_USER) | Transaction.reimbursable_set_by.is_(None),
        )
    ).all()
    for transaction in transactions:
        should_be = rule_matches(rule, transaction.merchant_name, transaction.transaction_date)
        if transaction.is_reimbursable != should_be or transaction.reimbursable_set_by != SET_BY_RULE:
            changed += transaction.is_reimbursable != should_be
            transaction.is_reimbursable = should_be
            transaction.reimbursable_set_by = SET_BY_RULE
    db.commit()
    return changed
