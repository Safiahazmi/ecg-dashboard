import csv
import io
import os
from flask import Flask, render_template, jsonify, request, Response
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

app = Flask(__name__)

# Render uses DATABASE_URL. Local PostgreSQL can still use DB_HOST/DB_NAME/etc.
DATABASE_URL = os.getenv("DATABASE_URL")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "ecg_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_PORT = os.getenv("DB_PORT", "5432")

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


@app.route("/")
def index():
    return render_template("index.html")


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
