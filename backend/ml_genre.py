"""Machine-learned genre classifier from instrumentation.

The corpus's own `genre` field is real metadata, but it is noisy: five
languages and two numbering schemes for the same handful of concepts
("Vocal music" / "Vokalmusik" / "782 Vocal music"), plus movement-level
labels from the CRIM mass corpus ("Kyrie", "Sanctus"...) sitting alongside
work-level genres. canonicaliseGenre() collapses that into a small set of
comparable categories - a deterministic lookup, not a prediction, so it
supplies ground truth rather than pre-empting the task below.

The actual ML task is harder than the encoding-style classifier: predict
that canonical genre purely from instrumentation (which instrument families
are present, how many instruments, how many movements) - a different input
space from the genre text itself, so there is no risk of the model just
re-reading its own label. ruleBasedGenre() gives a hand-written baseline to
compare the trained model against, the same pattern used for encoding style.

Writes data/ml_genre_report.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from db import dataDir, openDb

GENRE_RULES: list[tuple[str, str]] = [
    ("kyrie", "vocal_choral"),
    ("gloria", "vocal_choral"),
    ("credo", "vocal_choral"),
    ("sanctus", "vocal_choral"),
    ("agnus dei", "vocal_choral"),
    ("ordinarium missae", "vocal_choral"),
    ("missa", "vocal_choral"),
    ("motet", "vocal_choral"),
    ("madrigal", "vocal_choral"),
    ("chanson", "vocal_choral"),
    ("vokal", "vocal_choral"),
    ("vocal", "vocal_choral"),
    ("lied", "vocal_choral"),
    ("song", "vocal_choral"),
    ("orgel", "keyboard_organ"),
    ("organ", "keyboard_organ"),
    ("klavier", "keyboard_organ"),
    ("piano", "keyboard_organ"),
    ("keyboard", "keyboard_organ"),
    ("sinfonie", "orchestral_stage"),
    ("symphon", "orchestral_stage"),
    ("stage", "orchestral_stage"),
    ("opera", "orchestral_stage"),
    ("streichquartett", "chamber_instrumental"),
    ("quartet", "chamber_instrumental"),
    ("chamber", "chamber_instrumental"),
    ("gitarre", "chamber_instrumental"),
    ("wind instrument", "chamber_instrumental"),
    ("instrument", "chamber_instrumental"),
]

GENRE_CLASSES = ["vocal_choral", "keyboard_organ", "orchestral_stage", "chamber_instrumental", "other"]


def canonicaliseGenre(raw: str | None) -> str:
    if raw is None or raw.strip() == "":
        return "other"
    lowered = raw.strip().lower()
    for needle, canonical in GENRE_RULES:
        if needle in lowered:
            return canonical
    return "other"


INSTRUMENT_RULES: list[tuple[str, str]] = [
    ("sopran", "voice"), ("alt", "voice"), ("tenor", "voice"), ("bass", "voice"),
    ("voice", "voice"), ("voix", "voice"), ("cantus", "voice"), ("discant", "voice"),
    ("superius", "voice"), ("contratenor", "voice"), ("bassus", "voice"), ("choir", "voice"),
    ("coro", "voice"), (" s.", "voice"), (" a.", "voice"), (" t.", "voice"), (" b.", "voice"),
    ("violin", "violin"), ("geige", "violin"),
    ("viola", "viola"), ("bratsche", "viola"),
    ("violoncell", "cello"), ("cello", "cello"),
    ("contrabass", "double_bass"), ("double bass", "double_bass"), ("kontrabass", "double_bass"),
    ("piano", "piano"), ("pf.", "piano"), ("klavier", "piano"), ("pianoforte", "piano"),
    ("organ", "organ"), ("orgel", "organ"),
    ("flute", "woodwind"), ("flöte", "woodwind"), ("oboe", "woodwind"), ("clarinet", "woodwind"),
    ("klarinette", "woodwind"), ("bassoon", "woodwind"), ("fagott", "woodwind"),
    ("horn", "brass"), ("trumpet", "brass"), ("trompete", "brass"), ("trombone", "brass"),
    ("posaune", "brass"), ("tuba", "brass"),
    ("guitar", "other_instrument"), ("gitarre", "other_instrument"), ("harp", "other_instrument"),
]

INSTRUMENT_FAMILIES = ["voice", "violin", "viola", "cello", "double_bass", "piano", "organ",
                        "woodwind", "brass", "other_instrument"]

_bracketRun = re.compile(r"[\[\]\(\)]")


def canonicaliseInstrument(raw: str) -> str:
    cleaned = _bracketRun.sub("", raw).strip().lower()
    padded = f" {cleaned} "
    for needle, family in INSTRUMENT_RULES:
        if needle in padded:
            return family
    return "other_instrument"


def featuriseWork(instrumentNames: list[str], instrumentCount: int, movementCount: int) -> list[float]:
    families = {canonicaliseInstrument(name) for name in instrumentNames}
    familyVector = [1.0 if family in families else 0.0 for family in INSTRUMENT_FAMILIES]
    return familyVector + [float(instrumentCount), float(movementCount)]


featureNames = INSTRUMENT_FAMILIES + ["instrument_count", "movement_count"]


def ruleBasedGenre(instrumentNames: list[str]) -> str:
    families = {canonicaliseInstrument(name) for name in instrumentNames}
    instrumentalFamilies = families - {"voice"}
    if "voice" in families and len(instrumentalFamilies) <= 1:
        return "vocal_choral"
    if families.issubset({"piano"}) or families.issubset({"organ"}) or families.issubset({"piano", "organ"}):
        return "keyboard_organ"
    if len(families) == 0:
        return "other"
    if len(families) <= 3:
        return "chamber_instrumental"
    return "orchestral_stage"


def loadGenreDataset(con: Any) -> tuple[list[list[float]], list[str], list[int], list[str]]:
    rows = con.execute(
        """
        SELECT w.id, w.genre,
               (SELECT COUNT(*) FROM movement m WHERE m.work_id = w.id) AS movement_count
        FROM work w
        WHERE w.genre IS NOT NULL AND w.genre != ''
        """
    ).fetchall()

    features: list[list[float]] = []
    labels: list[str] = []
    workIds: list[int] = []
    rawGenres: list[str] = []
    for row in rows:
        instrumentRows = con.execute(
            "SELECT i.name FROM work_instrument wi JOIN instrument i ON i.id = wi.instrument_id WHERE wi.work_id = ?",
            (row["id"],),
        ).fetchall()
        instrumentNames = [r["name"] for r in instrumentRows]
        label = canonicaliseGenre(row["genre"])
        features.append(featuriseWork(instrumentNames, len(instrumentNames), row["movement_count"]))
        labels.append(label)
        workIds.append(row["id"])
        rawGenres.append(row["genre"])
    return features, labels, workIds, rawGenres


def trainGenreModel() -> Any:
    """Fit the random forest on the current corpus; returns the fitted model."""
    from sklearn.ensemble import RandomForestClassifier

    with openDb() as con:
        features, labels, _, _ = loadGenreDataset(con)
    model = RandomForestClassifier(n_estimators=200, random_state=42, class_weight="balanced")
    model.fit(features, labels)
    return model


def classifyGenreFeatures(model: Any, features: list[float]) -> tuple[str, float]:
    probabilities = model.predict_proba([features])[0]
    best = max(range(len(probabilities)), key=lambda i: probabilities[i])
    return str(model.classes_[best]), round(float(probabilities[best]), 3)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and evaluate the instrumentation-based genre classifier.")
    args = parser.parse_args()

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import confusion_matrix
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
    except ImportError:
        print("scikit-learn is not installed: pip install scikit-learn", file=sys.stderr)
        return 1

    with openDb() as con:
        features, labels, workIds, rawGenres = loadGenreDataset(con)
        instrumentLookup = {}
        for workId in workIds:
            rows = con.execute(
                "SELECT i.name FROM work_instrument wi JOIN instrument i ON i.id = wi.instrument_id WHERE wi.work_id = ?",
                (workId,),
            ).fetchall()
            instrumentLookup[workId] = [r["name"] for r in rows]

    if len(set(labels)) < 2:
        print("Need at least two genre classes in the corpus to train.", file=sys.stderr)
        return 1

    classOrder = sorted(set(labels))
    ruleLabels = [ruleBasedGenre(instrumentLookup[wid]) for wid in workIds]
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    models = {
        "logistic_regression": LogisticRegression(max_iter=2000),
        "random_forest": RandomForestClassifier(n_estimators=200, random_state=42, class_weight="balanced"),
    }

    results: dict[str, Any] = {}
    for modelName, model in models.items():
        predicted = cross_val_predict(model, features, labels, cv=folds)
        correct = sum(1 for p, t in zip(predicted, labels) if p == t)
        matrix = confusion_matrix(labels, predicted, labels=classOrder).tolist()
        ruleCorrect = sum(1 for r, t in zip(ruleLabels, labels) if r == t)
        results[modelName] = {
            "cv_accuracy": round(correct / len(labels), 4),
            "rule_baseline_accuracy": round(ruleCorrect / len(labels), 4),
            "confusion_matrix": {"classes": classOrder, "matrix": matrix},
        }

    forest = RandomForestClassifier(n_estimators=200, random_state=42, class_weight="balanced")
    forest.fit(features, labels)
    importances = sorted(
        zip(featureNames, forest.feature_importances_.tolist()),
        key=lambda pair: pair[1],
        reverse=True,
    )

    report = {
        "corpus_size": len(labels),
        "class_counts": {c: labels.count(c) for c in classOrder},
        "models": results,
        "feature_importances": [
            {"feature": name, "importance": round(value, 4)} for name, value in importances
        ],
    }
    reportPath = dataDir / "ml_genre_report.json"
    with open(reportPath, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print(f"Corpus: {len(labels)} works with a genre label ({report['class_counts']}).")
    for modelName, modelResult in results.items():
        print(f"{modelName}: 5-fold CV accuracy {modelResult['cv_accuracy'] * 100:.1f}% "
              f"(rule baseline: {modelResult['rule_baseline_accuracy'] * 100:.1f}%).")
    print("Top predictive features:", ", ".join(f"{n} ({v:.3f})" for n, v in importances[:5]))
    print(f"Full report: {reportPath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
