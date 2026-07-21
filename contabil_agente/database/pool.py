"""Minimal DatabasePool stub for tests.

Provides a lightweight DatabasePool used by tests that only need a
placeholder object. Do not expose real DB credentials here.
"""

from typing import Optional


class DatabasePool:
    """Minimal stub of a database connection pool.

    Tests in this repository construct a DatabasePool but do not perform
    real database operations. This class provides a small, safe surface
    so imports succeed.
    """

    def __init__(self, pool_size: int = 1):
        self.pool_size = pool_size

    def get_connection(self) -> Optional[object]:
        """Return a dummy connection placeholder (None).

        Real code should replace this with a proper DB connection.
        """
        return None

    def execute(self, *args, **kwargs):
        """Placeholder execute method for compatibility in tests.

        Raises NotImplementedError to avoid silent false positives if a
        test mistakenly tries to run real SQL.
        """
        raise NotImplementedError("Database operations are not available in test stub")
