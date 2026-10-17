"""SQLite runtime configuration hooks.

Every new database connection (in web, bot and worker processes) gets the
PRAGMAs required for safe concurrent access to the shared SQLite file:

- journal_mode=WAL       -> readers never block the writer and vice versa
- busy_timeout=5000      -> writers wait up to 5s instead of raising
                            'database is locked' immediately
- synchronous=NORMAL     -> recommended durability setting when using WAL
- foreign_keys=ON        -> enforce FK integrity (off by default in SQLite)
"""
from django.db.backends.signals import connection_created


def configure_sqlite_connection(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")


connection_created.connect(configure_sqlite_connection)
