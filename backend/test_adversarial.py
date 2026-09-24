"""Adversarial and malformed-input tests for the import pipeline.

Runs deliberately hostile MEI files from data/adversarial/ through ingestFile
against an isolated in-memory database, so the results never touch the real
catalogue or the 77-file evaluation corpus. Complements validate_mei.py,
which proves correctness on well-formed sources; this proves the pipeline
degrades gracefully instead of crashing or corrupting data on bad ones.

Writes data/adversarial_report.json and prints a pass/fail summary. Exit
code 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

from db import dataDir, schemaPath
from import_mei import ingestFile

adversarialDir = dataDir / "adversarial"


def openMemoryDb() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    with open(schemaPath, "r", encoding="utf-8") as handle:
        con.executescript(handle.read())
    return con


def countWorks(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COUNT(*) AS n FROM work").fetchone()["n"]


def caseMalformedTruncated(con: sqlite3.Connection) -> list[tuple[str, bool, str]]:
    report = ingestFile(con, adversarialDir / "malformed_truncated.xml")
    checks = []
    checks.append(("status is skipped", report["status"] == "skipped", report["status"]))
    checks.append(("no row inserted", countWorks(con) == 0, f"work count={countWorks(con)}"))
    return checks


def caseNoNamespace(con: sqlite3.Connection) -> list[tuple[str, bool, str]]:
    before = countWorks(con)
    report = ingestFile(con, adversarialDir / "no_namespace.xml")
    checks = []
    checks.append(("does not crash, status ok", report["status"] == "ok", report["status"]))
    checks.append(("degrades to filename title, not a crash", countWorks(con) == before + 1, f"work count={countWorks(con)}"))
    checks.append(("no composer found, warned", "no composer element found, stored as 'Unknown'" in report["warnings"], str(report["warnings"])))
    return checks


def caseAmbiguousYear(con: sqlite3.Connection) -> list[tuple[str, bool, str]]:
    report = ingestFile(con, adversarialDir / "ambiguous_year.xml")
    row = con.execute(
        "SELECT year_composed FROM work WHERE source_file = 'ambiguous_year.xml'"
    ).fetchone()
    checks = []
    checks.append(("free-text date does not crash", report["status"] == "ok", report["status"]))
    checks.append(("non-numeric date parses to NULL, not a garbage value", row["year_composed"] is None, f"year_composed={row['year_composed']!r}"))
    return checks


def caseDuplicateCatalogueNumber(con: sqlite3.Connection) -> list[tuple[str, bool, str]]:
    ingestFile(con, adversarialDir / "duplicate_catalogue_a.xml")
    ingestFile(con, adversarialDir / "duplicate_catalogue_b.xml")
    rows = con.execute(
        """
        SELECT w.title FROM work w
        JOIN composer c ON c.id = w.composer_id
        WHERE c.name = 'Duplicate Test Composer' AND w.catalogue_number = 'DUP-001'
        """
    ).fetchall()
    checks = []
    checks.append(("same composer+catalogue_number replaces, not duplicates", len(rows) == 1, f"{len(rows)} rows found"))
    if len(rows) == 1:
        checks.append(("the later file wins", "should replace A" in rows[0]["title"], rows[0]["title"]))
    return checks


cases: dict[str, Callable[[sqlite3.Connection], list[tuple[str, bool, str]]]] = {
    "malformed_truncated": caseMalformedTruncated,
    "no_namespace": caseNoNamespace,
    "ambiguous_year": caseAmbiguousYear,
    "duplicate_catalogue_number": caseDuplicateCatalogueNumber,
}


def main() -> int:
    con = openMemoryDb()
    results: dict[str, Any] = {}
    allPassed = True
    for caseName, caseFn in cases.items():
        checks = caseFn(con)
        casePassed = all(ok for _, ok, _ in checks)
        allPassed = allPassed and casePassed
        results[caseName] = {
            "passed": casePassed,
            "checks": [{"name": name, "ok": ok, "detail": detail} for name, ok, detail in checks],
        }
        status = "PASS" if casePassed else "FAIL"
        print(f"[{status}] {caseName}")
        for name, ok, detail in checks:
            mark = "  ok" if ok else "  FAIL"
            print(f"{mark}: {name} ({detail})")

    con.close()

    reportPath = dataDir / "adversarial_report.json"
    with open(reportPath, "w", encoding="utf-8") as handle:
        json.dump({"all_passed": allPassed, "cases": results}, handle, indent=2)
    print(f"Full report: {reportPath}")

    return 0 if allPassed else 1


if __name__ == "__main__":
    sys.exit(main())
