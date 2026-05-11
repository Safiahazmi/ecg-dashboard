ECG DASHBOARD FINAL FIX
=======================

File yang perlu replace / upload:

1. app.py
   - Tambah endpoint /api/esp32/features untuk ESP32 WiFi.
   - Tambah validation ECG features supaya bacaan tidak realistik tidak dimasukkan ke database.
   - Load model ML daripada ecg_hardware_friendly_model_small.joblib.

2. requirements.txt
   - Tambah scikit-learn supaya error "No module named 'sklearn'" selesai.
   - Pin Python ML libraries supaya model joblib boleh load di Render.

3. ecg_hardware_friendly_model_small.joblib
   - Ini model hardware-friendly yang sudah compressed.
   - Saiz bawah 25 MB, boleh upload ke GitHub browser.
   - Letak sama level dengan app.py.

4. create_table.sql
   - Table ecg_predictions dan patients.
   - Tambah column tambahan jika database lama belum ada.

5. .python-version
   - Paksa Render guna Python 3.10.13.

6. esp32_wifi_code/esp32_wifi_ecg_ml_monitor/esp32_wifi_ecg_ml_monitor.ino
   - WiFi direct ke Render.
   - SERVER_URL sudah diset kepada:
     https://ecg-dashboard-jf8e.onrender.com/api/esp32/features
   - Fix R-peak/RR logic supaya preRR 4.5s tidak dihantar ke server.

Render Environment Variables yang perlu ada:

DATABASE_URL = Internal Database URL Render PostgreSQL
PYTHON_VERSION = 3.10.13
MODEL_PATH = ecg_hardware_friendly_model_small.joblib
ESP32_API_KEY = safiah_ecg_2026

Selepas upload ke GitHub:
1. Render > Manual Deploy > Clear build cache & deploy
2. Tunggu deploy selesai.
3. Upload semula Arduino code ke ESP32.
4. Serial Monitor baud rate: 115200.

Output yang betul:
HTTP Code: 201
Response: {"status":"NORMAL",...}

atau

HTTP Code: 201
Response: {"status":"ABNORMAL",...}

Jika keluar WAITING:
- Itu bukan server error.
- Maksudnya signal ECG/RR belum stabil.
- Betulkan electrode dan tunggu beberapa beat stabil.
