"""Dashboard numbers. All sums are done in SQL with NUMERIC, never in floats."""

import calendar
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import case, extract, func, select
from sqlalchemy.orm import Session

from app.models import PendingImport, Transaction

ZERO = Decimal("0.00")


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _month_range(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _group_totals(db: Session, user_id: uuid.UUID, column, start: date, end: date, unknown: str) -> list[dict]:
    label = func.coalesce(column, unknown)
    rows = db.execute(
        select(label.label("label"), func.sum(Transaction.amount), func.count())
        .where(Transaction.user_id == user_id, Transaction.transaction_date.between(start, end))
        .group_by(label)
        .order_by(func.sum(Transaction.amount).desc())
    ).all()
    return [{"label": r[0], "total": _money(r[1]), "count": r[2]} for r in rows]


def get_dashboard(db: Session, user_id: uuid.UUID, year: int, month: int, today: date) -> dict:
    mine = Transaction.user_id == user_id
    month_start, month_end = _month_range(year, month)
    in_month = Transaction.transaction_date.between(month_start, month_end)

    today_total = db.scalar(select(func.sum(Transaction.amount)).where(mine, Transaction.transaction_date == today))

    month_total, month_count = db.execute(
        select(func.sum(Transaction.amount), func.count()).where(mine, in_month)
    ).one()
    month_total = _money(month_total)
    month_average = _money(month_total / month_count) if month_count else ZERO

    # Company reimbursements this month.
    reimb_total, reimb_count = db.execute(
        select(func.sum(Transaction.amount), func.count()).where(mine, in_month, Transaction.is_reimbursable.is_(True))
    ).one()
    reimb_total = _money(reimb_total)

    largest = db.scalars(
        select(Transaction).where(mine, in_month).order_by(Transaction.amount.desc()).limit(1)
    ).first()

    # Daily totals for the selected month (every day present, zero if no spending).
    day_col = extract("day", Transaction.transaction_date)
    daily_rows = dict(
        db.execute(
            select(day_col, func.sum(Transaction.amount)).where(mine, in_month).group_by(day_col)
        ).all()
    )
    daily_rows = {int(k): v for k, v in daily_rows.items()}
    daily = [{"day": d, "total": _money(daily_rows.get(d))} for d in range(1, month_end.day + 1)]

    # Monthly trend: the 12 months ending with the selected month.
    first_year, first_month = _shift_month(year, month, -11)
    trend_start = date(first_year, first_month, 1)
    year_col = extract("year", Transaction.transaction_date)
    month_col = extract("month", Transaction.transaction_date)
    reimbursable_amount = func.sum(case((Transaction.is_reimbursable.is_(True), Transaction.amount), else_=0))
    trend_rows = db.execute(
        select(year_col, month_col, func.sum(Transaction.amount), reimbursable_amount)
        .where(mine, Transaction.transaction_date.between(trend_start, month_end))
        .group_by(year_col, month_col)
    ).all()
    trend_map = {(int(y), int(m)): (total, reimb) for y, m, total, reimb in trend_rows}
    monthly_trend = []
    for offset in range(12):
        y, m = _shift_month(first_year, first_month, offset)
        total, reimb = trend_map.get((y, m), (0, 0))
        monthly_trend.append(
            {
                "year": y,
                "month": m,
                "label": f"{calendar.month_abbr[m]} {y}",
                "total": _money(total),
                "reimbursable": _money(reimb),
                "personal": _money(total) - _money(reimb),
            }
        )

    yearly_rows = db.execute(
        select(year_col, func.sum(Transaction.amount)).where(mine).group_by(year_col).order_by(year_col)
    ).all()
    yearly = [{"year": int(y), "total": _money(total)} for y, total in yearly_rows]

    recent = db.scalars(
        select(Transaction)
        .where(mine)
        .order_by(
            Transaction.transaction_date.desc(),
            Transaction.transaction_time.desc().nulls_last(),
            Transaction.created_at.desc(),
        )
        .limit(5)
    ).all()

    pending_reviews = db.scalar(select(func.count()).select_from(PendingImport).where(PendingImport.user_id == user_id))

    return {
        "year": year,
        "month": month,
        "today_total": _money(today_total),
        "month_total": month_total,
        "month_count": month_count,
        "month_average": month_average,
        "month_reimbursable_total": reimb_total,
        "month_reimbursable_count": reimb_count,
        "month_personal_total": month_total - reimb_total,
        "largest_transaction": largest,
        "by_category": _group_totals(db, user_id, Transaction.category, month_start, month_end, "Other"),
        "by_bank": _group_totals(db, user_id, Transaction.bank, month_start, month_end, "Unknown"),
        "by_payment_method": _group_totals(
            db, user_id, Transaction.payment_method, month_start, month_end, "Unknown"
        ),
        "daily": daily,
        "monthly_trend": monthly_trend,
        "yearly": yearly,
        "recent_transactions": list(recent),
        "pending_reviews": pending_reviews or 0,
    }
