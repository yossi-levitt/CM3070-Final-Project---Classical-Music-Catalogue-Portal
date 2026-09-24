"""Export works from the catalogue database as catalogue-style MEI 5.1 XML.

This is the conversion half of the pipeline: any imported work, whatever the
style or MEI version of its source file, can be regenerated as a clean,
bibliographic (catalogue-style) MEI document built from the relational data.

CLI: python export_mei.py --work-id 3           (single file to stdout)
     python export_mei.py --all --out ../data/export
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from lxml import etree

from db import dataDir, openDb

meiUri = "http://www.music-encoding.org/ns/mei"
mei = "{%s}" % meiUri


def sub(parent: Any, tag: str, textValue: str | None = None, **attrs: str) -> Any:
    node = etree.SubElement(parent, mei + tag)
    for key, value in attrs.items():
        node.set(key.replace("_", "."), value)
    if textValue is not None:
        node.text = textValue
    return node


def fetchWorkBundle(con, workId: int) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT w.*, c.name AS composer_name, c.birth_year, c.death_year
        FROM work w JOIN composer c ON c.id = w.composer_id
        WHERE w.id = ?
        """,
        (workId,),
    ).fetchone()
    if row is None:
        return None
    return {
        "work": row,
        "movements": con.execute(
            "SELECT sequence, title, tempo, key_signature FROM movement WHERE work_id = ? ORDER BY sequence",
            (workId,),
        ).fetchall(),
        "instruments": con.execute(
            """
            SELECT i.name, wi.count FROM work_instrument wi
            JOIN instrument i ON i.id = wi.instrument_id
            WHERE wi.work_id = ? ORDER BY i.name
            """,
            (workId,),
        ).fetchall(),
        "manuscripts": con.execute(
            "SELECT repository, shelf_mark, description, date_text FROM manuscript WHERE work_id = ? ORDER BY id",
            (workId,),
        ).fetchall(),
        "performances": con.execute(
            "SELECT performance_date, venue, city, notes FROM performance WHERE work_id = ? ORDER BY id",
            (workId,),
        ).fetchall(),
    }


def buildMeiDocument(bundle: dict[str, Any]) -> Any:
    work = bundle["work"]
    root = etree.Element(mei + "mei", nsmap={None: meiUri})
    root.set("meiversion", "5.1")

    head = sub(root, "meiHead")
    fileDesc = sub(head, "fileDesc")
    titleStmt = sub(fileDesc, "titleStmt")
    sub(titleStmt, "title", work["title"], type="main")
    if work["subtitle"]:
        sub(titleStmt, "title", work["subtitle"], type="subordinate")

    respStmt = sub(titleStmt, "respStmt")
    persName = sub(respStmt, "persName", work["composer_name"], role="composer")
    if work["birth_year"]:
        persName.set("startdate", str(work["birth_year"]))
    if work["death_year"]:
        persName.set("enddate", str(work["death_year"]))

    pubStmt = sub(fileDesc, "pubStmt")
    sub(pubStmt, "publisher", "Classical Music Catalogue Portal")
    sub(pubStmt, "availability", "Generated from the catalogue database; see source_file for provenance.")

    sourceDesc = sub(fileDesc, "sourceDesc")
    for manuscript in bundle["manuscripts"]:
        source = sub(sourceDesc, "source")
        bibl = sub(source, "bibl")
        if manuscript["repository"]:
            sub(bibl, "repository", manuscript["repository"])
        if manuscript["shelf_mark"]:
            sub(bibl, "identifier", manuscript["shelf_mark"], type="shelfmark")
        if manuscript["date_text"]:
            sub(bibl, "date", manuscript["date_text"])
        if manuscript["description"]:
            sub(source, "physDesc").append(etree.fromstring(
                f'<p xmlns="{meiUri}">{escapeText(manuscript["description"])}</p>'
            ))

    workList = sub(head, "workList")
    workNode = sub(workList, "work")
    if work["catalogue_number"]:
        sub(workNode, "identifier", work["catalogue_number"])
    sub(workNode, "title", work["title"])
    if work["key_signature"]:
        sub(workNode, "key", work["key_signature"])
    if work["year_composed"] or work["year_completed"]:
        creation = sub(workNode, "creation")
        dateText = str(work["year_composed"]) if work["year_composed"] else None
        dateNode = sub(creation, "date", dateText)
        if work["year_composed"] and work["year_completed"]:
            dateNode.set("notbefore", str(work["year_composed"]))
            dateNode.set("notafter", str(work["year_completed"]))
        elif work["year_composed"]:
            dateNode.set("isodate", str(work["year_composed"]))
        else:
            dateNode.set("notafter", str(work["year_completed"]))
    if work["genre"]:
        classification = sub(workNode, "classification")
        termList = sub(classification, "termList")
        sub(termList, "term", work["genre"], classcode="genre")
    if work["dedication"]:
        sub(workNode, "dedicatee", work["dedication"])
    if work["notes"]:
        notesStmt = sub(workNode, "notesStmt")
        sub(notesStmt, "annot", work["notes"])

    if bundle["instruments"]:
        perfMedium = sub(workNode, "perfMedium")
        instrumentation = sub(perfMedium, "instrumentation")
        for instrument in bundle["instruments"]:
            voice = sub(instrumentation, "instrVoice", instrument["name"])
            if instrument["count"]:
                voice.set("count", str(instrument["count"]))

    if bundle["movements"]:
        expressionList = sub(workNode, "expressionList")
        for movement in bundle["movements"]:
            expression = sub(expressionList, "expression", n=str(movement["sequence"]))
            if movement["title"]:
                sub(expression, "title", movement["title"])
            if movement["tempo"]:
                sub(expression, "tempo", movement["tempo"])
            if movement["key_signature"]:
                sub(expression, "key", movement["key_signature"])

    if bundle["performances"]:
        history = sub(workNode, "history")
        eventList = sub(history, "eventList")
        for performance in bundle["performances"]:
            event = sub(eventList, "event", type="performance")
            if performance["performance_date"]:
                sub(event, "date", performance["performance_date"])
            if performance["venue"]:
                sub(event, "geogName", performance["venue"], type="venue")
            if performance["city"]:
                sub(event, "geogName", performance["city"], type="city")
            if performance["notes"]:
                sub(event, "p", performance["notes"])

    return root


def escapeText(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def serialise(root: Any) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def exportWork(con, workId: int) -> bytes | None:
    bundle = fetchWorkBundle(con, workId)
    if bundle is None:
        return None
    return serialise(buildMeiDocument(bundle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export works as catalogue-style MEI 5.1 XML.")
    parser.add_argument("--work-id", type=int, help="Export a single work to stdout.")
    parser.add_argument("--all", action="store_true", help="Export every work.")
    parser.add_argument("--out", type=str, default=str(dataDir / "export"), help="Output directory for --all.")
    args = parser.parse_args()

    with openDb() as con:
        if args.work_id is not None:
            payload = exportWork(con, args.work_id)
            if payload is None:
                print(f"No work with id {args.work_id}", file=sys.stderr)
                return 1
            sys.stdout.buffer.write(payload)
            return 0

        if args.all:
            outDir = Path(args.out)
            outDir.mkdir(parents=True, exist_ok=True)
            rows = con.execute("SELECT id, source_file FROM work ORDER BY id").fetchall()
            for row in rows:
                payload = exportWork(con, row["id"])
                stem = Path(row["source_file"]).stem if row["source_file"] else f"work_{row['id']}"
                (outDir / f"{stem}.catalogue.mei").write_bytes(payload)
            print(f"Exported {len(rows)} works to {outDir}")
            return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
