from decimal import Decimal

from pydantic import BaseModel

from app.schemas.transaction import TransactionOut


class GroupTotal(BaseModel):
    label: str
    total: Decimal
    count: int


class MonthTotal(BaseModel):
    year: int
    month: int
    label: str  # e.g. "Oct 2026"
    total: Decimal


class YearTotal(BaseModel):
    year: int
    total: Decimal


class DayTotal(BaseModel):
    day: int
    total: Decimal


class DashboardResponse(BaseModel):
    year: int
    month: int
    today_total: Decimal
    month_total: Decimal
    month_count: int
    month_average: Decimal
    largest_transaction: TransactionOut | None
    by_category: list[GroupTotal]
    by_bank: list[GroupTotal]
    by_payment_method: list[GroupTotal]
    daily: list[DayTotal]
    monthly_trend: list[MonthTotal]
    yearly: list[YearTotal]
    recent_transactions: list[TransactionOut]
    pending_reviews: int
