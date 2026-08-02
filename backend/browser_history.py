"""The shape of a browser visit as it arrives from an exporter.

Deliberately three fields. The exporter reads a lot more out of Safari's database —
visit counts, redirect chains, per-visit load context — and none of it is worth
accepting here, because every field this endpoint takes is a field the API has to keep
meaning forever.

Timestamps must carry an offset. A bare "2026-07-29T23:40:00" is ambiguous by up to a
day once it crosses a date boundary, and the whole point of the export is which day a
visit happened on, so an ambiguous timestamp is rejected rather than guessed at.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

# Long enough for the data: URLs and deeply-nested query strings that real browsing
# produces, short enough that a single malformed batch cannot balloon the store.
MAX_URL_LENGTH = 8192
MAX_TITLE_LENGTH = 2048


class SiteVisit(BaseModel):
    """One page view: when it happened, where, and what it was called."""

    model_config = {"extra": "forbid"}

    timestamp: datetime
    url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    # Safari leaves this null for visits it never got a title for — a page that failed
    # to load, or one navigated away from too fast. That is a normal visit, not a bad
    # record, so the default keeps it out of the error path.
    title: str = Field(default="", max_length=MAX_TITLE_LENGTH)

    @field_validator("timestamp")
    @classmethod
    def _require_offset(cls, value: datetime) -> datetime:
        """Reject naive timestamps, then normalise to UTC.

        Storing everything in UTC means two exports from machines in different time
        zones sort against each other correctly. The offset the client sent is not
        preserved: it is a property of where the laptop was, not of the visit.
        """
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                "timestamp needs a UTC offset (e.g. 2026-07-29T08:14:22-04:00)"
            )
        return value.astimezone(UTC)
