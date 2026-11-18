from alembic import op
import sqlalchemy as sa

revision = "0005_mfa_hardening"
down_revision = "0004_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("investment_approvals")}
    if "mfa_code_hash" not in existing:
        op.add_column("investment_approvals", sa.Column("mfa_code_hash", sa.String(length=64), nullable=True))
    if "mfa_expires_at" not in existing:
        op.add_column("investment_approvals", sa.Column("mfa_expires_at", sa.DateTime(), nullable=True))
    if "mfa_used" not in existing:
        op.add_column("investment_approvals", sa.Column("mfa_used", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "mfa_failed_attempts" not in existing:
        op.add_column("investment_approvals", sa.Column("mfa_failed_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("investment_approvals")}
    for column_name in ("mfa_failed_attempts", "mfa_used", "mfa_expires_at", "mfa_code_hash"):
        if column_name in existing:
            op.drop_column("investment_approvals", column_name)
