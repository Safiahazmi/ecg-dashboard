"""
train_mit_hardware_model_v2.py

Purpose:
Train a hardware-compatible ECG arrhythmia classifier using the uploaded
MIT-BIH Arrhythmia Database CSV.

Why this version is different:
The MIT-BIH CSV stores RR and QRS intervals as sample counts. The original
MIT-BIH sampling frequency is 360 Hz, so this script converts RR values into
seconds before training. The ESP32 also sends RR values in seconds, so the
training features and hardware features use the same unit.

Model features used by ESP32 + Render:
- pre_rr_s
- post_rr_s
- rr_diff_s
- bpm

Class mapping:
- N    -> NORMAL
- SVEB -> ABNORMAL
- VEB  -> ABNORMAL
- F    -> ABNORMAL
- Q    -> ABNORMAL
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

# =========================
# USER SETTINGS
# =========================
CSV_PATH = Path("MIT-BIH Arrhythmia Database.csv")
OUTPUT_MODEL = Path("ecg_mit_hardware_model_v2.joblib")
OUTPUT_REPORT = Path("training_report_v2.json")

MIT_BIH_FS_HZ = 360.0
RANDOM_STATE = 42

FEATURE_COLUMNS = ["pre_rr_s", "post_rr_s", "rr_diff_s", "bpm"]
LABEL_MAPPING = {0: "NORMAL", 1: "ABNORMAL"}


def load_and_prepare_data(csv_path: Path) -> tuple[pd.DataFrame, pd.Series, dict]:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"CSV file not found: {csv_path}\n"
            "Put 'MIT-BIH Arrhythmia Database.csv' in the same folder as this script."
        )

    required_columns = ["type", "0_pre-RR", "0_post-RR"]
    df = pd.read_csv(csv_path, usecols=required_columns)

    before_rows = len(df)

    # Convert MIT-BIH sample counts into seconds so it matches ESP32 feature units.
    df["pre_rr_s"] = pd.to_numeric(df["0_pre-RR"], errors="coerce") / MIT_BIH_FS_HZ
    df["post_rr_s"] = pd.to_numeric(df["0_post-RR"], errors="coerce") / MIT_BIH_FS_HZ
    df["rr_diff_s"] = (df["pre_rr_s"] - df["post_rr_s"]).abs()
    df["bpm"] = 60.0 / df["post_rr_s"].replace(0, np.nan)

    # Binary target: N is normal; all other MIT-BIH beat groups are abnormal.
    df["target"] = np.where(df["type"].astype(str).str.upper().eq("N"), 0, 1)

    # Keep values that the ESP32 can realistically send.
    valid_mask = (
        df["pre_rr_s"].between(0.30, 2.00)
        & df["post_rr_s"].between(0.30, 2.00)
        & df["bpm"].between(30, 200)
        & df["rr_diff_s"].between(0.0, 1.50)
    )
    df = df.loc[valid_mask].dropna(subset=FEATURE_COLUMNS + ["target"]).copy()

    summary = {
        "input_rows": int(before_rows),
        "rows_after_filtering": int(len(df)),
        "normal_rows": int((df["target"] == 0).sum()),
        "abnormal_rows": int((df["target"] == 1).sum()),
        "mit_bih_sampling_frequency_hz": MIT_BIH_FS_HZ,
        "feature_columns": FEATURE_COLUMNS,
        "label_mapping": LABEL_MAPPING,
    }

    X = df[FEATURE_COLUMNS]
    y = df["target"].astype(int)
    return X, y, summary


def train_model(X: pd.DataFrame, y: pd.Series):
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.20,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    # Small enough for GitHub/Render, but still strong for non-linear RR patterns.
    model = RandomForestClassifier(
        n_estimators=80,
        max_depth=8,
        min_samples_leaf=20,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=RANDOM_STATE,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, y_pred)),
        "f1_abnormal": float(f1_score(y_test, y_pred, pos_label=1)),
        "roc_auc": float(roc_auc_score(y_test, y_prob)),
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "classification_report": classification_report(
            y_test,
            y_pred,
            target_names=["NORMAL", "ABNORMAL"],
            output_dict=True,
        ),
    }

    return model, metrics


def main() -> None:
    X, y, data_summary = load_and_prepare_data(CSV_PATH)
    model, metrics = train_model(X, y)

    bundle = {
        "pipeline": model,
        "feature_columns": FEATURE_COLUMNS,
        "label_mapping": LABEL_MAPPING,
        "model_type": "RandomForestClassifier",
        "project_note": "Hardware-compatible MIT-BIH ECG arrhythmia model. RR values are seconds.",
        "data_summary": data_summary,
        "metrics": metrics,
    }

    joblib.dump(bundle, OUTPUT_MODEL, compress=("xz", 3))

    report = {
        "data_summary": data_summary,
        "metrics": metrics,
        "output_model": str(OUTPUT_MODEL),
    }
    OUTPUT_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Training completed.")
    print(f"Model saved: {OUTPUT_MODEL}")
    print(f"Report saved: {OUTPUT_REPORT}")
    print("Metrics:")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
