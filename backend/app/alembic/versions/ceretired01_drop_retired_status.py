"""Drop the unused 'retired' course environment version status.

Revision ID: ceretired01_drop_status
Revises: mrg14_merge_ufb_rpindex

沒有任何程式會把教學環境版本設成 retired，enum 值、語系字串與徽章卻都還在，
畫面上看起來像有「已停用」這個狀態。PostgreSQL 不能直接從 enum 拿掉一個值，
所以把舊型別改名、建新型別、轉欄位、再刪舊型別。

資料表裡若真的有 retired 的列（只可能是手動改資料庫），這支 migration 不猜它
該變成草稿還是已發布，直接停下來讓人處理。
"""

import sqlalchemy as sa
from alembic import op

revision = "ceretired01_drop_status"
down_revision = "mrg14_merge_ufb_rpindex"
branch_labels = None
depends_on = None

_ENUM = "courseenvironmentversionstatus"
_TABLE = "course_environment_versions"


def _swap_enum(labels: tuple[str, ...]) -> None:
    quoted = ", ".join(f"'{label}'" for label in labels)
    op.execute(f"ALTER TYPE {_ENUM} RENAME TO {_ENUM}_old")
    op.execute(f"CREATE TYPE {_ENUM} AS ENUM ({quoted})")
    op.execute(
        f"ALTER TABLE {_TABLE} ALTER COLUMN status TYPE {_ENUM} "
        f"USING status::text::{_ENUM}"
    )
    op.execute(f"DROP TYPE {_ENUM}_old")


def upgrade() -> None:
    retired = (
        op.get_bind()
        .execute(sa.text(f"SELECT count(*) FROM {_TABLE} WHERE status = 'retired'"))
        .scalar_one()
    )
    if retired:
        raise RuntimeError(
            f"{_TABLE} has {retired} row(s) with status 'retired'. The application "
            "never sets this status, so decide by hand whether each row should be "
            "'draft' or 'published', update it, and run the migration again."
        )
    _swap_enum(("draft", "published"))


def downgrade() -> None:
    _swap_enum(("draft", "published", "retired"))
