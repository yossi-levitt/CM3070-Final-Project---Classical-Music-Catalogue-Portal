from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import re

from lxml import etree

from db import dataDir, initSchema, openDb

_whitespaceRun = re.compile(r"\s+")

meiNs = {"mei": "http://www.music-encoding.org/ns/mei"}

# Work fields tracked in the per-file coverage report
workFieldNames = [
    "catalogue_number",
    "title",
    "subtitle",
    "genre",
    "key_signature",
    "year_composed",
    "year_completed",
    "dedication",
    "notes",
]


def text(node: Any) -> str | None:
    if node is None:
        return None
    if isinstance(node, str):
        stripped = _whitespaceRun.sub(" ", node).strip()
        if stripped == "":
            return None
        return stripped
    # Join child text chunks with spaces so multi-element titles stay readable.
    # Each chunk also has its own internal whitespace collapsed, since a source
    # file pretty-printed across multiple lines can put newlines and indentation
    # inside a single text node (e.g. "1.\n    Violine").
    chunks = [_whitespaceRun.sub(" ", chunk).strip() for chunk in node.itertext()]
    value = " ".join(chunk for chunk in chunks if chunk != "")
    if value == "":
        return None
    return value


def findFirst(root: Any, xpath: str) -> Any:
    results = root.xpath(xpath, namespaces=meiNs)
    if results is None:
        return None
    if len(results) == 0:
        return None
    return results[0]


def findAll(root: Any, xpath: str) -> list[Any]:
    results = root.xpath(xpath, namespaces=meiNs)
    if results is None:
        return []
    return results


def parseYear(raw: str | None) -> int | None:
    if raw is None:
        return None
    digits = ""
    for char in raw:
        if char.isdigit():
            digits = digits + char
            if len(digits) == 4:
                break
        else:
            if len(digits) > 0:
                break
    if len(digits) == 4:
        return int(digits)
    return None


def countNotationNotes(root: Any) -> int:
    return len(findAll(root, ".//mei:music//mei:note"))


def detectEncodingStyle(root: Any) -> str:
    hasWorkMetadata = findFirst(root, ".//mei:workList/mei:work") is not None or findFirst(root, ".//mei:work/mei:identifier") is not None
    hasNotation = findFirst(root, ".//mei:music//mei:note") is not None
    if hasWorkMetadata and hasNotation:
        return "hybrid"
    if hasNotation:
        return "notation"
    return "catalogue"


def extractComposer(root: Any) -> tuple[str, int | None, int | None]:
    composerNode = findFirst(root, ".//mei:fileDesc//mei:respStmt/mei:persName[@role='composer']")
    if composerNode is None:
        composerNode = findFirst(root, ".//mei:fileDesc//mei:composer")
    if composerNode is None:
        composerNode = findFirst(root, ".//mei:titleStmt//mei:persName[@role='composer']")
    if composerNode is None:
        composerNode = findFirst(root, ".//mei:fileDesc//mei:respStmt/mei:persName[@role='creator']")
    if composerNode is None:
        composerNode = findFirst(root, ".//mei:fileDesc//mei:respStmt/mei:persName[@role='author']")
    if composerNode is None:
        composerNode = findFirst(root, ".//mei:work/mei:contributor/mei:persName[@role='composer']")

    name = text(composerNode)
    if name is None:
        name = "Unknown"

    birth = None
    death = None
    if composerNode is not None:
        birthAttr = composerNode.get("startdate")
        deathAttr = composerNode.get("enddate")
        if birthAttr is not None:
            birth = parseYear(birthAttr)
        if deathAttr is not None:
            death = parseYear(deathAttr)

    return name, birth, death


