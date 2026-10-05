"""UTC timestamps, including legacy SQLite CURRENT_TIMESTAMP values."""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


UTCTimestamp = Annotated[datetime, AfterValidator(_utc_timestamp)]
