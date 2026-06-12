import csv
import io
import os
from pathlib import Path

import pandas as pd
from joblib import load
from flask import Flask, render_template, jsonify, request, Response
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

app = Flask(__name__)

# =====================================================
# DATABASE SETTINGS
# =====================================================
# Render uses DATABASE_URL. Local PostgreSQL can still use DB_HOST/DB_NAME/etc.
DATABASE_URL = os.getenv("DATABASE_URL")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "ecg_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_PORT = os.getenv("DB_PORT", "5432")

# =====================================================
# ML / ESP32 WIFI API SETTINGS
# =====================================================
# Use the compressed small model because GitHub browser upload accepts files under 25 MB.
MODEL_PATH = os.getenv("MODEL_PATH", "ecg_mit_hardware_model_v2.joblib")
ESP32_API_KEY = os.getenv("ESP32_API_KEY", "").strip()

MODEL_BUNDLE = None
MODEL_LOAD_ERROR = None

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ecg_predictions (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_id VARCHAR(50),
    pre_rr DOUBLE PRECISION,
    post_rr DOUBLE PRECISION,
    r_peak DOUBLE PRECISION,
    qrs_interval DOUBLE PRECISION,
    heart_rate DOUBLE PRECISION,
    prediction_class INT,
    prediction_label VARCHAR(20),
    confidence DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS patients (
    id SERIAL PRIMARY KEY,
    patient_name VARCHAR(120) NOT NULL,
    age INT NOT NULL CHECK (age >= 0 AND age <= 120),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ecg_predictions ADD COLUMN IF NOT EXISTS heart_rate DOUBLE PRECISION;
ALTER TABLE ecg_predictions ADD COLUMN IF NOT EXISTS source VARCHAR(30) DEFAULT 'ESP32_WIFI';
ALTER TABLE ecg_predictions ADD COLUMN IF NOT EXISTS model_source VARCHAR(80);
ALTER TABLE ecg_predictions ADD COLUMN IF NOT EXISTS message TEXT;
"""


def get_connection():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)

    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
    )


def ensure_table_exists():
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(CREATE_TABLE_SQL)
        conn.commit()
        cur.close()
        print("ecg_predictions and patients tables are ready.")
    except Exception as exc:
        # Do not crash Render during boot if DB is sleeping/unavailable.
        print("Database setup warning:", exc)
    finally:
        if conn:
            conn.close()


def query_db(query, params=None):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params or ())
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        if conn:
            conn.close()


def execute_db(query, params=None, fetch_one=False):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params or ())
        row = cur.fetchone() if fetch_one else None
        conn.commit()
        cur.close()
        return row
    finally:
        if conn:
            conn.close()


def time_to_ms(value):
    if value is None:
        return ""
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return ""
    ms = raw * 1000 if abs(raw) < 10 else raw
    return f"{ms:.1f}"


def fmt_number(value, decimals=2):
    if value is None:
        return ""
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return ""


def get_optional_float(payload, *keys):
    for key in keys:
        if key in payload and payload.get(key) is not None and str(payload.get(key)).strip() != "":
            try:
                return float(payload.get(key))
            except (TypeError, ValueError):
                return None
    return None


def calculate_heart_rate(pre_rr, post_rr=None):
    """Calculate heart rate in BPM from valid RR interval values in seconds."""
    intervals = []
    for value in (pre_rr, post_rr):
        try:
            rr = float(value)
        except (TypeError, ValueError):
            continue
        if 0.30 <= rr <= 2.00:
            intervals.append(rr)

    if not intervals:
        return None

    average_rr = sum(intervals) / len(intervals)
    if average_rr <= 0:
        return None

    bpm = 60.0 / average_rr
    if bpm < 20 or bpm > 250:
        return None

    return round(bpm, 2)


# =====================================================
# ML MODEL HELPERS FOR ESP32 WIFI MODE
# =====================================================
def load_model_bundle():
    """Load the trained ECG ML model once when the ESP32 WiFi API is used."""
    global MODEL_BUNDLE, MODEL_LOAD_ERROR

    if MODEL_BUNDLE is not None:
        return MODEL_BUNDLE

    model_file = Path(MODEL_PATH)
    if not model_file.exists():
        MODEL_LOAD_ERROR = f"Model file not found: {MODEL_PATH}"
        return None

    try:
        MODEL_BUNDLE = load(model_file)
        MODEL_LOAD_ERROR = None
        print(f"ECG ML model loaded: {MODEL_PATH}")
        return MODEL_BUNDLE
    except Exception as exc:
        MODEL_LOAD_ERROR = str(exc)
        return None


def get_float(payload, *keys):
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return float(payload.get(key))
    raise ValueError(f"Missing required value: {keys[0]}")


def validate_ecg_features(data):
    """
    Validate ESP32 ECG features before prediction.

    Unit rules for V2:
    - pre_rr_s and post_rr_s are in seconds.
    - rr_diff_s is calculated in seconds.
    - bpm is beats per minute.
    - r_peak and qrs_interval are saved for dashboard/debug, but they are NOT used by the ML model.
    """
    pre_rr = float(data["pre_rr_s"])
    post_rr = float(data["post_rr_s"])
    rr_diff = float(data["rr_diff_s"])
    bpm = float(data["bpm"])

    if pre_rr < 0.30 or pre_rr > 2.00:
        return False, f"preRR not realistic: {pre_rr:.4f} s"

    if post_rr < 0.30 or post_rr > 2.00:
        return False, f"postRR not realistic: {post_rr:.4f} s"

    if rr_diff < 0.0 or rr_diff > 1.50:
        return False, f"RR difference not realistic: {rr_diff:.4f} s"

    if bpm < 30 or bpm > 200:
        return False, f"BPM not realistic: {bpm:.1f}"

    return True, "Valid ECG features"


def apply_rhythm_safety_logic(prediction_label, prediction_class, confidence, features):
    """
    Keep the ML model, but add a simple safety layer for simulator/hardware testing.
    This helps the system react correctly to obvious bradycardia, tachycardia,
    or highly irregular RR rhythm even when the model probability is uncertain.
    """
    bpm = float(features["bpm"])
    rr_diff = float(features["rr_diff_s"])

    reasons = []
    if bpm < 50:
        reasons.append("bradycardia range")
    if bpm >= 120:
        reasons.append("tachycardia range")
    if rr_diff > 0.30:
        reasons.append("irregular RR interval")

    if reasons:
        return 1, "ABNORMAL", max(float(confidence), 85.0), "Hybrid rule: " + ", ".join(reasons)

    return prediction_class, prediction_label, confidence, "ML prediction"


def predict_ecg_status(features):
    """Run the V2 hardware-compatible trained model and return class, label, confidence."""
    bundle = load_model_bundle()
    if bundle is None:
        raise RuntimeError(MODEL_LOAD_ERROR or "Model could not be loaded")

    model = bundle["pipeline"] if isinstance(bundle, dict) and "pipeline" in bundle else bundle
    feature_columns = bundle.get("feature_columns", [
        "pre_rr_s", "post_rr_s", "rr_diff_s", "bpm"
    ]) if isinstance(bundle, dict) else ["pre_rr_s", "post_rr_s", "rr_diff_s", "bpm"]
    label_mapping = bundle.get("label_mapping", {0: "NORMAL", 1: "ABNORMAL"}) if isinstance(bundle, dict) else {0: "NORMAL", 1: "ABNORMAL"}

    X = pd.DataFrame([{
        "pre_rr_s": features["pre_rr_s"],
        "post_rr_s": features["post_rr_s"],
        "rr_diff_s": features["rr_diff_s"],
        "bpm": features["bpm"],
    }])[feature_columns]

    prediction_class = int(model.predict(X)[0])
    prediction_label = str(label_mapping.get(prediction_class, "ABNORMAL")).upper()
    if prediction_label != "NORMAL":
        prediction_label = "ABNORMAL"

    confidence = 0.0
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(X)[0]
        confidence = float(max(probabilities) * 100.0)

    return prediction_class, prediction_label, confidence


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "OK",
        "model_path": MODEL_PATH,
        "model_exists": Path(MODEL_PATH).exists(),
        "database": "Render PostgreSQL" if DATABASE_URL else DB_NAME,
    })


@app.route("/api/esp32/features", methods=["POST"])
def api_esp32_features():
    """
    Direct ESP32 WiFi endpoint for V2.
    ESP32 sends hardware-compatible ECG rhythm features here.
    Server runs ML prediction, applies a safety rhythm check, stores result into PostgreSQL,
    and returns NORMAL/ABNORMAL to the OLED.
    """
    payload = request.get_json(silent=True) or {}

    if ESP32_API_KEY:
        provided_key = request.headers.get("X-API-Key", "") or str(payload.get("api_key", ""))
        if provided_key != ESP32_API_KEY:
            return jsonify({"status": "UNAUTHORIZED", "message": "Invalid ESP32 API key"}), 401

    try:
        lo_plus = int(payload.get("lo_plus", payload.get("LO_PLUS", 0)) or 0)
        lo_minus = int(payload.get("lo_minus", payload.get("LO_MINUS", 0)) or 0)
        device_id = str(payload.get("device_id", "ESP32_AD8232_01"))

        if lo_plus == 1 or lo_minus == 1:
            return jsonify({"status": "LEADS_OFF", "message": "Check ECG electrodes"}), 200

        pre_rr = get_float(payload, "pre_rr_s", "pre_rr", "preRR", "0_pre-RR")
        post_rr = get_float(payload, "post_rr_s", "post_rr", "postRR", "0_post-RR")
        rr_diff = abs(pre_rr - post_rr)

        received_heart_rate = get_optional_float(payload, "heart_rate", "heartRate", "bpm", "BPM")
        heart_rate = received_heart_rate if received_heart_rate and 20 <= received_heart_rate <= 250 else calculate_heart_rate(pre_rr, post_rr)
        if heart_rate is None:
            return jsonify({"status": "WAITING", "message": "Cannot calculate BPM"}), 200

        r_peak = get_optional_float(payload, "r_peak", "rPeak", "0_rPeak")
        if r_peak is None:
            r_peak = 0.0

        qrs_interval = get_optional_float(payload, "qrs_interval", "qrsInterval", "0_qrs_interval")
        if qrs_interval is None or qrs_interval < 0.03 or qrs_interval > 0.25:
            qrs_interval = 0.08

        features = {
            "pre_rr_s": pre_rr,
            "post_rr_s": post_rr,
            "rr_diff_s": rr_diff,
            "bpm": heart_rate,
        }

        # Normal-mode transition filter:
        # When the simulator is changed from tachy/brady/irregular back to normal,
        # the first RR pair may mix one old interval with one new normal interval.
        # Example: pre_rr=0.530 s and post_rr=0.749 s gives bpm≈80 but rr_diff≈0.219 s.
        # That is a transition artifact, not a stable normal rhythm. Do not save/predict it.
        if 55 <= heart_rate <= 105 and 0.18 < rr_diff <= 0.30:
            return jsonify({
                "status": "WAITING",
                "prediction_label": "WAITING",
                "prediction_class": -1,
                "confidence": 0.0,
                "heart_rate": heart_rate,
                "bpm": heart_rate,
                "decision_message": "Transition filter: waiting for stable normal RR intervals",
                "message": "Rhythm stabilizing. Wait 3-5 beats before reading.",
            }), 200

        is_valid, validation_message = validate_ecg_features(features)
        if not is_valid:
            return jsonify({"status": "WAITING", "message": validation_message}), 200

        ml_class, ml_label, ml_confidence = predict_ecg_status(features)
        prediction_class, prediction_label, confidence, decision_message = apply_rhythm_safety_logic(
            ml_label, ml_class, ml_confidence, features
        )

        row = None
        save_message = "Prediction saved to PostgreSQL"
        try:
            row = execute_db(
                """
                INSERT INTO ecg_predictions
                    (device_id, pre_rr, post_rr, r_peak, qrs_interval, heart_rate,
                     prediction_class, prediction_label, confidence, source, model_source, message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING
                    id,
                    to_char(timestamp, 'DD/MM/YYYY, HH24:MI:SS') AS timestamp,
                    device_id,
                    pre_rr,
                    post_rr,
                    r_peak,
                    qrs_interval,
                    heart_rate,
                    prediction_class,
                    prediction_label,
                    confidence;
                """,
                (
                    device_id,
                    pre_rr,
                    post_rr,
                    r_peak,
                    qrs_interval,
                    heart_rate,
                    prediction_class,
                    prediction_label,
                    confidence,
                    "ESP32_WIFI_V2",
                    MODEL_PATH,
                    decision_message,
                ),
                fetch_one=True,
            )
        except Exception as db_exc:
            # Return the prediction to the ESP32 even if PostgreSQL is temporarily unavailable.
            save_message = f"Prediction made, but database save failed: {db_exc}"

        return jsonify({
            "status": prediction_label,
            "prediction_label": prediction_label,
            "prediction_class": prediction_class,
            "confidence": confidence,
            "heart_rate": heart_rate,
            "bpm": heart_rate,
            "ml_label": ml_label,
            "ml_confidence": ml_confidence,
            "decision_message": decision_message,
            "message": save_message,
            "saved_record": row,
        }), 201

    except Exception as exc:
        return jsonify({"status": "ERROR", "message": str(exc)}), 400


@app.route("/api/latest")
def api_latest():
    try:
        rows = query_db(
            """
            SELECT
                id,
                to_char(timestamp, 'DD/MM/YYYY, HH24:MI:SS') AS timestamp,
                device_id,
                pre_rr,
                post_rr,
                r_peak,
                qrs_interval,
                CASE
                    WHEN heart_rate IS NOT NULL THEN heart_rate
                    WHEN pre_rr IS NOT NULL AND post_rr IS NOT NULL AND ((pre_rr + post_rr) / 2.0) > 0 THEN 60.0 / ((pre_rr + post_rr) / 2.0)
                    WHEN pre_rr IS NOT NULL AND pre_rr > 0 THEN 60.0 / pre_rr
                    ELSE NULL
                END AS heart_rate,
                prediction_class,
                prediction_label,
                confidence
            FROM ecg_predictions
            ORDER BY timestamp DESC, id DESC
            LIMIT 1;
            """
        )
        return jsonify(rows[0] if rows else None)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/history")
def api_history():
    try:
        rows = query_db(
            """
            SELECT
                id,
                to_char(timestamp, 'DD/MM/YYYY, HH24:MI:SS') AS timestamp,
                device_id,
                pre_rr,
                post_rr,
                r_peak,
                qrs_interval,
                CASE
                    WHEN heart_rate IS NOT NULL THEN heart_rate
                    WHEN pre_rr IS NOT NULL AND post_rr IS NOT NULL AND ((pre_rr + post_rr) / 2.0) > 0 THEN 60.0 / ((pre_rr + post_rr) / 2.0)
                    WHEN pre_rr IS NOT NULL AND pre_rr > 0 THEN 60.0 / pre_rr
                    ELSE NULL
                END AS heart_rate,
                prediction_class,
                prediction_label,
                confidence
            FROM ecg_predictions
            ORDER BY timestamp DESC, id DESC
            LIMIT 30;
            """
        )
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/stats")
def api_stats():
    try:
        rows = query_db(
            """
            SELECT
                COUNT(*) AS total_predictions,
                COUNT(*) FILTER (WHERE LOWER(prediction_label) = 'normal') AS normal_count,
                COUNT(*) FILTER (WHERE LOWER(prediction_label) = 'abnormal') AS abnormal_count
            FROM ecg_predictions;
            """
        )
        return jsonify(rows[0] if rows else {"total_predictions": 0, "normal_count": 0, "abnormal_count": 0})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/patient", methods=["GET", "POST"])
def api_patient():
    if request.method == "GET":
        try:
            rows = query_db(
                """
                SELECT
                    id,
                    patient_name,
                    age,
                    to_char(created_at, 'DD/MM/YYYY, HH24:MI:SS') AS created_at
                FROM patients
                ORDER BY created_at DESC, id DESC
                LIMIT 1;
                """
            )
            return jsonify(rows[0] if rows else None)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    payload = request.get_json(silent=True) or {}
    patient_name = str(payload.get("patient_name", "")).strip()
    age_value = payload.get("age")

    if not patient_name:
        return jsonify({"error": "Patient name is required."}), 400

    try:
        age = int(age_value)
    except (TypeError, ValueError):
        return jsonify({"error": "Age must be a number."}), 400

    if age < 0 or age > 120:
        return jsonify({"error": "Age must be between 0 and 120."}), 400

    try:
        row = execute_db(
            """
            INSERT INTO patients (patient_name, age)
            VALUES (%s, %s)
            RETURNING id, patient_name, age, to_char(created_at, 'DD/MM/YYYY, HH24:MI:SS') AS created_at;
            """,
            (patient_name, age),
            fetch_one=True,
        )
        return jsonify(row), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/export-excel")
def api_export_excel():
    """Export an Excel-compatible CSV file that can be opened directly in Microsoft Excel."""
    try:
        patient_rows = query_db(
            """
            SELECT patient_name, age
            FROM patients
            ORDER BY created_at DESC, id DESC
            LIMIT 1;
            """
        )
        patient = patient_rows[0] if patient_rows else {"patient_name": "", "age": ""}

        prediction_rows = query_db(
            """
            SELECT
                to_char(timestamp, 'DD/MM/YYYY, HH24:MI:SS') AS timestamp,
                device_id,
                pre_rr,
                post_rr,
                r_peak,
                qrs_interval,
                CASE
                    WHEN heart_rate IS NOT NULL THEN heart_rate
                    WHEN pre_rr IS NOT NULL AND post_rr IS NOT NULL AND ((pre_rr + post_rr) / 2.0) > 0 THEN 60.0 / ((pre_rr + post_rr) / 2.0)
                    WHEN pre_rr IS NOT NULL AND pre_rr > 0 THEN 60.0 / pre_rr
                    ELSE NULL
                END AS heart_rate,
                prediction_label,
                confidence
            FROM ecg_predictions
            ORDER BY timestamp DESC, id DESC;
            """
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Patient Name",
            "Age",
            "Time",
            "Device ID",
            "0_pre-RR (ms)",
            "0_post-RR (ms)",
            "0_rPeak (ADC)",
            "0_qrs_interval (ms)",
            "Heart Rate (BPM)",
            "Prediction",
            "Confidence (%)",
        ])

        for row in prediction_rows:
            writer.writerow([
                patient.get("patient_name", ""),
                patient.get("age", ""),
                row.get("timestamp", ""),
                row.get("device_id", ""),
                time_to_ms(row.get("pre_rr")),
                time_to_ms(row.get("post_rr")),
                fmt_number(row.get("r_peak"), 2),
                time_to_ms(row.get("qrs_interval")),
                fmt_number(row.get("heart_rate"), 1),
                row.get("prediction_label", ""),
                fmt_number(row.get("confidence"), 1),
            ])

        csv_text = "\ufeff" + output.getvalue()
        return Response(
            csv_text,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=ecg_prediction_export.csv"},
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/db-status")
def api_db_status():
    try:
        query_db("SELECT 1;")
        return jsonify({"connected": True, "database": DB_NAME if not DATABASE_URL else "Render PostgreSQL"})
    except Exception as exc:
        return jsonify({"connected": False, "database": DB_NAME if not DATABASE_URL else "Render PostgreSQL", "error": str(exc)})


ensure_table_exists()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