def extractWorkFields(root: Any, sourceFile: str) -> dict[str, Any]:
    titleNode = findFirst(root, ".//mei:fileDesc//mei:titleStmt/mei:title[not(@type) or @type='main']")
    if titleNode is None:
        titleNode = findFirst(root, ".//mei:fileDesc//mei:titleStmt/mei:title")
    title = text(titleNode)
    if title is None:
        title = sourceFile

    subtitleNode = findFirst(root, ".//mei:fileDesc//mei:titleStmt/mei:title[@type='subordinate']")
    if subtitleNode is None:
        subtitleNode = findFirst(root, ".//mei:fileDesc//mei:titleStmt/mei:title[@type='subtitle']")
    subtitle = text(subtitleNode)

    # Some sources carry several numbering schemes side by side on one work
    # (Opus, CNW, CNU...); prefer the one named after the catalogue itself.
    catalogueNode = findFirst(root, ".//mei:work/mei:identifier[@label='CNW']")
    if catalogueNode is None:
        catalogueNode = findFirst(root, ".//mei:work/mei:identifier")
    if catalogueNode is None:
        catalogueNode = findFirst(root, ".//mei:workList//mei:identifier")
    if catalogueNode is None:
        catalogueNode = findFirst(root, ".//mei:fileDesc//mei:seriesStmt/mei:identifier")
    catalogueNumber = text(catalogueNode)

    genreNode = findFirst(root, ".//mei:work//mei:term[@classcode='genre']")
    if genreNode is None:
        genreNode = findFirst(root, ".//mei:work//mei:classification//mei:term")
    if genreNode is None:
        genreNode = findFirst(root, ".//mei:fileDesc//mei:classification//mei:term")
    genre = text(genreNode)

    keyNode = findFirst(root, ".//mei:work//mei:key")
    if keyNode is None:
        keyNode = findFirst(root, ".//mei:scoreDef/@key.sig")
    keySignature = text(keyNode)

    composedNode = findFirst(root, ".//mei:work//mei:creation//mei:date")
    if composedNode is None:
        composedNode = findFirst(root, ".//mei:fileDesc//mei:pubStmt//mei:date")
    if composedNode is None:
        composedNode = findFirst(root, ".//mei:fileDesc//mei:editionStmt//mei:date")
    yearComposed = None
    yearCompleted = None
    if composedNode is not None:
        startAttr = composedNode.get("isodate")
        if startAttr is None:
            startAttr = composedNode.get("notbefore")
        endAttr = composedNode.get("notafter")
        if startAttr is not None:
            yearComposed = parseYear(startAttr)
        if endAttr is not None:
            yearCompleted = parseYear(endAttr)
        if yearComposed is None:
            yearComposed = parseYear(text(composedNode))

    dedicationNode = findFirst(root, ".//mei:work//mei:dedicatee")
    if dedicationNode is None:
        dedicationNode = findFirst(root, ".//mei:work//mei:dedication")
    dedication = text(dedicationNode)

    notesNode = findFirst(root, ".//mei:work//mei:notesStmt//mei:annot")
    notes = text(notesNode)

    return {
        "catalogue_number": catalogueNumber,
        "title": title,
        "subtitle": subtitle,
        "genre": genre,
        "key_signature": keySignature,
        "year_composed": yearComposed,
        "year_completed": yearCompleted,
        "dedication": dedication,
        "notes": notes,
        "encoding_style": detectEncodingStyle(root),
        "source_file": sourceFile,
        "note_count": countNotationNotes(root),
    }


