ECG Dashboard WiFi Update Only
==============================

Replace/add these files only:

1. Replace app.py in your dashboard project.
2. Replace requirements.txt in your dashboard project.
3. Open esp32_wifi_code/esp32_wifi_ecg_ml_monitor.ino in Arduino IDE and upload to ESP32.

Render environment variables needed:
- DATABASE_URL      = Internal Database URL from Render PostgreSQL
- PYTHON_VERSION    = 3.10.13
- MODEL_PATH        = ecg_hardware_friendly_model.joblib
- ESP32_API_KEY     = safiah_ecg_2026

Important:
- Upload ecg_hardware_friendly_model.joblib to your GitHub repo because the Render server must run the ML prediction.
- ESP32 sends features directly to: /api/esp32/features
- Dashboard design files are not changed.
- ESP32 uses WiFi and no longer needs the Python serial bridge for live dashboard updates.

Arduino settings:
- Replace SERVER_URL inside esp32_wifi_ecg_ml_monitor.ino with your real Render URL:
  https://your-service-name.onrender.com/api/esp32/features

For iPhone hotspot:
- Turn ON Personal Hotspot.
- Turn ON Maximize Compatibility so ESP32 can connect to 2.4 GHz WiFi.
- Make sure the SSID spelling is exactly the same.
