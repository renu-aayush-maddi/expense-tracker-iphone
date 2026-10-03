from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def today_local() -> date:
    """'Today' in the user's timezone (APP_TIMEZONE), not the server's (UTC on Render)."""
    return datetime.now(ZoneInfo(settings.APP_TIMEZONE)).date()
