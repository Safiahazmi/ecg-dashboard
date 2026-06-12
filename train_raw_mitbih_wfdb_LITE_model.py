"""
ECG Raw Waveform ML Training - MIT-BIH Arrhythmia Database via PhysioNet/WFDB
Author: ChatGPT package for ESP32 + AD8232 ECG Arrhythmia Project

Purpose
-------
Train a machine-learning model that classifies a 5-second raw ECG waveform window as:
    0 = NORMAL
    1 = ABNORMAL

This script downloads MIT-BIH Arrhythmia Database records directly from PhysioNet using wfdb.
It does NOT train on the old feature CSV. It trains on original raw ECG waveform.

How to run in Google Colab
--------------------------
1) Upload this file to Colab, or paste the code into a Colab notebook.
2) Run:
       !pip install wfdb scikit-learn scipy pandas numpy joblib
3) Run:
       !python train_raw_mitbih_wfdb_model.py
4) Download the output files:
       ecg_raw_waveform_model.joblib
       training_report_raw_ml.json

Important
---------
The ESP32 must send raw ECG samples to Render. The server will resize and normalize the waveform
using the same preprocessing method used here.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
import wfdb
from scipy import signal
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.utils import shuffle

# Patient-oriented split commonly used for MIT-BIH inter-patient evaluation.
# DS1 = training subjects, DS2 = testing subjects.
TRAIN_RECORDS = [
    "101", "106", "108", "109", "112", "114", "115", "116", "118", "119", "122", "124",
    "201", "203", "205", "207", "208", "209", "215", "220", "223", "230",
]
TEST_RECORDS = [
    "100", "103", "105", "111", "113", "117", "121", "123", "200", "202", "210", "212",
    "213", "214", "219", "221", "222", "228", "231", "232", "233", "234",
]

# MIT-BIH beat symbols. We treat only pure "N" beats as NORMAL for a clean binary project.
# All other beat symbols are treated as ABNORMAL when they appear inside a window.
BEAT_SYMBOLS = {
    "N", "L", "R", "B", "A", "a", "J", "S", "V", "r", "F", "e", "j", "n", "E", "/", "f", "Q", "?"
}
NORMAL_SYMBOLS = {"N"}


def preprocess_window(raw_window: np.ndarray, output_length: int) -> np.ndarray:
    """Resize, baseline-remove and z-score-normalize one raw ECG window."""
    x = np.asarray(raw_window, dtype=np.float32)
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

    # Remove DC baseline. This keeps preprocessing lightweight and matches Render inference.
    x = x - np.median(x)

    if len(x) != output_length:
        x = signal.resample(x, output_length).astype(np.float32)

    std = float(np.std(x))
    if std < 1e-6:
        return np.zeros(output_length, dtype=np.float32)

    x = x / std
    return x.astype(np.float32)


def label_window(annotation_samples: np.ndarray, annotation_symbols: List[str], start: int, end: int) -> int | None:
    """
    Label a 5-second ECG window.

    Return:
        0 = NORMAL      if the window contains only N beats
        1 = ABNORMAL    if the window contains at least one beat symbol other than N
        None            if the window contains no valid beat annotation
    """
    idx = np.where((annotation_samples >= start) & (annotation_samples < end))[0]
    beat_symbols = [annotation_symbols[i] for i in idx if annotation_symbols[i] in BEAT_SYMBOLS]

    if not beat_symbols:
        return None

    if all(sym in NORMAL_SYMBOLS for sym in beat_symbols):
        return 0

    return 1


def extract_windows_from_record(
    record_id: str,
    window_seconds: float,
    step_seconds: float,
    output_length: int,
    channel: int = 0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Download one MIT-BIH record via WFDB and extract labelled raw ECG windows."""
    print(f"Reading MIT-BIH record {record_id} ...")

    record = wfdb.rdrecord(record_id, pn_dir="mitdb", channels=[channel], physical=True)
    ann = wfdb.rdann(record_id, "atr", pn_dir="mitdb")

    fs = int(record.fs)
    raw_signal = record.p_signal[:, 0].astype(np.float32)

    win_len = int(round(window_seconds * fs))
    step_len = int(round(step_seconds * fs))

    X_list: List[np.ndarray] = []
    y_list: List[int] = []

    for start in range(0, len(raw_signal) - win_len, step_len):
        end = start + win_len
        y = label_window(np.asarray(ann.sample), list(ann.symbol), start, end)
        if y is None:
            continue
        x = preprocess_window(raw_signal[start:end], output_length)
        if np.std(x) < 1e-6:
            continue
        X_list.append(x)
        y_list.append(y)

    if not X_list:
        return np.empty((0, output_length), dtype=np.float32), np.empty((0,), dtype=np.int64)

    return np.vstack(X_list).astype(np.float32), np.asarray(y_list, dtype=np.int64)


