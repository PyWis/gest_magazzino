from alembic import context
from flask import current_app

config = context.config
db = current_app.extensions["migrate"].db


def run_migrations_offline():
    context.configure(url=str(db.engine.url), target_metadata=db.metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=db.metadata,
                          render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
