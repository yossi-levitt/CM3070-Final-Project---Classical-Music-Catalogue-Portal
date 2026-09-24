from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from lxml import etree

from db import dataDir, initSchema, openDb
from export_mei import exportWork
from import_mei import detectEncodingStyle, ingestFile
from ml_genre import canonicaliseGenre, classifyGenreFeatures, featuriseWork, ruleBasedGenre, trainGenreModel
from ml_style import classifyRoot, trainStyleModel
from validate_mei import validateFile

# Trained lazily on first classification request
_styleModel: Any = None
_genreModel: Any = None


def getStyleModel() -> Any:
    global _styleModel
    if _styleModel is None:
        _styleModel = trainStyleModel()
    return _styleModel


def getGenreModel() -> Any:
    global _genreModel
    if _genreModel is None:
        _genreModel = trainGenreModel()
    return _genreModel

projectRoot = Path(__file__).resolve().parent.parent
frontendDir = projectRoot / "frontend"

app = Flask(__name__, static_folder=None)
CORS(app)

initSchema()


def rowToDict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def rowsToList(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(rowToDict(row))
    return out


@app.get("/api/health")
def health() -> Any:
    return jsonify({"status": "ok"})


@app.get("/api/composers")
def listComposers() -> Any:
    with openDb() as con:
        rows = con.execute(
            """
            SELECT c.id, c.name, c.birth_year, c.death_year,
                   COUNT(w.id) AS work_count
            FROM composer c
            LEFT JOIN work w ON w.composer_id = c.id
            GROUP BY c.id
            ORDER BY c.name
            """
        ).fetchall()
    return jsonify(rowsToList(rows))


@app.get("/api/composers/<int:composerId>")
def getComposer(composerId: int) -> Any:
    with openDb() as con:
        row = con.execute("SELECT * FROM composer WHERE id = ?", (composerId,)).fetchone()
        if row is None:
            return jsonify({"error": "composer not found"}), 404
        works = con.execute(
            "SELECT id, catalogue_number, title, year_composed FROM work WHERE composer_id = ? ORDER BY catalogue_number, title",
            (composerId,),
        ).fetchall()
    result = rowToDict(row)
    result["works"] = rowsToList(works)
    return jsonify(result)


@app.get("/api/works")
def listWorks() -> Any:
    queryText = request.args.get("q", "").strip()
    composerFilter = request.args.get("composer_id", type=int)
    genreFilter = request.args.get("genre", "").strip()
    instrumentFilter = request.args.get("instrument_id", type=int)
    limit = request.args.get("limit", default=50, type=int)
    offset = request.args.get("offset", default=0, type=int)

    whereSql = " WHERE 1 = 1"
    params: list[Any] = []

    if queryText != "":
        whereSql = whereSql + " AND (w.title LIKE ? OR w.subtitle LIKE ? OR w.catalogue_number LIKE ? OR c.name LIKE ?)"
        likeValue = f"%{queryText}%"
        params.append(likeValue)
        params.append(likeValue)
        params.append(likeValue)
        params.append(likeValue)

    if composerFilter is not None:
        whereSql = whereSql + " AND w.composer_id = ?"
        params.append(composerFilter)

    if genreFilter != "":
        whereSql = whereSql + " AND w.genre = ?"
        params.append(genreFilter)

    if instrumentFilter is not None:
        whereSql = whereSql + " AND EXISTS (SELECT 1 FROM work_instrument wi WHERE wi.work_id = w.id AND wi.instrument_id = ?)"
        params.append(instrumentFilter)

    countSql = "SELECT COUNT(*) FROM work w JOIN composer c ON c.id = w.composer_id" + whereSql
    listSql = (
        "SELECT w.id, w.catalogue_number, w.title, w.subtitle, w.genre,"
        " w.key_signature, w.year_composed, w.year_completed,"
        " c.id AS composer_id, c.name AS composer_name"
        " FROM work w JOIN composer c ON c.id = w.composer_id"
        + whereSql
        + " ORDER BY c.name, w.catalogue_number, w.title LIMIT ? OFFSET ?"
    )

    with openDb() as con:
        total = con.execute(countSql, params).fetchone()[0]
        rows = con.execute(listSql, params + [limit, offset]).fetchall()
    return jsonify({"works": rowsToList(rows), "total": total, "limit": limit, "offset": offset})


@app.get("/api/works/<int:workId>")
def getWork(workId: int) -> Any:
    with openDb() as con:
        row = con.execute(
            """
            SELECT w.*, c.name AS composer_name, c.birth_year, c.death_year
            FROM work w
            JOIN composer c ON c.id = w.composer_id
            WHERE w.id = ?
            """,
            (workId,),
        ).fetchone()
        if row is None:
            return jsonify({"error": "work not found"}), 404

        movements = con.execute(
            "SELECT sequence, title, tempo, key_signature, incipit FROM movement WHERE work_id = ? ORDER BY sequence",
            (workId,),
        ).fetchall()

        instruments = con.execute(
            """
            SELECT i.name, wi.count
            FROM work_instrument wi
            JOIN instrument i ON i.id = wi.instrument_id
            WHERE wi.work_id = ?
            ORDER BY i.name
            """,
            (workId,),
        ).fetchall()

        manuscripts = con.execute(
            "SELECT repository, shelf_mark, description, date_text FROM manuscript WHERE work_id = ? ORDER BY repository",
            (workId,),
        ).fetchall()

        performances = con.execute(
            "SELECT performance_date, venue, city, notes FROM performance WHERE work_id = ? ORDER BY performance_date",
            (workId,),
        ).fetchall()

    result = rowToDict(row)
    result["movements"] = rowsToList(movements)
    result["instruments"] = rowsToList(instruments)
    result["manuscripts"] = rowsToList(manuscripts)
    result["performances"] = rowsToList(performances)
    return jsonify(result)


@app.get("/api/works/<int:workId>/mei")
def exportWorkMei(workId: int) -> Any:
    with openDb() as con:
        payload = exportWork(con, workId)
    if payload is None:
        return jsonify({"error": "work not found"}), 404
    return Response(
        payload,
        mimetype="application/xml",
        headers={"Content-Disposition": f"attachment; filename=work_{workId}.catalogue.mei"},
    )


@app.get("/api/works/<int:workId>/source-mei")
def getSourceMei(workId: int) -> Any:
    with openDb() as con:
        row = con.execute("SELECT source_file FROM work WHERE id = ?", (workId,)).fetchone()
    if row is None:
        return jsonify({"error": "work not found"}), 404
    sourcePath = dataDir / "mei" / row["source_file"]
    if not sourcePath.exists():
        return jsonify({"error": f"source file missing: {row['source_file']}"}), 404
    return Response(sourcePath.read_bytes(), mimetype="application/xml")


@app.get("/api/works/<int:workId>/validation")
def validateWork(workId: int) -> Any:
    with openDb() as con:
        row = con.execute("SELECT source_file FROM work WHERE id = ?", (workId,)).fetchone()
        if row is None:
            return jsonify({"error": "work not found"}), 404
        sourcePath = dataDir / "mei" / row["source_file"]
        if not sourcePath.exists():
            return jsonify({"error": f"source file missing: {row['source_file']}"}), 404
        result = validateFile(con, sourcePath)
    checksPassed = sum(1 for c in result["checks"] if c["ok"])
    return jsonify({
        "work_id": workId,
        "source_file": row["source_file"],
        "passed": result["passed"],
        "checks_passed": checksPassed,
        "checks_total": len(result["checks"]),
        "checks": result["checks"],
    })


@app.get("/api/works/<int:workId>/classification")
def classifyWork(workId: int) -> Any:
    with openDb() as con:
        row = con.execute(
            "SELECT source_file, encoding_style FROM work WHERE id = ?", (workId,)
        ).fetchone()
    if row is None:
        return jsonify({"error": "work not found"}), 404
    sourcePath = dataDir / "mei" / row["source_file"]
    if not sourcePath.exists():
        return jsonify({"error": f"source file missing: {row['source_file']}"}), 404

    root = etree.parse(str(sourcePath)).getroot()
    ruleStyle = detectEncodingStyle(root)
    mlStyle, confidence = classifyRoot(getStyleModel(), root)
    # the classifier folds hybrid into catalogue, mirror that for the agreement check
    ruleForComparison = "catalogue" if ruleStyle == "hybrid" else ruleStyle
    return jsonify({
        "work_id": workId,
        "source_file": row["source_file"],
        "rule_style": ruleStyle,
        "ml_style": mlStyle,
        "ml_confidence": confidence,
        "agreement": mlStyle == ruleForComparison,
    })


@app.get("/api/works/<int:workId>/genre-classification")
def classifyWorkGenre(workId: int) -> Any:
    with openDb() as con:
        row = con.execute("SELECT genre FROM work WHERE id = ?", (workId,)).fetchone()
        if row is None:
            return jsonify({"error": "work not found"}), 404
        instrumentRows = con.execute(
            """
            SELECT i.name FROM work_instrument wi
            JOIN instrument i ON i.id = wi.instrument_id
            WHERE wi.work_id = ?
            """,
            (workId,),
        ).fetchall()
        movementCount = con.execute(
            "SELECT COUNT(*) FROM movement WHERE work_id = ?", (workId,)
        ).fetchone()[0]

    instrumentNames = [r["name"] for r in instrumentRows]
    features = featuriseWork(instrumentNames, len(instrumentNames), movementCount)
    ruleGenre = ruleBasedGenre(instrumentNames)
    mlGenre, confidence = classifyGenreFeatures(getGenreModel(), features)
    actualGenreCanonical = canonicaliseGenre(row["genre"]) if row["genre"] else None

    return jsonify({
        "work_id": workId,
        "instrument_count": len(instrumentNames),
        "movement_count": movementCount,
        "rule_genre": ruleGenre,
        "ml_genre": mlGenre,
        "ml_confidence": confidence,
        "agreement": ruleGenre == mlGenre,
        "actual_genre_raw": row["genre"],
        "actual_genre_canonical": actualGenreCanonical,
    })


@app.get("/api/validation")
def validateCorpus() -> Any:
    sourceDir = dataDir / "mei"
    files = sorted(list(sourceDir.glob("*.xml")) + list(sourceDir.glob("*.mei")))
    results = []
    with openDb() as con:
        for meiPath in files:
            results.append(validateFile(con, meiPath))
    totalChecks = sum(len(r["checks"]) for r in results)
    failed = [
        {"file": r["file"], "name": c["name"], "detail": c["detail"]}
        for r in results for c in r["checks"] if not c["ok"]
    ]
    return jsonify({
        "files_checked": len(results),
        "files_passed": sum(1 for r in results if r["passed"]),
        "checks_total": totalChecks,
        "checks_failed": len(failed),
        "failures": failed,
    })


@app.post("/api/upload")
def uploadMei() -> Any:
    uploaded = request.files.get("file")
    if uploaded is None or uploaded.filename == "":
        return jsonify({"error": "no file provided (multipart field 'file')"}), 400
    fileName = Path(uploaded.filename).name
    if not fileName.lower().endswith((".xml", ".mei")):
        return jsonify({"error": "only .xml or .mei files are accepted"}), 400

    uploadDir = dataDir / "mei"
    uploadDir.mkdir(parents=True, exist_ok=True)
    targetPath = uploadDir / fileName
    uploaded.save(str(targetPath))

    try:
        root = etree.parse(str(targetPath)).getroot()
    except etree.XMLSyntaxError as err:
        targetPath.unlink()
        return jsonify({"error": f"not well-formed XML: {err}"}), 400
    if not root.tag.endswith("}mei") and root.tag != "mei":
        targetPath.unlink()
        return jsonify({"error": "root element is not <mei>"}), 400

    detectedStyle = detectEncodingStyle(root)
    mlStyle, mlConfidence = classifyRoot(getStyleModel(), root)
    meiVersion = root.get("meiversion")

    with openDb() as con:
        report = ingestFile(con, targetPath)
        workRow = con.execute(
            "SELECT id, title FROM work WHERE source_file = ?", (fileName,)
        ).fetchone()

    return jsonify({
        "file": fileName,
        "status": report["status"],
        "detected_style": detectedStyle,
        "ml_style": mlStyle,
        "ml_confidence": mlConfidence,
        "mei_version": meiVersion,
        "warnings": report["warnings"],
        "field_coverage": report["field_coverage"],
        "work_id": workRow["id"] if workRow is not None else None,
        "title": workRow["title"] if workRow is not None else None,
    }), 201


@app.get("/api/instruments")
def listInstruments() -> Any:
    with openDb() as con:
        rows = con.execute(
            """
            SELECT i.id, i.name, COUNT(wi.work_id) AS work_count
            FROM instrument i
            JOIN work_instrument wi ON wi.instrument_id = i.id
            GROUP BY i.id
            ORDER BY i.name
            """
        ).fetchall()
    return jsonify(rowsToList(rows))


@app.get("/api/genres")
def listGenres() -> Any:
    with openDb() as con:
        rows = con.execute(
            "SELECT DISTINCT genre FROM work WHERE genre IS NOT NULL AND genre != '' ORDER BY genre"
        ).fetchall()
    out: list[str] = []
    for row in rows:
        value = row["genre"]
        if value is not None:
            out.append(value)
    return jsonify(out)


@app.get("/api/stats")
def stats() -> Any:
    with openDb() as con:
        composerCount = con.execute("SELECT COUNT(*) AS n FROM composer").fetchone()["n"]
        workCount = con.execute("SELECT COUNT(*) AS n FROM work").fetchone()["n"]
        movementCount = con.execute("SELECT COUNT(*) AS n FROM movement").fetchone()["n"]
        manuscriptCount = con.execute("SELECT COUNT(*) AS n FROM manuscript").fetchone()["n"]
    return jsonify({
        "composers": composerCount,
        "works": workCount,
        "movements": movementCount,
        "manuscripts": manuscriptCount,
    })


@app.get("/")
def serveIndex() -> Any:
    return send_from_directory(str(frontendDir), "index.html")


@app.get("/<path:filename>")
def serveStatic(filename: str) -> Any:
    target = frontendDir / filename
    if not target.exists():
        return send_from_directory(str(frontendDir), "index.html")
    return send_from_directory(str(frontendDir), filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