def extractMovements(root: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    sequence = 0
    for node in findAll(root, ".//mei:work//mei:expressionList//mei:expression"):
        sequence = sequence + 1
        titleNode = findFirst(node, ".//mei:title")
        tempoNode = findFirst(node, ".//mei:tempo")
        keyNode = findFirst(node, ".//mei:key")
        # Only the direct text is kept, not every <p> for every language variant
        incipitNode = findFirst(node, ".//mei:incip//mei:incipText/mei:p")
        out.append({
            "sequence": sequence,
            "title": text(titleNode),
            "tempo": text(tempoNode),
            "key_signature": text(keyNode),
            "incipit": text(incipitNode),
        })
    if len(out) == 0:
        for node in findAll(root, ".//mei:work//mei:component"):
            sequence = sequence + 1
            titleNode = findFirst(node, ".//mei:title")
            incipitNode = findFirst(node, ".//mei:incip//mei:incipText/mei:p")
            out.append({
                "sequence": sequence,
                "title": text(titleNode),
                "tempo": None,
                "key_signature": None,
                "incipit": text(incipitNode),
            })
    if len(out) == 0:
        mdivs = findAll(root, ".//mei:music//mei:mdiv")
        if len(mdivs) > 1:
            for node in mdivs:
                sequence = sequence + 1
                label = node.get("label")
                if label is None:
                    label = node.get("n")
                out.append({
                    "sequence": sequence,
                    "title": label,
                    "tempo": None,
                    "key_signature": None,
                    "incipit": None,
                })
    return out


def extractInstruments(root: Any) -> list[tuple[str, int | None]]:
    out: list[tuple[str, int | None]] = []
    for node in findAll(root, ".//mei:work//mei:perfMedium//mei:instrumentation//mei:instrVoice"):
        name = text(node)
        if name is None:
            continue
        countAttr = node.get("count")
        count = None
        if countAttr is not None:
            try:
                count = int(countAttr)
            except ValueError:
                count = None
        out.append((name, count))
    if len(out) == 0:
        for node in findAll(root, ".//mei:work//mei:perfMedium//mei:perfRes"):
            name = text(node)
            if name is None:
                continue
            out.append((name, None))
    if len(out) == 0:
        seen: set[str] = set()
        for node in findAll(root, ".//mei:scoreDef//mei:staffDef"):
            name = node.get("label")
            if name is None:
                continue
            name = name.strip()
            if name == "":
                continue
            if name in seen:
                continue
            seen.add(name)
            out.append((name, None))
    return out


def extractManuscripts(root: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in findAll(root, ".//mei:source"):
        repoNode = findFirst(node, ".//mei:repository")
        shelfNode = findFirst(node, ".//mei:identifier[@type='shelfmark']")
        if shelfNode is None:
            shelfNode = findFirst(node, ".//mei:identifier")
        descriptionNode = findFirst(node, ".//mei:physDesc")
        if descriptionNode is None:
            descriptionNode = findFirst(node, ".//mei:p")
        dateNode = findFirst(node, ".//mei:date")
        repo = text(repoNode)
        shelf = text(shelfNode)
        description = text(descriptionNode)
        dateText = text(dateNode)
        if repo is None and shelf is None and description is None:
            continue
        out.append({
            "repository": repo,
            "shelf_mark": shelf,
            "description": description,
            "date_text": dateText,
        })
    return out


def extractPerformances(root: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in findAll(root, ".//mei:eventList//mei:event[@type='performance']"):
        dateNode = findFirst(node, ".//mei:date")
        venueNode = findFirst(node, ".//mei:geogName[@type='venue']")
        if venueNode is None:
            venueNode = findFirst(node, ".//mei:corpName")
        cityNode = findFirst(node, ".//mei:geogName[@type='city']")
        notesNode = findFirst(node, ".//mei:p")
        out.append({
            "performance_date": text(dateNode),
            "venue": text(venueNode),
            "city": text(cityNode),
            "notes": text(notesNode),
        })
    if len(out) == 0:
        # The eventList itself (not each event) carries type="performances" here,
        # and venue/city use @role rather than @type.
        for node in findAll(root, ".//mei:eventList[@type='performances']/mei:event"):
            dateNode = findFirst(node, ".//mei:date")
            venueNode = findFirst(node, ".//mei:geogName[@role='venue']")
            cityNode = findFirst(node, ".//mei:geogName[@role='place']")
            notesNode = findFirst(node, ".//mei:desc")
            out.append({
                "performance_date": text(dateNode),
                "venue": text(venueNode),
                "city": text(cityNode),
                "notes": text(notesNode),
            })
    if len(out) == 0:
        for node in findAll(root, ".//mei:performance"):
            dateNode = findFirst(node, ".//mei:date")
            venueNode = findFirst(node, ".//mei:geogName")
            notesNode = findFirst(node, ".//mei:p")
            out.append({
                "performance_date": text(dateNode),
                "venue": text(venueNode),
                "city": None,
                "notes": text(notesNode),
            })
    return out


def ensureComposer(con, name: str, birth: int | None, death: int | None) -> int:
    row = con.execute("SELECT id FROM composer WHERE name = ?", (name,)).fetchone()
    if row is not None:
        return row["id"]
    cur = con.execute(
        "INSERT INTO composer (name, birth_year, death_year) VALUES (?, ?, ?)",
        (name, birth, death),
    )
    return int(cur.lastrowid)


def ensureInstrument(con, name: str) -> int:
    row = con.execute("SELECT id FROM instrument WHERE name = ?", (name,)).fetchone()
    if row is not None:
        return row["id"]
    cur = con.execute("INSERT INTO instrument (name) VALUES (?)", (name,))
    return int(cur.lastrowid)


def upsertWork(con, composerId: int, workFields: dict[str, Any]) -> int:
    catalogueNumber = workFields["catalogue_number"]
    if catalogueNumber is not None:
        existing = con.execute(
            "SELECT id FROM work WHERE composer_id = ? AND catalogue_number = ?",
            (composerId, catalogueNumber),
        ).fetchone()
        if existing is not None:
            con.execute("DELETE FROM work WHERE id = ?", (existing["id"],))

    cur = con.execute(
        """
        INSERT INTO work (composer_id, catalogue_number, title, subtitle, genre,
            key_signature, year_composed, year_completed, dedication, notes,
            encoding_style, source_file, note_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            composerId,
            workFields["catalogue_number"],
            workFields["title"],
            workFields["subtitle"],
            workFields["genre"],
            workFields["key_signature"],
            workFields["year_composed"],
            workFields["year_completed"],
            workFields["dedication"],
            workFields["notes"],
            workFields["encoding_style"],
            workFields["source_file"],
            workFields.get("note_count", 0),
        ),
    )
    return int(cur.lastrowid)


def ingestMultiFileWork(
    con,
    files: list[Path],
    composerName: str,
    workTitle: str,
    catalogueNumber: str | None = None,
    genre: str | None = None,
) -> dict[str, Any]:
    """Ingest several MEI files as ONE work, one movement per file.

    For a work spread across many files (e.g. one opera encoded as one file
    per movement), the per-work identity model in upsertWork assumes one file
    is one work; giving each movement file to the normal import path would
    make every movement overwrite the previous one under the same composer
    and catalogue number. This function instead creates a single work row
    from caller-supplied bibliographic fields (the individual files' own
    headers describe the encoding project, not the opera, so they are not a
    reliable source for the work-level title and composer) and inserts one
    movement per file, each carrying its own source_file so validate_mei.py
    can still check it against its own content.
    """
    report: dict[str, Any] = {"file": workTitle, "work_title": workTitle, "movement_files": [], "warnings": []}

    composerId = ensureComposer(con, composerName, None, None)

    # Parsed once up front (rather than inside the insert loop below) so the
    # note count across all movements is known before the work row itself is
    # inserted - the frontend uses that total to decide whether a notation
    # preview is worth offering at all.
    parsedMovements: list[tuple[Path, Any, dict[str, Any]]] = []
    totalNoteCount = 0
    for sequence, path in enumerate(files, start=1):
        try:
            root = etree.parse(str(path)).getroot()
        except etree.XMLSyntaxError as err:
            warn(report, f"{path.name}: XML syntax error, movement skipped: {err}")
            continue
        movementFields = extractWorkFields(root, path.name)
        totalNoteCount = totalNoteCount + movementFields["note_count"]
        parsedMovements.append((path, root, movementFields))

    # source_file deliberately does not match any real file on disk: this
    # work's bibliographic fields are supplied by the caller, not extracted
    # from one file, so validate_mei.py's per-file checks (which compare a
    # work row against a fresh extraction of the file its source_file names)
    # do not apply to it the way they do to every other work. Each real file
    # is still checked individually, as a movement (validateMovementFile).
    workFields = {
        "catalogue_number": catalogueNumber,
        "title": workTitle,
        "subtitle": None,
        "genre": genre,
        "key_signature": None,
        "year_composed": None,
        "year_completed": None,
        "dedication": None,
        "notes": None,
        "encoding_style": "hybrid",
        "source_file": f"(multi-file: {len(files)} movements, no single source file)",
        "note_count": totalNoteCount,
    }
    workId = upsertWork(con, composerId, workFields)

    for sequence, (path, root, movementFields) in enumerate(parsedMovements, start=1):
        title = movementFields["title"] if movementFields["title"] != path.name else f"Movement {sequence}"
        con.execute(
            "INSERT INTO movement (work_id, sequence, title, tempo, key_signature, source_file) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (workId, sequence, title, None, movementFields["key_signature"], path.name),
        )
        report["movement_files"].append(path.name)

        for instrumentName, count in extractInstruments(root):
            instrumentId = ensureInstrument(con, instrumentName)
            con.execute(
                "INSERT OR IGNORE INTO work_instrument (work_id, instrument_id, count) VALUES (?, ?, ?)",
                (workId, instrumentId, count),
            )

    report["work_id"] = workId
    return report


def buildFileReport(meiPath: Path) -> dict[str, Any]:
    return {
        "file": meiPath.name,
        "status": "ok",
        "warnings": [],
        "field_coverage": {},
        "counts": {},
    }


def warn(report: dict[str, Any], message: str) -> None:
    report["warnings"].append(message)
    print(f"  warning [{report['file']}]: {message}", file=sys.stderr)


def ingestFile(con, meiPath: Path) -> dict[str, Any]:
    report = buildFileReport(meiPath)
    try:
        tree = etree.parse(str(meiPath))
    except etree.XMLSyntaxError as err:
        report["status"] = "skipped"
        warn(report, f"XML syntax error, file skipped: {err}")
        return report

    root = tree.getroot()
    composerName, birth, death = extractComposer(root)
    if composerName == "Unknown":
        warn(report, "no composer element found, stored as 'Unknown'")

    workFields = extractWorkFields(root, meiPath.name)
    encodingStyle = workFields["encoding_style"]
    report["encoding_style"] = encodingStyle
    if workFields["title"] == meiPath.name:
        warn(report, "no title element found, filename used as title")

    # Notation-style files legitimately omit bibliographic fields - no warnings
    if encodingStyle == "catalogue":
        if workFields["catalogue_number"] is None:
            warn(report, "no catalogue number (mei:identifier) found")
        if workFields["genre"] is None:
            warn(report, "no genre classification found")
        if workFields["year_composed"] is None:
            warn(report, "no composition date found")

    for fieldName in workFieldNames:
        report["field_coverage"][fieldName] = workFields[fieldName] is not None

    composerId = ensureComposer(con, composerName, birth, death)
    workId = upsertWork(con, composerId, workFields)

    movements = extractMovements(root)
    instruments = extractInstruments(root)
    manuscripts = extractManuscripts(root)
    performances = extractPerformances(root)
    report["counts"] = {
        "movements": len(movements),
        "instruments": len(instruments),
        "manuscripts": len(manuscripts),
        "performances": len(performances),
    }
    if len(instruments) == 0:
        warn(report, "no instrumentation found (perfMedium/perfRes/staffDef all empty)")

    for movement in movements:
        con.execute(
            "INSERT INTO movement (work_id, sequence, title, tempo, key_signature, incipit) VALUES (?, ?, ?, ?, ?, ?)",
            (workId, movement["sequence"], movement["title"], movement["tempo"], movement["key_signature"], movement["incipit"]),
        )

    for instrumentName, count in instruments:
        instrumentId = ensureInstrument(con, instrumentName)
        con.execute(
            "INSERT OR IGNORE INTO work_instrument (work_id, instrument_id, count) VALUES (?, ?, ?)",
            (workId, instrumentId, count),
        )

    for manuscript in manuscripts:
        con.execute(
            "INSERT INTO manuscript (work_id, repository, shelf_mark, description, date_text) VALUES (?, ?, ?, ?, ?)",
            (workId, manuscript["repository"], manuscript["shelf_mark"], manuscript["description"], manuscript["date_text"]),
        )

    for performance in performances:
        con.execute(
            "INSERT INTO performance (work_id, performance_date, venue, city, notes) VALUES (?, ?, ?, ?, ?)",
            (workId, performance["performance_date"], performance["venue"], performance["city"], performance["notes"]),
        )

    return report


def summariseCoverage(fileReports: list[dict[str, Any]], style: str | None = None) -> dict[str, Any]:
    ingested = [r for r in fileReports if r["status"] == "ok"]
    if style is not None:
        ingested = [r for r in ingested if r.get("encoding_style") == style]
    coverage: dict[str, Any] = {}
    for fieldName in workFieldNames:
        present = sum(1 for r in ingested if r["field_coverage"].get(fieldName))
        coverage[fieldName] = {
            "present": present,
            "total": len(ingested),
            "percent": round(100.0 * present / len(ingested), 1) if ingested else 0.0,
        }
    return coverage


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest MEI XML files into the catalogue SQLite database.")
    parser.add_argument("--source", type=str, default=str(dataDir / "mei"), help="Directory containing MEI XML files.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate the database before ingest.")
    args = parser.parse_args()

    sourceDir = Path(args.source)
    if not sourceDir.exists():
        print(f"Source directory not found: {sourceDir}", file=sys.stderr)
        return 1

    if args.reset:
        from db import dbPath as targetDb
        if targetDb.exists():
            targetDb.unlink()

    initSchema()

    files = sorted(list(sourceDir.glob("*.xml")) + list(sourceDir.glob("*.mei")))
    # Movement files of a single multi-file work (e.g. one opera encoded as one
    # file per movement) are ingested separately by import_multi_file_works.py,
    # which creates one work row with one movement per file; giving them to
    # the per-file loop below would import each as its own top-level work and
    # have each overwrite the last under the same composer and catalogue number.
    files = [f for f in files if not f.name.startswith("freidi_core_mov")]
    if len(files) == 0:
        print(f"No .xml or .mei files in {sourceDir}", file=sys.stderr)
        return 1

    fileReports: list[dict[str, Any]] = []
    with openDb() as con:
        for meiPath in files:
            print(f"  ingesting: {meiPath.name}")
            fileReports.append(ingestFile(con, meiPath))

    total = sum(1 for r in fileReports if r["status"] == "ok")
    skipped = len(fileReports) - total
    warningCount = sum(len(r["warnings"]) for r in fileReports)

    styles = sorted({r["encoding_style"] for r in fileReports if r.get("encoding_style")})
    importReport = {
        "files_ingested": total,
        "files_skipped": skipped,
        "warning_count": warningCount,
        "field_coverage": summariseCoverage(fileReports),
        "field_coverage_by_style": {s: summariseCoverage(fileReports, s) for s in styles},
        "files": fileReports,
    }
    reportPath = dataDir / "import_report.json"
    with open(reportPath, "w", encoding="utf-8") as handle:
        json.dump(importReport, handle, indent=2)

    print(f"Done. Ingested {total} works, skipped {skipped}, {warningCount} warnings.")
    print("Field coverage across ingested files:")
    for fieldName, stats in importReport["field_coverage"].items():
        print(f"  {fieldName}: {stats['present']}/{stats['total']} ({stats['percent']}%)")
    print(f"Full report: {reportPath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
