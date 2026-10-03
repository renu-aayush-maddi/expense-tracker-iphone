import csv
import io
import math
import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.transaction import (
    FilterOptions,
    TransactionCreate,
    TransactionDetailOut,
    TransactionListResponse,
    TransactionOut,
    TransactionUpdate,
)
from app.services import transaction_service
from app.services.transaction_service import DuplicateTransactionError, TransactionFilters

router = APIRouter(prefix="/transactions", tags=["transactions"])


def duplicate_http_error(error: DuplicateTransactionError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": "A transaction with the same PhonePe transaction ID / UTR already exists.",
            "existing_transaction_id": str(error.existing.id) if error.existing else None,
        },
    )


def _get_owned_or_404(db: Session, user: User, transaction_id: uuid.UUID):
    transaction = transaction_service.get_transaction(db, user.id, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found.")
    return transaction


def transaction_filters(
    on_date: date | None = Query(default=None, alias="date"),
    date_from: date | None = None,
    date_to: date | None = None,
    month: int | None = Query(default=None, ge=1, le=12),
    year: int | None = Query(default=None, ge=2000, le=2100),
    category: str | None = Query(default=None, max_length=50),
    bank: str | None = Query(default=None, max_length=100),
    payment_method: str | None = Query(default=None, max_length=50),
    merchant: str | None = Query(default=None, max_length=100),
    search: str | None = Query(default=None, max_length=100),
    min_amount: Decimal | None = Query(default=None, ge=0),
    max_amount: Decimal | None = Query(default=None, ge=0),
    source: str | None = Query(default=None, max_length=30),
    reimbursable: bool | None = Query(default=None, description="true = company reimbursable, false = personal"),
) -> TransactionFilters:
    """Query-string filters shared by the list and the CSV export."""
    return TransactionFilters(
        date=on_date,
        date_from=date_from,
        date_to=date_to,
        month=month,
        year=year,
        category=category or None,
        bank=bank or None,
        payment_method=payment_method or None,
        merchant=merchant or None,
        search=search or None,
        min_amount=min_amount,
        max_amount=max_amount,
        source=source or None,
        reimbursable=reimbursable,
    )


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    filters: TransactionFilters = Depends(transaction_filters),
    sort_by: Literal["date", "amount", "merchant", "category", "created"] = "date",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = transaction_service.list_transactions(
        db, current_user.id, filters, sort_by, sort_order, page, page_size
    )
    return TransactionListResponse(
        items=[TransactionOut.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/filter-options", response_model=FilterOptions)
def filter_options(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return transaction_service.get_filter_options(db, current_user.id)


def _csv_cell(value) -> str:
    """Stop spreadsheet formula injection: a cell starting with = + - @ is shown as text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@router.get("/export.csv", response_class=Response)
def export_csv(
    filters: TransactionFilters = Depends(transaction_filters),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download the filtered transactions as CSV (e.g. a month's reimbursement claim)."""
    rows = transaction_service.list_all_for_export(db, current_user.id, filters)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["Date", "Time", "Merchant", "Category", "Amount (INR)", "Payment method", "Bank",
         "Company reimbursable", "Notes", "UTR", "PhonePe transaction ID"]
    )
    for t in rows:
        writer.writerow(
            [_csv_cell(v) for v in (
                t.transaction_date.isoformat(),
                t.transaction_time.strftime("%H:%M") if t.transaction_time else "",
                t.merchant_name,
                t.category,
                f"{t.amount:.2f}",
                t.payment_method,
                t.bank,
                "Yes" if t.is_reimbursable else "No",
                t.notes,
                t.utr,
                t.phonepe_transaction_id,
            )]
        )
    writer.writerow([])
    writer.writerow(["", "", "Total", "", f"{sum((t.amount for t in rows), Decimal('0')):.2f}"])
    return Response(
        content="\ufeff" + buffer.getvalue(),  # BOM so Excel shows ₹/Unicode correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="transactions.csv"'},
    )


@router.post("", response_model=TransactionDetailOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return transaction_service.create_transaction(db, current_user.id, payload.model_dump())
    except DuplicateTransactionError as error:
        raise duplicate_http_error(error)


@router.get("/{transaction_id}", response_model=TransactionDetailOut)
def get_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, current_user, transaction_id)


@router.put("/{transaction_id}", response_model=TransactionDetailOut)
def update_transaction(
    transaction_id: uuid.UUID,
    payload: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    transaction = _get_owned_or_404(db, current_user, transaction_id)
    changes = payload.model_dump(exclude_unset=True)
    # Required columns can't be cleared.
    for field in ("amount", "merchant_name", "category", "transaction_date"):
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{field} cannot be empty.")
    try:
        return transaction_service.update_transaction(db, transaction, changes)
    except DuplicateTransactionError as error:
        raise duplicate_http_error(error)


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    transaction = _get_owned_or_404(db, current_user, transaction_id)
    transaction_service.delete_transaction(db, transaction)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
