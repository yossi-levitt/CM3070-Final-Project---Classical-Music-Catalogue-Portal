"""Validate the SQLite catalogue against the original MEI XML sources.

Two independent layers of checking:
1. Round-trip: every stored work field is re-extracted from its source file
   and compared with the database value (catches import or storage bugs).
2. Raw-text presence: stored title and catalogue number must literally occur
   in the source XML text (catches extraction picking up the wrong element).

Also detects orphans in both directions: database rows whose source file has
disappeared, and MEI files that never made it into the database.

Writes data/validation_report.json and prints a summary. Exit code 0 when
all checks pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from lxml import etree

_whitespaceRun = re.compile(r"\s+")

from db import dataDir, openDb
from import_mei import (
    extractComposer,
    extractInstruments,
    extractManuscripts,
    extractMovements,
    extractPerformances,
    extractWorkFields,
    workFieldNames,
)


def fetchWorkRow(con, sourceFile: str) -> Any:
    return con.execute(
        """
        SELECT w.*, c.name AS composer_name
        FROM work w
        JOIN composer c ON c.id = w.composer_id
        WHERE w.source_file = ?
        """,
        (sourceFile,),
    ).fetchone()


def fetchChildCounts(con, workId: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ("movement", "work_instrument", "manuscript", "performance"):
        counts[table] = con.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE work_id = ?", (workId,)
        ).fetchone()["n"]
    return counts


def fetchMovementRow(con, sourceFile: str) -> Any:
    return con.execute(
        "SELECT * FROM movement WHERE source_file = ?", (sourceFile,)
    ).fetchone()


def validateMovementFile(con, meiPath: Path, movementRow: Any) -> dict[str, Any]:
    """Validate a file that was ingested as one movement of a multi-file work
    (import_multi_file_works.py), rather than as its own top-level work.
    """
    result: dict[str, Any] = {"file": meiPath.name, "checks": [], "passed": True}

    def check(name: str, ok: bool, detail: str | None = None) -> None:
        result["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            result["passed"] = False

    check("movement_row_exists", True)
    try:
        root = etree.parse(str(meiPath)).getroot()
    except etree.XMLSyntaxError as err:
        check("xml_parse", False, str(err))
        return result

    expected = extractWorkFields(root, meiPath.name)
    expectedTitle = expected["title"] if expected["title"] != meiPath.name else None
    # ingestMultiFileWork falls back to "Movement N" when the file's own title
    # extraction just returns its filename; a real extracted title must match
    # exactly, a fallback title only needs the "Movement " pattern.
    if expectedTitle is not None:
        check(
            "field:title",
            movementRow["title"] == expectedTitle,
            None if movementRow["title"] == expectedTitle else f"db={movementRow['title']!r} xml={expectedTitle!r}",
        )
    else:
        check("field:title", str(movementRow["title"]).startswith("Movement "))

    return result


def validateFile(con, meiPath: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"file": meiPath.name, "checks": [], "passed": True}

    def check(name: str, ok: bool, detail: str | None = None) -> None:
        result["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            result["passed"] = False

    try:
        tree = etree.parse(str(meiPath))
    except etree.XMLSyntaxError as err:
        check("xml_parse", False, str(err))
        return result

    row = fetchWorkRow(con, meiPath.name)
    if row is None:
        movementRow = fetchMovementRow(con, meiPath.name)
        if movementRow is not None:
            return validateMovementFile(con, meiPath, movementRow)
        check("db_row_exists", False, "no work row for this source file")
        return result
    check("db_row_exists", True)

    root = tree.getroot()
    expected = extractWorkFields(root, meiPath.name)
    for fieldName in workFieldNames + ["encoding_style"]:
        stored = row[fieldName]
        check(
            f"field:{fieldName}",
            stored == expected[fieldName],
            None if stored == expected[fieldName] else f"db={stored!r} xml={expected[fieldName]!r}",
        )

    composerName, _, _ = extractComposer(root)
    check(
        "field:composer",
        row["composer_name"] == composerName,
        None if row["composer_name"] == composerName else f"db={row['composer_name']!r} xml={composerName!r}",
    )

    # Raw-text presence: stored values must occur in the whitespace-normalised source text
    # Collapse internal whitespace too, independently of import_mei's own text()
    # helper, since a pretty-printed source can put newlines/indentation inside
    # a single text node.
    rawText = " ".join(chunk for chunk in (_whitespaceRun.sub(" ", c).strip() for c in root.itertext()) if chunk != "")
    if row["title"] is not None and row["title"] != meiPath.name:
        check("raw_text:title", row["title"] in rawText, f"title {row['title']!r} not in source text")
    if row["catalogue_number"] is not None:
        check(
            "raw_text:catalogue_number",
            row["catalogue_number"] in rawText,
            f"catalogue number {row['catalogue_number']!r} not in source text",
        )

    expectedCounts = {
        "movement": len(extractMovements(root)),
        "work_instrument": len(extractInstruments(root)),
        "manuscript": len(extractManuscripts(root)),
        "performance": len(extractPerformances(root)),
    }
    storedCounts = fetchChildCounts(con, row["id"])
    for table, expectedCount in expectedCounts.items():
        # work_instrument dedupes on (work, instrument), so stored may be lower
        ok = storedCounts[table] == expectedCount or (
            table == "work_instrument" and storedCounts[table] <= expectedCount
        )
        check(
            f"count:{table}",
            ok,
            None if ok else f"db={storedCounts[table]} xml={expectedCount}",
        )

    return result


def findOrphanRows(con, fileNames: set[str]) -> list[str]:
    rows = con.execute("SELECT source_file FROM work").fetchall()
    return sorted({
        r["source_file"] for r in rows
        if r["source_file"] not in fileNames and not r["source_file"].startswith("(multi-file")
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the catalogue database against source MEI XML files.")
    parser.add_argument("--source", type=str, default=str(dataDir / "mei"), help="Directory containing MEI XML files.")
    args = parser.parse_args()

    sourceDir = Path(args.source)
    files = sorted(list(sourceDir.glob("*.xml")) + list(sourceDir.glob("*.mei")))
    if len(files) == 0:
        print(f"No .xml or .mei files in {sourceDir}", file=sys.stderr)
        return 1

    fileResults: list[dict[str, Any]] = []
    with openDb() as con:
        for meiPath in files:
            fileResults.append(validateFile(con, meiPath))
        orphanRows = findOrphanRows(con, {p.name for p in files})

    totalChecks = sum(len(r["checks"]) for r in fileResults)
    failedChecks = [
        {"file": r["file"], **c}
        for r in fileResults
        for c in r["checks"]
        if not c["ok"]
    ]
    filesPassed = sum(1 for r in fileResults if r["passed"])

    report = {
        "files_checked": len(fileResults),
        "files_passed": filesPassed,
        "total_checks": totalChecks,
        "failed_checks": failedChecks,
        "orphan_db_rows": orphanRows,
        "files": fileResults,
    }
    reportPath = dataDir / "validation_report.json"
    with open(reportPath, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print(f"Validated {len(fileResults)} files: {filesPassed} passed, {len(fileResults) - filesPassed} failed.")
    print(f"Checks run: {totalChecks}, failed: {len(failedChecks)}.")
    for failure in failedChecks:
        print(f"  FAIL {failure['file']} {failure['name']}: {failure['detail']}", file=sys.stderr)
    if orphanRows:
        print(f"Orphan database rows (source file missing): {', '.join(orphanRows)}", file=sys.stderr)
    print(f"Full report: {reportPath}")

    if failedChecks or orphanRows:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
