"""User settings: import tokens for the iPhone Shortcut, and account -> bank mappings."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import generate_import_token, hash_import_token
from app.db.session import get_db
from app.models import ApiToken, BankAccount, User
from app.schemas.settings import ApiTokenCreate, ApiTokenCreated, ApiTokenOut, BankAccountCreate, BankAccountOut

router = APIRouter(prefix="/settings", tags=["settings"])

MAX_TOKENS_PER_USER = 10


# ----- Import tokens -----
@router.get("/tokens", response_model=list[ApiTokenOut])
def list_tokens(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(ApiToken).where(ApiToken.user_id == current_user.id).order_by(ApiToken.created_at.desc())
    ).all()


@router.post("/tokens", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
def create_token(payload: ApiTokenCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = len(db.scalars(select(ApiToken.id).where(ApiToken.user_id == current_user.id)).all())
    if count >= MAX_TOKENS_PER_USER:
        raise HTTPException(status_code=400, detail=f"You can have at most {MAX_TOKENS_PER_USER} tokens. Delete one first.")

    plain = generate_import_token()
    token = ApiToken(
        user_id=current_user.id,
        name=payload.name.strip(),
        token_hash=hash_import_token(plain),
        token_hint=plain[:8] + "…",
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return ApiTokenCreated(**ApiTokenOut.model_validate(token).model_dump(), token=plain)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_token(token_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token = db.scalar(select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == current_user.id))
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found.")
    db.delete(token)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----- Bank account mappings -----
@router.get("/accounts", response_model=list[BankAccountOut])
def list_accounts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(BankAccount).where(BankAccount.user_id == current_user.id).order_by(BankAccount.bank_name)
    ).all()


@router.post("/accounts", response_model=BankAccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: BankAccountCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    account = BankAccount(user_id=current_user.id, account_last4=payload.account_last4, bank_name=payload.bank_name)
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This account number is already mapped to a bank.")
    db.refresh(account)
    return account


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = db.scalar(select(BankAccount).where(BankAccount.id == account_id, BankAccount.user_id == current_user.id))
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    db.delete(account)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
