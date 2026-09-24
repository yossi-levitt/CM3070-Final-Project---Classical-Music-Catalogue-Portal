"""Ingest works that are spread across several MEI files, one movement per
file, using ingestMultiFileWork. Run this after the normal import_mei.py
pass. Currently handles one case: Weber's "Der Freischuetz" as encoded by
the Freischuetz Digital project, one file per movement.
"""
from __future__ import annotations

import sys
from pathlib import Path

from db import dataDir, openDb
from import_mei import ingestMultiFileWork


def main() -> int:
    meiDir = dataDir / "mei"
    movementFiles = sorted(
        meiDir.glob("freidi_core_mov*.xml"),
        key=lambda p: int(p.stem.replace("freidi_core_mov", "")),
    )
    if len(movementFiles) == 0:
        print("No freidi_core_mov*.xml files found; nothing to do.", file=sys.stderr)
        return 0

    with openDb() as con:
        report = ingestMultiFileWork(
            con,
            movementFiles,
            composerName="Carl Maria von Weber",
            workTitle="Der Freischuetz",
            genre="Opera",
        )

    print(f"Ingested '{report['work_title']}' as work id {report['work_id']} "
          f"with {len(report['movement_files'])} movements.")
    for warning in report["warnings"]:
        print(f"  warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
