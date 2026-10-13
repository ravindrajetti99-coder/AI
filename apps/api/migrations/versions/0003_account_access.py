"""account access: emailed tokens (password reset, email verification), invites, token versions

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13 10:42:07.377110

Existing users start unverified (they can confirm from their profile) with token_version 0,
which matches the version-less access tokens already issued.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("requested_ip", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_account_tokens_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_account_tokens_token_hash")),
    )
    op.create_index(op.f("ix_account_tokens_user_id"), "account_tokens", ["user_id"], unique=False)
    op.create_table(
        "invites",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_invites_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_invites_code_hash")),
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("token_version", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("token_version")
        batch_op.drop_column("email_verified_at")
    op.drop_table("invites")
    op.drop_index(op.f("ix_account_tokens_user_id"), table_name="account_tokens")
    op.drop_table("account_tokens")
