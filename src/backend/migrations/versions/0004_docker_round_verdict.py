"""The explicit verdict of each collector round on the Docker API (host_metrics): how many containers came through
(``docker_container_count``), a short readable reason when the round failed (``docker_reason_text``), and the
individual containers whose detail or stats failed while the rest succeeded (``docker_container_errors``, JSON).

Revision 0004, after 0003.
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

_COLUMNS = (
    ('docker_container_count', sa.Integer(), sa.INTEGER()),
    ('docker_reason_text', sa.String(length=255), sa.VARCHAR(length=255)),
    ('docker_container_errors', sa.Text(), sa.TEXT()),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("host_metrics")}
    if bind.dialect.name == "postgresql":
        for name, _model_type, raw_type in _COLUMNS:
            if name not in existing:
                op.execute(f"ALTER TABLE host_metrics ADD COLUMN {name} {raw_type.compile(bind.dialect)}")
        return
    # SQLite (and any other dialect): the portable add_column, skipped when a create_all database already has it.
    for name, model_type, _raw_type in _COLUMNS:
        if name not in existing:
            op.add_column("host_metrics", sa.Column(name, model_type, nullable=True))


def downgrade() -> None:
    for name, _model_type, _raw_type in _COLUMNS:
        op.drop_column("host_metrics", name)
