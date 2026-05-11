import os
from flask import Flask, render_template, jsonify
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
        print("ecg_predictions table is ready.")
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
