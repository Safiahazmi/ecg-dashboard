"""
test_model_v2.py
Quick offline test for ecg_mit_hardware_model_v2.joblib.
This does not need Render or PostgreSQL.
"""

import joblib
import pandas as pd

MODEL_PATH = "ecg_mit_hardware_model_v2.joblib"

samples = pd.DataFrame([
    {"name": "Normal 70 BPM", "pre_rr_s": 0.86, "post_rr_s": 0.86, "rr_diff_s": 0.00, "bpm": 70},
    {"name": "Tachycardia 140 BPM", "pre_rr_s": 0.43, "post_rr_s": 0.43, "rr_diff_s": 0.00, "bpm": 140},
    {"name": "Bradycardia 45 BPM", "pre_rr_s": 1.33, "post_rr_s": 1.33, "rr_diff_s": 0.00, "bpm": 45},
    {"name": "Irregular RR", "pre_rr_s": 0.70, "post_rr_s": 1.05, "rr_diff_s": 0.35, "bpm": 57},
])

bundle = joblib.load(MODEL_PATH)
model = bundle["pipeline"]
feature_columns = bundle["feature_columns"]
label_mapping = bundle["label_mapping"]

X = samples[feature_columns]
pred = model.predict(X)
proba = model.predict_proba(X)

for i, row in samples.iterrows():
    ml_label = label_mapping[int(pred[i])]
    confidence = max(proba[i]) * 100
    final_label = ml_label
    reason = "ML prediction"

    # Same safety logic as app.py
    if row["bpm"] < 50 or row["bpm"] > 120 or row["rr_diff_s"] > 0.18:
        final_label = "ABNORMAL"
        reason = "Hybrid rhythm rule"

    print(f"{row['name']}: ML={ml_label} ({confidence:.1f}%), Final={final_label}, Reason={reason}")
