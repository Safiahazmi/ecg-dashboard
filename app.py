import csv
import io
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal
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
RAW_MODEL_PATH = os.getenv("RAW_MODEL_PATH", "ecg_raw_waveform_model.joblib")
ESP32_API_KEY = os.getenv("ESP32_API_KEY", "").strip()

MODEL_BUNDLE = None
MODEL_LOAD_ERROR = None
RAW_MODEL_BUNDLE = None
RAW_MODEL_LOAD_ERROR = None

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
    if bpm > 120:
        reasons.append("tachycardia range")
    if rr_diff > 0.18:
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




# =====================================================
# RAW WAVEFORM ML HELPERS - FULLY ML CLASSIFICATION
# =====================================================
def load_raw_model_bundle():
    """Load the raw waveform ML model once. This model makes the final NORMAL/ABNORMAL decision."""
    global RAW_MODEL_BUNDLE, RAW_MODEL_LOAD_ERROR

    if RAW_MODEL_BUNDLE is not None:
        return RAW_MODEL_BUNDLE

    model_file = Path(RAW_MODEL_PATH)
    if not model_file.exists():
        RAW_MODEL_LOAD_ERROR = f"Raw waveform model file not found: {RAW_MODEL_PATH}"
        return None

    try:
        RAW_MODEL_BUNDLE = load(model_file)
        RAW_MODEL_LOAD_ERROR = None
        print(f"Raw waveform ECG ML model loaded: {RAW_MODEL_PATH}")
        return RAW_MODEL_BUNDLE
    except Exception as exc:
        RAW_MODEL_LOAD_ERROR = str(exc)
        return None


def preprocess_raw_waveform(samples, input_length):
    """
    Apply the same preprocessing used during training:
    median baseline removal -> resize/resample -> z-score normalization.

    This preprocessing prepares the signal only. It does NOT decide NORMAL/ABNORMAL.
    """
    x = np.asarray(samples, dtype=np.float32)
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

    if x.size < 250:
        raise ValueError("Not enough ECG samples. Send at least 250 samples.")

    # Remove baseline/DC component. ADC offset does not matter after this step.
    x = x - np.median(x)

    if x.size != int(input_length):
        x = signal.resample(x, int(input_length)).astype(np.float32)

    std = float(np.std(x))
    if std < 1e-6:
        raise ValueError("ECG waveform is too flat. Check AD8232 output/electrodes/simulator.")

    x = x / std
    return x.reshape(1, -1)


def estimate_bpm_for_display(samples, sample_rate_hz):
    """
    Estimate BPM from raw waveform for dashboard/OLED display.
    This version is tuned for ECG simulator testing up to about 180 BPM.
    """
    try:
        fs = float(sample_rate_hz)
        if fs < 50 or fs > 1000:
            fs = 250.0

        x = np.asarray(samples, dtype=np.float32)
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        if x.size < int(fs * 2):
            return None

        # Remove DC/baseline and normalize
        x = x - np.median(x)
        std = float(np.std(x))
        if std < 1e-6:
            return None
        x = x / std

        # 180 BPM = RR about 0.333 s.
        # Old 0.35 s distance blocked 180 BPM, so use 0.22 s.
        min_distance = int(0.22 * fs)
        prominence = max(0.35, float(np.std(x) * 0.45))

        peaks_pos, _ = signal.find_peaks(x, distance=min_distance, prominence=prominence)
        peaks_neg, _ = signal.find_peaks(-x, distance=min_distance, prominence=prominence)

        candidates = []
        for peaks in (peaks_pos, peaks_neg):
            if len(peaks) >= 2:
                rr = np.diff(peaks) / fs
                rr = rr[(rr >= 0.22) & (rr <= 2.50)]
                if rr.size >= 2:
                    median_rr = float(np.median(rr))
                    bpm = 60.0 / median_rr
                    if 20 <= bpm <= 260:
                        # Prefer polarity with more valid beats and stable RR
                        rr_stability = float(np.std(rr))
                        candidates.append((len(rr), -rr_stability, bpm))

        if not candidates:
            return None

        candidates.sort(reverse=True)
        return round(float(candidates[0][2]), 1)
    except Exception:
        return None


def apply_bpm_simulator_rule(ml_prediction_class, ml_prediction_label, ml_confidence, bpm):
    """
    Simulator demo rule requested by user:
    - BPM < 40       => ABNORMAL
    - 40 to 100 BPM  => NORMAL
    - BPM > 100      => ABNORMAL

    Important: this makes the final display a HYBRID decision, not ML-only.
    """
    if bpm is None:
        return ml_prediction_class, ml_prediction_label, ml_confidence, "ML prediction; BPM not available"

    try:
        bpm = float(bpm)
    except Exception:
        return ml_prediction_class, ml_prediction_label, ml_confidence, "ML prediction; BPM invalid"

    if bpm < 40:
        return 1, "ABNORMAL", max(float(ml_confidence), 90.0), "BPM rule: bradycardia below 40 BPM"
    if 40 <= bpm <= 100:
        return 0, "NORMAL", max(float(ml_confidence), 90.0), "BPM rule: normal simulator range 40-100 BPM"
    if bpm > 100:
        return 1, "ABNORMAL", max(float(ml_confidence), 90.0), "BPM rule: tachycardia above 100 BPM"

    return ml_prediction_class, ml_prediction_label, ml_confidence, "ML prediction"


