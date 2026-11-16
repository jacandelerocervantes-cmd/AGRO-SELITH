import os

from alembic import context
from sqlalchemy import create_engine

URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://milpa:milpa_dev_only@localhost:5432/milpa"
)


def run() -> None:
    engine = create_engine(context.config.attributes.get("url") or URL)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run()
