"""Machine-learned MEI encoding-style classifier.

Learns to classify MEI files as catalogue-style or notation-style from
structural features (element frequencies), and evaluates the learned model
against the hand-written rule in import_mei.detectEncodingStyle.

The rule provides the reference labels, so the experiment answers: can the
style distinction be recovered from raw structure alone, without hand-picking
the deciding elements? Feature importances show which elements the model
chose, and cross-validated accuracy shows how separable the two styles are.

Writes data/ml_style_report.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lxml import etree

from db import dataDir
from import_mei import detectEncodingStyle

featureElements = [
    "note", "measure", "staff", "layer", "scoreDef", "mdiv",
    "workList", "work", "identifier", "source", "perfMedium",
    "instrVoice", "eventList", "expression", "persName", "title",
    "creation", "classification", "physDesc", "annot",
]


def featurise(root: Any) -> list[float]:
    counts: dict[str, int] = {name: 0 for name in featureElements}
    total = 0
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        total = total + 1
        localName = node.tag.rsplit("}", 1)[-1]
        if localName in counts:
            counts[localName] = counts[localName] + 1
    if total == 0:
        return [0.0] * len(featureElements)
    return [counts[name] / total for name in featureElements]


def loadDataset(sourceDir: Path) -> tuple[list[list[float]], list[str], list[str]]:
    features: list[list[float]] = []
    labels: list[str] = []
    names: list[str] = []
    for meiPath in sorted(list(sourceDir.glob("*.xml")) + list(sourceDir.glob("*.mei"))):
        try:
            root = etree.parse(str(meiPath)).getroot()
        except etree.XMLSyntaxError:
            continue
        style = detectEncodingStyle(root)
        if style == "hybrid":
            style = "catalogue"
        features.append(featurise(root))
        labels.append(style)
        names.append(meiPath.name)
    return features, labels, names


def trainStyleModel(sourceDir: Path | None = None) -> Any:
    """Fit the random forest on the current corpus; returns the fitted model."""
    from sklearn.ensemble import RandomForestClassifier

    if sourceDir is None:
        sourceDir = dataDir / "mei"
    features, labels, _ = loadDataset(sourceDir)
    model = RandomForestClassifier(n_estimators=200, random_state=42)
    model.fit(features, labels)
    return model


def classifyRoot(model: Any, root: Any) -> tuple[str, float]:
    """Predict encoding style for one parsed MEI document; returns (label, confidence)."""
    probabilities = model.predict_proba([featurise(root)])[0]
    best = max(range(len(probabilities)), key=lambda i: probabilities[i])
    return str(model.classes_[best]), round(float(probabilities[best]), 3)


def loadHandLabels(path: Path) -> dict[str, str]:
    """Load independently hand-checked labels, keyed by filename, from a JSON file
    written by a human (see data/hand_labels.json). These are never derived from
    detectEncodingStyle, so they give ground truth the rule was not folded against.
    """
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return {name: entry["label"] for name, entry in payload.get("labels", {}).items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and evaluate the MEI style classifier.")
    parser.add_argument("--source", type=str, default=str(dataDir / "mei"))
    parser.add_argument("--hand-labels", type=str, default=str(dataDir / "hand_labels.json"),
                         help="JSON file of independently hand-checked labels for a subset of the corpus.")
    args = parser.parse_args()

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import confusion_matrix
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
    except ImportError:
        print("scikit-learn is not installed: pip install scikit-learn", file=sys.stderr)
        return 1

    features, labels, names = loadDataset(Path(args.source))
    if len(set(labels)) < 2:
        print("Need at least two style classes in the corpus to train.", file=sys.stderr)
        return 1

    classOrder = sorted(set(labels))
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    models = {
        "logistic_regression": LogisticRegression(max_iter=1000),
        "random_forest": RandomForestClassifier(n_estimators=200, random_state=42),
    }

    results: dict[str, Any] = {}
    for modelName, model in models.items():
        predicted = cross_val_predict(model, features, labels, cv=folds)
        correct = sum(1 for p, t in zip(predicted, labels) if p == t)
        matrix = confusion_matrix(labels, predicted, labels=classOrder).tolist()
        disagreements = [
            {"file": names[i], "rule_label": labels[i], "model_prediction": predicted[i]}
            for i in range(len(names))
            if predicted[i] != labels[i]
        ]
        results[modelName] = {
            "cv_accuracy": round(correct / len(labels), 4),
            "confusion_matrix": {"classes": classOrder, "matrix": matrix},
            "disagreements": disagreements,
        }

        handLabels = loadHandLabels(Path(args.hand_labels))
        handChecked = [
            (names[i], predicted[i], handLabels[names[i]])
            for i in range(len(names))
            if names[i] in handLabels
        ]
        if len(handChecked) > 0:
            handCorrect = sum(1 for _, pred, hand in handChecked if pred == hand)
            results[modelName]["hand_label_validation"] = {
                "note": "Accuracy against independently hand-checked labels (data/hand_labels.json), "
                        "never used to train or fold the rule-based labels this model is also compared "
                        "against. Answers 'is the model actually right', not just 'does it agree with the rule'.",
                "n_checked": len(handChecked),
                "accuracy": round(handCorrect / len(handChecked), 4),
                "detail": [
                    {"file": f, "model_prediction": pred, "hand_label": hand, "correct": pred == hand}
                    for f, pred, hand in handChecked
                ],
            }

    forest = RandomForestClassifier(n_estimators=200, random_state=42)
    forest.fit(features, labels)
    importances = sorted(
        zip(featureElements, forest.feature_importances_.tolist()),
        key=lambda pair: pair[1],
        reverse=True,
    )

    report = {
        "corpus_size": len(labels),
        "class_counts": {c: labels.count(c) for c in classOrder},
        "models": results,
        "feature_importances": [
            {"element": name, "importance": round(value, 4)} for name, value in importances
        ],
    }
    reportPath = dataDir / "ml_style_report.json"
    with open(reportPath, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print(f"Corpus: {len(labels)} files ({report['class_counts']}).")
    for modelName, modelResult in results.items():
        print(f"{modelName}: 5-fold CV accuracy {modelResult['cv_accuracy'] * 100:.1f}%, "
              f"{len(modelResult['disagreements'])} disagreement(s) with the rule.")
        handValidation = modelResult.get("hand_label_validation")
        if handValidation is not None:
            print(f"  hand-label validation: {handValidation['accuracy'] * 100:.1f}% correct "
                  f"on {handValidation['n_checked']} independently checked file(s).")
    print("Top structural features:", ", ".join(f"{n} ({v:.3f})" for n, v in importances[:5]))
    print(f"Full report: {reportPath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
