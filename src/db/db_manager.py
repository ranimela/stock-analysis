"""DuckDB Database Manager Module.

Provides thread-safe access, connection management, schema initialization,
and context managers for reading and writing to the DuckDB storage engine.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
from typing import Any, Generator, Sequence

import duckdb


class DatabaseManager:
    """Manages thread-safe read/write operations and schema lifecycle for DuckDB.

    DuckDB connections allow concurrent read operations across threads, but write
    operations require serialization. This manager maintains a shared lock for
    writing operations and schema setup to ensure thread safety across multi-threaded
    ingestion/screening workers.
    """

    def __init__(
        self,
        db_path: str | Path = "market_data.duckdb",
        read_only: bool = False,
    ) -> None:
        """Initialize DatabaseManager with database file path.

        Args:
            db_path: Path to DuckDB database file. Defaults to 'market_data.duckdb'.
            read_only: Whether to operate in read-only mode (prevents schema initialization & writes).
        """
        self.db_path = Path(db_path)
        self.read_only = read_only
        self._write_lock = threading.Lock()
        if not self.read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self, read_only: bool | None = None) -> duckdb.DuckDBPyConnection:
        """Create a new DuckDB connection.

        Args:
            read_only: Whether connection should open in read-only mode.
                If None, uses self.read_only.

        Returns:
            duckdb.DuckDBPyConnection: Opened connection instance.
        """
        effective_read_only = self.read_only if read_only is None else read_only
        config = {"access_mode": "READ_ONLY"} if effective_read_only else {}
        try:
            return duckdb.connect(database=str(self.db_path), read_only=effective_read_only, config=config)
        except Exception:
            return duckdb.connect(database=str(self.db_path), read_only=effective_read_only)

    def init_schema(self, schema_file: str | Path | None = None) -> None:
        """Initialize database schema from SQL DDL script.

        Args:
            schema_file: Path to schema SQL file. If None, resolves to default
                'schema.sql' in the same directory as this module.
        """
        if schema_file is None:
            schema_file = Path(__file__).parent / "schema.sql"
        else:
            schema_file = Path(schema_file)

        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found at {schema_file}")

        sql_content = schema_file.read_text(encoding="utf-8")

        with self._write_lock:
            conn = self.get_connection(read_only=False)
            try:
                conn.execute(sql_content)
            finally:
                conn.close()

    @contextmanager
    def read_cursor(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """Context manager providing a read-only DuckDB connection cursor.

        Yields:
            duckdb.DuckDBPyConnection: Read-only database connection.
        """
        conn = self.get_connection(read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write_cursor(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """Context manager providing thread-safe write access to DuckDB.

        Acquires thread lock before opening connection and executing commands.

        Yields:
            duckdb.DuckDBPyConnection: Read-write database connection.
        """
        if self.read_only:
            raise duckdb.ReadOnlyException("Cannot write when DatabaseManager is in read-only mode.")
        with self._write_lock:
            conn = self.get_connection(read_only=False)
            try:
                yield conn
            finally:
                conn.close()

    def execute_read(
        self, query: str, parameters: Sequence[Any] | None = None
    ) -> list[tuple[Any, ...]]:
        """Execute a SQL read query and fetch all results.

        Args:
            query: SQL query string.
            parameters: Optional query parameters.

        Returns:
            list[tuple[Any, ...]]: Fetched rows from query execution.
        """
        with self.read_cursor() as conn:
            if parameters:
                cursor = conn.execute(query, parameters)
            else:
                cursor = conn.execute(query)
            return cursor.fetchall()

    def execute_write(
        self, query: str, parameters: Sequence[Any] | None = None
    ) -> duckdb.DuckDBPyConnection:
        """Execute a single write query in a thread-safe context.

        Args:
            query: SQL DML/DDL query string.
            parameters: Optional query parameters.

        Returns:
            duckdb.DuckDBPyConnection: Executed cursor (within closed connection scope,
                useful for rowcount or execution confirmation).
        """
        with self.write_cursor() as conn:
            if parameters:
                return conn.execute(query, parameters)
            return conn.execute(query)
