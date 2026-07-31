"""browser_visits table

Revision ID: 0002
Revises: 0001
Created: 2026-07-31

Browser visits uploaded by cli/ (the Safari exporter). Raw SQL for the same reason 0001
is: there are no SQLAlchemy models here, and the SQL is the thing being reviewed.

The primary key is the interesting part. (visited_at, url) is the identity of a visit —
that is what makes an exporter's retry of a whole day a no-op — but it cannot be the key
directly: a URL may be up to 8192 bytes (browser_history.MAX_URL_LENGTH) and a btree
entry may not exceed roughly a third of an 8kB page, so a long URL would make the INSERT
fail outright rather than deduplicate. url_digest is a fixed-width stand-in for the URL.

It is generated and STORED rather than computed by the app so the digest cannot drift
from the url in its own row, and so a second writer cannot get the invariant wrong.

sha256(url::bytea), not sha256(convert_to(url, 'UTF8')): both hash identical bytes on a
UTF8 database, but convert_to is only STABLE and a generation expression must be
IMMUTABLE, so Postgres rejects the table outright.

Title is deliberately not part of the key. Safari revises a visit's title after the fact
when a page's <title> loads late, so including it would make the corrected re-export
look like a second visit at the identical instant.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE browser_visits (
            visited_at   TIMESTAMPTZ NOT NULL,
            url          TEXT NOT NULL,
            title        TEXT NOT NULL DEFAULT '',
            url_digest   BYTEA GENERATED ALWAYS AS (sha256(url::bytea)) STORED,
            -- When the exporter delivered it, as opposed to when the browsing happened.
            -- Answers "did last night's LaunchAgent run?" without reading logs.
            recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (visited_at, url_digest)
        )
    """)
    # No separate index for the newest-first listing: the primary key leads with
    # visited_at, so a backwards scan of it already serves ORDER BY visited_at DESC.


def downgrade() -> None:
    # Drops every recorded visit. Only reachable by running `alembic downgrade`
    # deliberately, and the cluster keeps 7 days of point-in-time recovery behind it.
    op.execute("DROP TABLE browser_visits")
