"""ai metering: cache tokens, request ids, stop reasons, refusals and fallbacks on llm_calls

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13 12:10:00.000000

Existing rows get empty strings and zero cache tokens (the defaults are dropped afterwards). For them `requested_model` stays empty,
which the AI status counts as "not a fallback".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STRINGS = {"requested_model": 80, "effort": 10, "request_id": 80, "stop_reason": 30, "refusal_category": 40}
COUNTS = ("cache_read_tokens", "cache_write_tokens")


def upgrade() -> None:
    # The server defaults only fill existing rows; the app always writes these columns.
    with op.batch_alter_table("llm_calls") as batch_op:
        for name, length in STRINGS.items():
            batch_op.add_column(sa.Column(name, sa.String(length=length), server_default="", nullable=False))
        for name in COUNTS:
            batch_op.add_column(sa.Column(name, sa.Integer(), server_default="0", nullable=False))
    with op.batch_alter_table("llm_calls") as batch_op:
        for name in (*STRINGS, *COUNTS):
            batch_op.alter_column(name, server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("llm_calls") as batch_op:
        for name in (*STRINGS, *COUNTS):
            batch_op.drop_column(name)
