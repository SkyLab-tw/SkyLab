"""proxmox_connections 移除沒有作用的 data_storage 與 local_subnet。

這兩個欄位在 PVE 連線表單與首次安裝精靈上看起來會影響建機，實際上沒有：

- ``data_storage``：機器磁碟放哪個 storage 由「儲存管理」（proxmox_storage）
  決定，這個欄位只出現在一則錯誤訊息裡。
- ``local_subnet``：機器的網段由「IP 管理」（SubnetConfig）決定，這個欄位
  存了之後沒有任何程式讀。

降版會把欄位加回來，但原本存的值不會回來：``data_storage`` 一律是預設的
``local-lvm``、``local_subnet`` 一律是空的（這兩個值本來就沒有程式在用）。

Revision ID: pconn03_drop_dead_cols
Revises: ceretired01_drop_status
"""

import sqlalchemy as sa
from alembic import op

revision = "pconn03_drop_dead_cols"
down_revision = "ceretired01_drop_status"
branch_labels = None
depends_on = None

_TABLE = "proxmox_connections"


def upgrade() -> None:
    op.drop_column(_TABLE, "data_storage")
    op.drop_column(_TABLE, "local_subnet")


def downgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "data_storage",
            sa.String(length=255),
            nullable=False,
            server_default="local-lvm",
        ),
    )
    op.add_column(
        _TABLE,
        sa.Column("local_subnet", sa.String(length=50), nullable=True),
    )