def predict_raw_waveform_status(samples):
    """Run raw waveform ML model. Final classification is ML-only."""
    bundle = load_raw_model_bundle()
    if bundle is None:
        raise RuntimeError(RAW_MODEL_LOAD_ERROR or "Raw waveform model could not be loaded")

    model = bundle["model"] if isinstance(bundle, dict) and "model" in bundle else bundle
    input_length = int(bundle.get("input_length", 400)) if isinstance(bundle, dict) else 400
    label_mapping = bundle.get("label_mapping", {0: "NORMAL", 1: "ABNORMAL"}) if isinstance(bundle, dict) else {0: "NORMAL", 1: "ABNORMAL"}

    X = preprocess_raw_waveform(samples, input_length)
    prediction_class = int(model.predict(X)[0])
    prediction_label = str(label_mapping.get(prediction_class, "ABNORMAL")).upper()
    if prediction_label != "NORMAL":
        prediction_label = "ABNORMAL"
        prediction_class = 1
    else:
        prediction_class = 0

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




@app.route("/api/esp32/raw", methods=["POST"])
def api_esp32_raw():
    """
    ESP32 raw waveform endpoint for fully ML classification.

    Expected JSON:
    {
        "api_key": "ECG12345",
        "device_id": "ESP32_AD8232_01",
        "samples": [2040, 2043, 2050, ...],
        "sample_rate": 250,
        "lo_plus": 0,
        "lo_minus": 0
    }

    Raw waveform ML is performed first. Then a simulator BPM rule is applied
    to match the requested demo ranges: <40 abnormal, 40-100 normal, >100 abnormal.
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
            return jsonify({"status": "LEADS_OFF", "message": "Check ECG electrodes/simulator leads"}), 200

        samples = payload.get("samples")
        if not isinstance(samples, list):
            return jsonify({"status": "ERROR", "message": "samples must be a JSON list"}), 400

        if len(samples) < 250:
            return jsonify({"status": "WAITING", "message": "Not enough raw ECG samples"}), 200
        if len(samples) > 5000:
            return jsonify({"status": "ERROR", "message": "Too many samples. Send 5 seconds only."}), 400

        sample_rate = get_optional_float(payload, "sample_rate", "sampleRate", "fs") or 250.0

        ml_prediction_class, ml_prediction_label, ml_confidence = predict_raw_waveform_status(samples)
        bpm = estimate_bpm_for_display(samples, sample_rate)

        prediction_class, prediction_label, confidence, decision_message = apply_bpm_simulator_rule(
            ml_prediction_class, ml_prediction_label, ml_confidence, bpm
        )

        row = None
        save_message = "Raw waveform ML prediction saved to PostgreSQL"
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
                    None,
                    None,
                    0.0,
                    None,
                    bpm,
                    prediction_class,
                    prediction_label,
                    confidence,
                    "ESP32_RAW_WAVEFORM_ML",
                    RAW_MODEL_PATH,
                    decision_message,
                ),
                fetch_one=True,
            )
        except Exception as db_exc:
            save_message = f"Prediction made, but database save failed: {db_exc}"

        return jsonify({
            "status": prediction_label,
            "prediction_label": prediction_label,
            "prediction_class": prediction_class,
            "confidence": confidence,
            "heart_rate": bpm,
            "bpm": bpm,
            "sample_rate": sample_rate,
            "sample_count": len(samples),
            "decision_message": decision_message,
            "ml_label": ml_prediction_label,
            "ml_confidence": ml_confidence,
            "message": save_message,
            "saved_record": row,
        }), 201

    except Exception as exc:
        return jsonify({"status": "ERROR", "message": str(exc)}), 400


@app.route("/api/raw-model-status")
def api_raw_model_status():
    bundle = load_raw_model_bundle()
    return jsonify({
        "raw_model_path": RAW_MODEL_PATH,
        "raw_model_exists": Path(RAW_MODEL_PATH).exists(),
        "raw_model_loaded": bundle is not None,
        "raw_model_error": RAW_MODEL_LOAD_ERROR,
        "decision_rule": "ML_ONLY_FOR_NORMAL_ABNORMAL",
    })


@app.route("/api/esp32/features", methods=["POST"])
def api_esp32_features():
    """
    Direct ESP32 WiFi endpoint for V2.
    Backward compatible:
    - If ESP32 sends raw waveform samples here by mistake, process it using raw waveform ML.
    - If ESP32 sends RR/features, process it using the older feature endpoint.
    """
    payload = request.get_json(silent=True) or {}

    # SAFETY PATCH: if the Arduino accidentally posts raw ECG samples to /api/esp32/features,
    # do not return "Missing pre_rr_s". Route it to the raw waveform ML handler.
    if isinstance(payload.get("samples"), list):
        return api_esp32_raw()

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
