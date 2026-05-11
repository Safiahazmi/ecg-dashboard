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
MODEL_PATH = os.getenv("MODEL_PATH", "ecg_hardware_friendly_model_small.joblib")
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
    Validate ECG features before ML prediction.

    Unit rules:
    - 0_pre-RR and 0_post-RR are in seconds from ESP32, displayed as ms in dashboard.
    - 0_qrs_interval is in seconds from ESP32, displayed as ms in dashboard.
    - 0_rPeak is ADC/raw amplitude.
    """
    pre_rr = data["0_pre-RR"]
    post_rr = data["0_post-RR"]
    r_peak = data["0_rPeak"]
    qrs_interval = data["0_qrs_interval"]

    # RR interval in seconds. 0.30–2.00 s is approximately 30–200 BPM.
    if pre_rr < 0.30 or pre_rr > 2.00:
        return False, f"preRR not realistic: {pre_rr:.4f} s"

    if post_rr < 0.30 or post_rr > 2.00:
        return False, f"postRR not realistic: {post_rr:.4f} s"

    # RR variation can happen in arrhythmia, so this is intentionally not too strict.
    if abs(pre_rr - post_rr) > 1.50:
        return False, f"RR interval mismatch too large: preRR={pre_rr:.4f}, postRR={post_rr:.4f}"

    # ESP32 ADC is 0–4095. Keep obvious flat/noisy readings out.
    if r_peak < 300 or r_peak > 4095:
        return False, f"rPeak not valid: {r_peak:.2f} ADC"

    # QRS interval in seconds. 0.04–0.20 s = 40–200 ms.
    if qrs_interval < 0.04 or qrs_interval > 0.20:
        return False, f"QRS interval not valid: {qrs_interval:.4f} s"

    return True, "Valid ECG features"


def predict_ecg_status(features):
    """Run the hardware-friendly trained model and return class, label, confidence."""
    bundle = load_model_bundle()
    if bundle is None:
        raise RuntimeError(MODEL_LOAD_ERROR or "Model could not be loaded")

    model = bundle["pipeline"] if isinstance(bundle, dict) and "pipeline" in bundle else bundle
    feature_columns = bundle.get("feature_columns", [
        "0_pre-RR", "0_post-RR", "0_rPeak", "0_qrs_interval"
    ]) if isinstance(bundle, dict) else ["0_pre-RR", "0_post-RR", "0_rPeak", "0_qrs_interval"]
    label_mapping = bundle.get("label_mapping", {0: "Normal", 1: "Abnormal"}) if isinstance(bundle, dict) else {0: "Normal", 1: "Abnormal"}

    X = pd.DataFrame([{
        "0_pre-RR": features["0_pre-RR"],
        "0_post-RR": features["0_post-RR"],
        "0_rPeak": features["0_rPeak"],
        "0_qrs_interval": features["0_qrs_interval"],
    }])[feature_columns]

    prediction_class = int(model.predict(X)[0])
    raw_label = str(label_mapping.get(prediction_class, "Abnormal"))
    prediction_label = "NORMAL" if raw_label.lower() == "normal" else "ABNORMAL"

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
    Direct ESP32 WiFi endpoint.
    ESP32 sends extracted ECG features here using HTTP POST.
    Server runs ML prediction, stores result into PostgreSQL, and returns NORMAL/ABNORMAL.
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

        features = {
            "0_pre-RR": get_float(payload, "0_pre-RR", "pre_rr", "preRR"),
            "0_post-RR": get_float(payload, "0_post-RR", "post_rr", "postRR"),
            "0_rPeak": get_float(payload, "0_rPeak", "r_peak", "rPeak"),
            "0_qrs_interval": get_float(payload, "0_qrs_interval", "qrs_interval", "qrsInterval"),
        }

        is_valid, validation_message = validate_ecg_features(features)
        if not is_valid:
            return jsonify({"status": "WAITING", "message": validation_message}), 200

        prediction_class, prediction_label, confidence = predict_ecg_status(features)

        row = execute_db(
            """
            INSERT INTO ecg_predictions
                (device_id, pre_rr, post_rr, r_peak, qrs_interval,
                 prediction_class, prediction_label, confidence, source, model_source, message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id,
                to_char(timestamp, 'DD/MM/YYYY, HH24:MI:SS') AS timestamp,
                device_id,
                pre_rr,
                post_rr,
                r_peak,
                qrs_interval,
                prediction_class,
                prediction_label,
                confidence;
            """,
            (
                device_id,
                features["0_pre-RR"],
                features["0_post-RR"],
                features["0_rPeak"],
                features["0_qrs_interval"],
                prediction_class,
                prediction_label,
                confidence,
                "ESP32_WIFI",
                MODEL_PATH,
                "Prediction saved from ESP32 WiFi API",
            ),
            fetch_one=True,
        )

        return jsonify({
            "status": prediction_label,
            "prediction_label": prediction_label,
            "prediction_class": prediction_class,
            "confidence": confidence,
            "message": "Prediction saved to PostgreSQL",
            "saved_record": row,
        }), 201

    except Exception as exc:
        return jsonify({"status": "ERROR", "message": str(exc)}), 500


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
