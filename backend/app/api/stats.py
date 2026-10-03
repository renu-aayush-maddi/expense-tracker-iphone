from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.timeutils import today_local
from app.db.session import get_db
from app.models import User
from app.schemas.stats import DashboardResponse
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = today_local()
    return stats_service.get_dashboard(
        db,
        current_user.id,
        year=year or today.year,
        month=month or today.month,
        today=today,
    )
