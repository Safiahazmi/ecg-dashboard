"""
Python bridge for ESP32 ECG features + ML prediction + PostgreSQL.

Expected serial line format from ESP32:
pre_rr,post_rr,r_peak,qrs_interval
Example:
0.9016,0.7953,1665.31,0.0844

Units stored in PostgreSQL:
- pre_rr: seconds from feature extraction
- post_rr: seconds from feature extraction
- r_peak: ADC/raw amplitude
- qrs_interval: seconds from feature extraction

Dashboard display units:
- 0_pre-RR, 0_post-RR, 0_qrs_interval are converted to ms on screen
- 0_rPeak is displayed as ADC
"""

import os
import time
from dotenv import load_dotenv
import joblib
import numpy as np
import psycopg2
import serial

load_dotenv()

# =========================
# USER SETTINGS
# =========================
SERIAL_PORT = os.getenv("SERIAL_PORT", "COM3")   # Change to your ESP32 COM port
BAUD_RATE = int(os.getenv("BAUD_RATE", "115200"))
MODEL_PATH = os.getenv("MODEL_PATH", "ecg_hardware_friendly_model.joblib")
DEVICE_ID = os.getenv("DEVICE_ID", "ESP32_AD8232_01")

DATABASE_URL = os.getenv("DATABASE_URL")  # Use Render External Database URL on your laptop
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "ecg_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_PORT = os.getenv("DB_PORT", "5432")

LABEL_MAP = {
    0: "NORMAL",
    1: "ABNORMAL",
}


def connect_db():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)

    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
    )


def insert_prediction(pre_rr, post_rr, r_peak, qrs_interval, prediction_class, prediction_label, confidence=None):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ecg_predictions
        (device_id, pre_rr, post_rr, r_peak, qrs_interval, prediction_class, prediction_label, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """,
        (DEVICE_ID, pre_rr, post_rr, r_peak, qrs_interval, int(prediction_class), prediction_label, confidence),
    )
    conn.commit()
    cur.close()
    conn.close()


def parse_serial_line(line):
    clean = line.strip()
    if not clean:
        return None

    # Allows optional prefixes such as FEATURES:0.9016,0.7953,1665.31,0.0844
    if ":" in clean:
        clean = clean.split(":", 1)[1]

    parts = [p.strip() for p in clean.split(",")]
    if len(parts) != 4:
        return None

    pre_rr, post_rr, r_peak, qrs_interval = [float(x) for x in parts]
    return pre_rr, post_rr, r_peak, qrs_interval


def get_confidence(model, features):
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(features)[0]
        return float(np.max(probabilities) * 100.0)
    return None


def main():
    print("Loading ML model:", MODEL_PATH)
    model = joblib.load(MODEL_PATH)

    print("Opening serial port:", SERIAL_PORT)
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)

    print("Bridge started. Waiting for ESP32 feature data...")
    print("Expected: pre_rr,post_rr,r_peak,qrs_interval")

    while True:
        try:
            raw_line = ser.readline().decode("utf-8", errors="ignore").strip()
            parsed = parse_serial_line(raw_line)
            if parsed is None:
                continue

            pre_rr, post_rr, r_peak, qrs_interval = parsed
            features = np.array([[pre_rr, post_rr, r_peak, qrs_interval]], dtype=float)

            prediction_class = int(model.predict(features)[0])
            prediction_label = LABEL_MAP.get(prediction_class, "ABNORMAL")
            confidence = get_confidence(model, features)

            insert_prediction(
                pre_rr=pre_rr,
                post_rr=post_rr,
                r_peak=r_peak,
                qrs_interval=qrs_interval,
                prediction_class=prediction_class,
                prediction_label=prediction_label,
                confidence=confidence,
            )

            print(
                f"Saved: pre_rr={pre_rr}, post_rr={post_rr}, r_peak={r_peak}, "
                f"qrs={qrs_interval}, prediction={prediction_label}, confidence={confidence}"
            )

        except KeyboardInterrupt:
            print("Bridge stopped by user.")
            break
        except Exception as exc:
            print("ERROR:", exc)
            time.sleep(1)


if __name__ == "__main__":
    main()
