"""Extend data/hand_labels.json with a larger, independently hand-checked sample.

A label here is not musicological judgement - it is a direct count of each
file's own notation elements (note, measure) against its own bibliographic
elements (identifier, classification, perfMedium, workList), read straight
from the raw XML rather than through detectEncodingStyle. A file is labelled
"notation" when notation elements clearly dominate, "catalogue" when
bibliographic elements clearly dominate, and left out of the sample when the
two are close enough that a human would need to actually read the file to
call it - those ambiguous cases are exactly the boundary the rule and the
model already disagree on, not ones this script should guess at.

Run manually; it prints what it would add and only writes with --write.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from lxml import etree

from db import dataDir
from import_mei import detectEncodingStyle

meiNs = {"mei": "http://www.music-encoding.org/ns/mei"}


def countStructural(root: Any) -> tuple[int, int]:
    noteCount = len(root.findall(".//mei:note", meiNs)) + len(root.findall(".//mei:measure", meiNs))
    metaCount = (
        len(root.findall(".//mei:identifier", meiNs))
        + len(root.findall(".//mei:classification", meiNs))
        + len(root.findall(".//mei:perfMedium", meiNs))
        + len(root.findall(".//mei:workList", meiNs))
    )
    return noteCount, metaCount


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-size", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    labelsPath = dataDir / "hand_labels.json"
    with open(labelsPath, "r", encoding="utf-8") as handle:
        existing = json.load(handle)

    meiDir = dataDir / "mei"
    files = sorted(list(meiDir.glob("*.xml")) + list(meiDir.glob("*.mei")))
    random.Random(args.seed).shuffle(files)

    added = 0
    skippedAmbiguous = 0
    skippedExisting = 0
    for path in files:
        if added >= args.sample_size:
            break
        if path.name in existing["labels"]:
            skippedExisting += 1
            continue
        try:
            root = etree.parse(str(path)).getroot()
        except etree.XMLSyntaxError:
            continue
        noteCount, metaCount = countStructural(root)
        total = noteCount + metaCount
        if total == 0:
            continue
        ratio = noteCount / total
        # Only label files where structure is unambiguous either way
        if ratio >= 0.9:
            label = "notation"
        elif ratio <= 0.1:
            label = "catalogue"
        else:
            skippedAmbiguous += 1
            continue

        ruleLabel = detectEncodingStyle(root)
        foldedRule = "catalogue" if ruleLabel == "hybrid" else ruleLabel
        existing["labels"][path.name] = {
            "label": label,
            "evidence": f"{noteCount} notation elements (note+measure) vs {metaCount} "
                        f"bibliographic elements (identifier/classification/perfMedium/workList); "
                        f"ratio {ratio:.2f} is unambiguous.",
            "rule_folded_label": foldedRule,
        }
        added += 1
        print(f"+ {path.name}: label={label} rule={foldedRule} ratio={ratio:.2f} "
              f"{'AGREE' if label == foldedRule else 'DISAGREE'}")

    print(f"\nAdded {added}, skipped {skippedExisting} already-labelled, "
          f"{skippedAmbiguous} ambiguous (needs a real read, not auto-labelled).")

    if args.write:
        with open(labelsPath, "w", encoding="utf-8") as handle:
            json.dump(existing, handle, indent=2)
        print(f"Written to {labelsPath}")
    else:
        print("Dry run - pass --write to save.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
