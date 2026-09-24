from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

backendDir = Path(__file__).resolve().parent
projectRoot = backendDir.parent
dataDir = projectRoot / "data"
dbPath = dataDir / "catalogue.db"
schemaPath = backendDir / "schema.sql"


def ensureDataDir() -> None:
    if not dataDir.exists():
        dataDir.mkdir(parents=True)


def initSchema() -> None:
    ensureDataDir()
    with open(schemaPath, "r", encoding="utf-8") as handle:
        ddl = handle.read()
    with sqlite3.connect(dbPath) as con:
        con.executescript(ddl)


@contextmanager
def openDb() -> Iterator[sqlite3.Connection]:
    ensureDataDir()
    con = sqlite3.connect(dbPath)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()
