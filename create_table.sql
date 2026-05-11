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