def balance_classes(X: np.ndarray, y: np.ndarray, max_per_class: int, seed: int) -> Tuple[np.ndarray, np.ndarray]:
    """Limit each class to max_per_class so training is not dominated by normal windows."""
    rng = np.random.default_rng(seed)
    selected_indices = []

    for cls in sorted(np.unique(y)):
        cls_idx = np.where(y == cls)[0]
        if len(cls_idx) > max_per_class:
            cls_idx = rng.choice(cls_idx, size=max_per_class, replace=False)
        selected_indices.extend(cls_idx.tolist())

    selected_indices = np.asarray(selected_indices)
    X_bal, y_bal = X[selected_indices], y[selected_indices]
    return shuffle(X_bal, y_bal, random_state=seed)


def build_dataset(records: List[str], args: argparse.Namespace) -> Tuple[np.ndarray, np.ndarray, Dict[str, int]]:
    X_all = []
    y_all = []
    per_record_counts: Dict[str, int] = {}

    for record_id in records:
        try:
            X_rec, y_rec = extract_windows_from_record(
                record_id=record_id,
                window_seconds=args.window_seconds,
                step_seconds=args.step_seconds,
                output_length=args.output_length,
                channel=args.channel,
            )
            if len(y_rec) > 0:
                X_all.append(X_rec)
                y_all.append(y_rec)
                per_record_counts[record_id] = int(len(y_rec))
                normal_count = int(np.sum(y_rec == 0))
                abnormal_count = int(np.sum(y_rec == 1))
                print(f"  -> windows={len(y_rec)} normal={normal_count} abnormal={abnormal_count}")
            else:
                per_record_counts[record_id] = 0
                print(f"  -> no usable windows")
        except Exception as exc:
            per_record_counts[record_id] = -1
            print(f"  !! skipped record {record_id}: {exc}")

    if not X_all:
        raise RuntimeError("No windows extracted. Check internet connection and wfdb installation.")

    X = np.vstack(X_all).astype(np.float32)
    y = np.concatenate(y_all).astype(np.int64)
    return X, y, per_record_counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window_seconds", type=float, default=5.0)
    parser.add_argument("--step_seconds", type=float, default=2.5)
    parser.add_argument("--output_length", type=int, default=400)
    parser.add_argument("--channel", type=int, default=0)
    parser.add_argument("--max_windows_per_class", type=int, default=2500)
    parser.add_argument("--n_estimators", type=int, default=40)
    parser.add_argument("--max_depth", type=int, default=10)
    parser.add_argument("--random_state", type=int, default=42)
    parser.add_argument("--model_out", type=str, default="ecg_raw_waveform_model.joblib")
    parser.add_argument("--report_out", type=str, default="training_report_raw_ml.json")
    args = parser.parse_args()

    random.seed(args.random_state)
    np.random.seed(args.random_state)

    print("\n========== BUILD TRAIN DATASET ==========")
    X_train, y_train, train_counts = build_dataset(TRAIN_RECORDS, args)
    print("\n========== BUILD TEST DATASET ==========")
    X_test, y_test, test_counts = build_dataset(TEST_RECORDS, args)

    print("\nBefore balancing:")
    print("Train:", dict(zip(*np.unique(y_train, return_counts=True))))
    print("Test :", dict(zip(*np.unique(y_test, return_counts=True))))

    X_train_bal, y_train_bal = balance_classes(
        X_train, y_train, max_per_class=args.max_windows_per_class, seed=args.random_state
    )

    print("\nAfter balancing train data:")
    print(dict(zip(*np.unique(y_train_bal, return_counts=True))))

    print("\n========== TRAIN RAW WAVEFORM ML MODEL ==========")
    model = ExtraTreesClassifier(
        n_estimators=args.n_estimators,
        random_state=args.random_state,
        class_weight="balanced",
        n_jobs=1,
        max_features="sqrt",
        min_samples_leaf=8,
        max_depth=args.max_depth,
        bootstrap=False,
    )
    model.fit(X_train_bal, y_train_bal)

    print("\n========== EVALUATE ==========")
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    report = {
        "model_type": "ExtraTreesClassifier_LITE_RenderSafe",
        "project_mode": "FULLY_ML_RAW_WAVEFORM_CLASSIFICATION",
        "decision_rule": "ML_ONLY_FOR_NORMAL_ABNORMAL",
        "dataset": "MIT-BIH Arrhythmia Database via PhysioNet/wfdb",
        "train_records": TRAIN_RECORDS,
        "test_records": TEST_RECORDS,
        "record_window_counts_train": train_counts,
        "record_window_counts_test": test_counts,
        "window_seconds": args.window_seconds,
        "step_seconds": args.step_seconds,
        "output_length": args.output_length,
        "n_estimators": args.n_estimators,
        "max_depth": args.max_depth,
        "min_samples_leaf": 8,
        "channel": args.channel,
        "normal_definition": "Window contains only N beat annotations",
        "abnormal_definition": "Window contains at least one valid beat annotation other than N",
        "label_mapping": {"0": "NORMAL", "1": "ABNORMAL"},
        "train_counts_before_balance": {str(k): int(v) for k, v in zip(*np.unique(y_train, return_counts=True))},
        "train_counts_after_balance": {str(k): int(v) for k, v in zip(*np.unique(y_train_bal, return_counts=True))},
        "test_counts": {str(k): int(v) for k, v in zip(*np.unique(y_test, return_counts=True))},
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, y_pred)),
        "roc_auc": float(roc_auc_score(y_test, y_proba)) if len(np.unique(y_test)) == 2 else None,
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "classification_report": classification_report(
            y_test,
            y_pred,
            target_names=["NORMAL", "ABNORMAL"],
            output_dict=True,
            zero_division=0,
        ),
        "preprocessing": "median baseline removal -> resample to fixed length -> z-score normalization",
    }

    print(json.dumps({
        "accuracy": report["accuracy"],
        "balanced_accuracy": report["balanced_accuracy"],
        "roc_auc": report["roc_auc"],
        "confusion_matrix": report["confusion_matrix"],
    }, indent=2))

    bundle = {
        "model": model,
        "input_length": args.output_length,
        "window_seconds": args.window_seconds,
        "training_sample_rate_hz": 360,
        "label_mapping": {0: "NORMAL", 1: "ABNORMAL"},
        "preprocessing": "median baseline removal -> resample to fixed length -> z-score normalization",
        "decision_rule": "ML_ONLY_FOR_NORMAL_ABNORMAL",
        "notes": "BPM may be estimated separately for display only; BPM is not used to force the normal/abnormal class.",
        "training_report": report,
    }

    joblib.dump(bundle, args.model_out, compress=("xz", 6))
    Path(args.report_out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nDONE")
    print(f"Saved model : {args.model_out}")
    print(f"Saved report: {args.report_out}")


if __name__ == "__main__":
    main()
