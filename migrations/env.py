from alembic import context
from serentable.database import database_engine

with database_engine().connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
