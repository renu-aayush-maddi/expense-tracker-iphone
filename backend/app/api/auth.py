from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_allow_password_change, inactive_account_error
from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.permissions import is_admin
from app.core.rate_limit import RateLimiter
from app.core.security import verify_password
from app.db.session import get_db
from app.models import User
from app.models.user import STATUS_ACTIVE
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services import audit_service, auth_service, security_service, session_service

router = APIRouter(prefix="/auth", tags=["auth"])

login_limiter = RateLimiter(max_requests=settings.LOGIN_RATE_LIMIT_PER_MINUTE)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    if not settings.ALLOW_REGISTRATION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registration is disabled.")
    login_limiter.hit(f"register:{get_client_ip(request)}")
    try:
        user = auth_service.register_user(db, payload.email, payload.password, payload.full_name, request)
    except auth_service.EmailAlreadyRegistered:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    security_service.record_event(db, security_service.REGISTER, request=request, user=user, success=True)
    security_service.after_registration(db, request)
    token = auth_service.start_session(db, user, request)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    login_limiter.hit(f"login:{get_client_ip(request)}")  # per-IP brute-force limit
    email = payload.email.lower()
    user, password_ok = auth_service.check_password(db, email, payload.password)

    # Per-account brute-force protection: temporary lockout after repeated failures.
    if user is not None and security_service.is_locked(db, user):
        security_service.record_event(db, security_service.LOGIN_BLOCKED, request=request, user=user,
                                      success=False, reason="account temporarily locked", severity="warning")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {settings.LOCKOUT_MINUTES} minutes.",
        )

    if not password_ok:
        security_service.record_event(db, security_service.LOGIN_FAILED, request=request, user=user, email=email,
                                      success=False, reason="wrong password" if user else "unknown email")
        if user is not None and is_admin(user.role):
            audit_service.record(db, "ADMIN_LOGIN_FAILED", actor=user, request=request, resource_type="session",
                                 result="failure", details={"reason": "wrong password"})
        security_service.after_failed_login(db, request, user, email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")

    # Status is only revealed after a correct password (doesn't leak which emails exist).
    if user.status != STATUS_ACTIVE:
        security_service.record_event(db, security_service.LOGIN_BLOCKED, request=request, user=user,
                                      success=False, reason=f"account {user.status}", severity="warning")
        raise inactive_account_error(user)

    token = auth_service.start_session(db, user, request)
    security_service.record_event(db, security_service.LOGIN_SUCCESS, request=request, user=user, success=True)
    if is_admin(user.role):
        audit_service.record(db, "ADMIN_LOGIN", actor=user, request=request, resource_type="session")
    security_service.after_successful_login(db, request, user)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, user: User = Depends(get_current_user_allow_password_change), db: Session = Depends(get_db)):
    """Ends this session on the server (the token stops working immediately)."""
    session_service.revoke(db, request.state.session, reason="logout")
    db.commit()
    security_service.record_event(db, security_service.LOGOUT, request=request, user=user, success=True)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user_allow_password_change),
    db: Session = Depends(get_db),
):
    login_limiter.hit(f"change-password:{user.id}")
    if not verify_password(payload.current_password, user.hashed_password):
        security_service.record_event(db, security_service.PASSWORD_CHANGED, request=request, user=user,
                                      success=False, reason="wrong current password", severity="warning")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your current password is incorrect.")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose a different password.")
    auth_service.set_password(user, payload.new_password)
    user.must_change_password = False
    # Log out every OTHER device; this one stays signed in.
    session_service.revoke_all(db, user.id, reason="password_changed", keep=request.state.session.id)
    db.commit()
    security_service.record_event(db, security_service.PASSWORD_CHANGED, request=request, user=user, success=True)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user_allow_password_change)):
    return current_user
