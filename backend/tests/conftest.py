"""Skip PostgreSQL integration cases when the local service is unavailable."""

import psycopg
import pytest

from dtp.db import DbUnconfigured, migrate


@pytest.fixture(scope="session")
def postgres_ready():
    try:
        migrate()
    except (DbUnconfigured, psycopg.OperationalError) as exc:
        pytest.skip(f"PostgreSQL unavailable: {exc}")
