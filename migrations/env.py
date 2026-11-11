from alembic import context
from app.core.database import Base, engine
from app.infrastructure import models  # noqa: F401

target_metadata=Base.metadata

def run_migrations_online():
    with engine.connect() as conn:
        context.configure(connection=conn,target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

def run_migrations_offline():
    from app.core.database import database_url
    context.configure(url=database_url().render_as_string(hide_password=False),
                      target_metadata=target_metadata,literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
