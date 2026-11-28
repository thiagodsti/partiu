"""A photo on a planner item: the Wikipedia thumbnail of a suggested place.

``image_url`` is the thumbnail, ``image_page`` the article it came from (the
credit link). Both only ever hold Wikimedia URLs — the planner service refuses
anything else, and the CSP only lets the browser load images from there.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE trip_plan_items ADD COLUMN image_url TEXT")
    op.execute("ALTER TABLE trip_plan_items ADD COLUMN image_page TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE trip_plan_items DROP COLUMN image_page")
    op.execute("ALTER TABLE trip_plan_items DROP COLUMN image_url")
