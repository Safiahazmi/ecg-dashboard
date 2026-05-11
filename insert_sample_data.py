import os
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "ecg_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_PORT = os.getenv("DB_PORT", "5432")

if DATABASE_URL:
    conn = psycopg2.connect(DATABASE_URL)
else:
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
    )
cur = conn.cursor()

now = datetime.now()
samples = [
    (now - timedelta(seconds=55), "ESP32_AD8232_01", 0.9016, 0.7953, 1665.31, 0.0844, 0, "NORMAL", 93.3),
    (now - timedelta(seconds=45), "ESP32_AD8232_01", 0.8200, 0.8320, 1588.12, 0.0860, 0, "NORMAL", 98.6),
    (now - timedelta(seconds=35), "ESP32_AD8232_01", 0.6450, 1.2400, 1742.80, 0.1180, 1, "ABNORMAL", 91.8),
    (now - timedelta(seconds=25), "ESP32_AD8232_01", 0.8800, 0.8560, 1621.44, 0.0900, 0, "NORMAL", 96.9),
    (now - timedelta(seconds=15), "ESP32_AD8232_01", 1.3300, 0.6100, 1810.55, 0.1260, 1, "ABNORMAL", 90.7),
    (now - timedelta(seconds=5), "ESP32_AD8232_01", 0.9016, 0.7953, 1665.31, 0.0844, 0, "NORMAL", 93.3),
]

cur.executemany(
    """
    INSERT INTO ecg_predictions
    (timestamp, device_id, pre_rr, post_rr, r_peak, qrs_interval, prediction_class, prediction_label, confidence)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
    """,
    samples,
)

conn.commit()
cur.close()
conn.close()
print("Sample ECG prediction data inserted into PostgreSQL successfully.")
