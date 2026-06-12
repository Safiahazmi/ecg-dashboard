ECG ARRHYTHMIA DETECTION V2 - STEP BY STEP
Hardware + Machine Learning + Render + PostgreSQL + Dashboard

=====================================================
A. WHAT THIS V2 FIXES
=====================================================
The old version failed mainly because the ML training features and ESP32 hardware features were not using the same units.

Old issue:
- MIT-BIH CSV stores RR intervals as sample counts, for example 313 samples.
- MIT-BIH sampling rate is 360 Hz, so 313 samples = 313 / 360 = 0.869 seconds.
- ESP32 sends RR interval directly in seconds, for example 0.869.
- Therefore the old model learned values around 200-300, but ESP32 sent values around 0.7-1.0.

V2 fix:
- The training script converts MIT-BIH RR values from sample count to seconds.
- The ESP32 sends pre_rr_s, post_rr_s, rr_diff_s and bpm.
- The Flask/Render app predicts using the same feature units.
- r_peak is saved for dashboard/debug only. It is NOT used as ML feature because MIT-BIH rPeak and ESP32 ADC value are not the same scale.

=====================================================
B. FILES INCLUDED
=====================================================
1. app.py
   Updated Flask app for Render. Endpoint remains:
   /api/esp32/features

2. ecg_mit_hardware_model_v2.joblib
   New trained ML model using MIT-BIH rhythm features compatible with ESP32.

3. train_mit_hardware_model_v2.py
   Training script. Use this only if you want to retrain the model.

4. training_report_v2.json
   Training result and metrics.

5. esp32_wifi_code/esp32_ecg_arrhythmia_v2/esp32_ecg_arrhythmia_v2.ino
   New ESP32 code for AD8232 + OLED + WiFi + Render.

6. create_table.sql
   PostgreSQL table creation file. Existing table is still compatible.

7. templates/, static/
   Existing dashboard UI files preserved.

8. .env.example
   Example environment variable file. Do not upload real password/API key publicly.

=====================================================
C. PYTHON / RENDER SETUP
=====================================================
1. Upload these files to your GitHub repository:
   - app.py
   - requirements.txt
   - Procfile
   - create_table.sql
   - ecg_mit_hardware_model_v2.joblib
   - templates folder
   - static folder

2. In Render, set environment variables:
   MODEL_PATH=ecg_mit_hardware_model_v2.joblib
   ESP32_API_KEY=choose_your_api_key

   If you already connected Render PostgreSQL, DATABASE_URL should already be available.

3. Deploy the Render web service.

4. Open this in browser to check server:
   https://YOUR-RENDER-APP.onrender.com/api/health

Expected:
   model_exists: true
   status: OK

=====================================================
D. ESP32 CODE SETUP
=====================================================
Open:
   esp32_wifi_code/esp32_ecg_arrhythmia_v2/esp32_ecg_arrhythmia_v2.ino

Edit only these lines:
   WIFI_SSID
   WIFI_PASSWORD
   SERVER_URL
   API_KEY

Example:
   SERVER_URL = "https://your-render-app.onrender.com/api/esp32/features";
   API_KEY = "same_key_as_Render_ESP32_API_KEY";

Install Arduino libraries:
   - Adafruit GFX Library
   - Adafruit SH110X
   - WiFi and HTTPClient are included with ESP32 board package

Board setting:
   Board: ESP32 Dev Module
   Upload Speed: 115200 or 921600
   Serial Monitor: 115200 baud

=====================================================
E. HARDWARE CONNECTION
=====================================================
AD8232 to ESP32:
   AD8232 OUTPUT  -> GPIO34
   AD8232 LO+     -> GPIO32
   AD8232 LO-     -> GPIO33
   AD8232 3.3V    -> ESP32 3V3
   AD8232 GND     -> ESP32 GND

OLED SH1106/SSD1306 I2C to ESP32:
   OLED SDA -> GPIO21
   OLED SCL -> GPIO22
   OLED VCC -> 3V3 or 5V depending on OLED module
   OLED GND -> GND

ECG simulator to AD8232:
   Simulator RA -> AD8232 RA
   Simulator LA -> AD8232 LA
   Simulator RL -> AD8232 RL

Do not compare 12-lead ECG directly with this project. AD8232 module is a 3-electrode single-lead style acquisition. For comparison, compare the matching limb-lead rhythm/BPM only.

=====================================================
F. TESTING ORDER - VERY IMPORTANT
=====================================================
Do not test ML first. Test in this order.

STEP 1: Upload ESP32 code.
Expected OLED:
   ECG Arrhythmia V2
   WiFi Connected
   WAITING

STEP 2: Connect ECG simulator normal sinus rhythm.
Recommended simulator setting:
   Normal sinus rhythm
   70 BPM

Expected Serial Monitor:
   ECG FEATURE READY
   pre_rr_s around 0.85
   post_rr_s around 0.85
   BPM around 70

Expected OLED after server response:
   NORMAL
   HR: around 70 BPM

STEP 3: Test tachycardia.
Recommended simulator setting:
   130-150 BPM

Expected:
   ABNORMAL

STEP 4: Test bradycardia.
Recommended simulator setting:
   40-50 BPM

Expected:
   ABNORMAL

STEP 5: Test PVC/irregular rhythm if available.
Expected:
   ABNORMAL, especially when RR interval becomes irregular.

=====================================================
G. TROUBLESHOOTING
=====================================================
Problem: OLED shows LEADS OFF
Cause:
   LO+ or LO- is HIGH.
Fix:
   Check RA, LA, RL connection between simulator and AD8232.

Problem: OLED stuck WAITING and BPM is --
Cause:
   ESP32 is not detecting stable R-peaks.
Fix:
   1. Open Serial Monitor.
   2. Check whether ECG FEATURE READY appears.
   3. Check AD8232 OUT to GPIO34.
   4. Check simulator amplitude and lead setting.
   5. Make sure simulator is outputting limb lead ECG, not unsupported mode.

Problem: BPM appears but dashboard not updating
Cause:
   WiFi/API/Render/PostgreSQL issue.
Fix:
   1. Check Serial Monitor HTTP Code.
   2. HTTP 201 = OK saved or prediction returned.
   3. HTTP 401 = API key mismatch.
   4. HTTP 404 = wrong SERVER_URL.
   5. HTTP 500 = Render/database issue.

Problem: Normal simulator becomes ABNORMAL sometimes
Cause:
   R-peak detector may detect noise/double peak, causing RR irregularity.
Fix:
   1. Make sure ECG simulator leads are stable.
   2. Use 70 BPM normal first.
   3. Avoid touching wires during test.
   4. Increase REFRACTORY_PERIOD_MS from 250 to 300 if double-counting happens.

Problem: Abnormal simulator still NORMAL
Cause:
   Simulator abnormal mode may only change waveform morphology while hardware model is rhythm-based.
Fix:
   Use tachycardia, bradycardia, PVC or irregular rhythm mode first. The V2 model is designed for hardware-compatible rhythm features.

=====================================================
H. HOW TO RETRAIN MODEL AGAIN
=====================================================
Only do this if you want to train again.

1. Put this CSV in the same folder:
   MIT-BIH Arrhythmia Database.csv

2. Run:
   python train_mit_hardware_model_v2.py

3. It will create:
   ecg_mit_hardware_model_v2.joblib
   training_report_v2.json

4. Upload the new .joblib to GitHub/Render.

=====================================================
I. THESIS / SLIDE EXPLANATION
=====================================================
Use this explanation:

The original system did not reliably detect arrhythmia from the ECG simulator because the trained ML model used MIT-BIH interval values in sample-count format, while the ESP32 hardware generated RR intervals in seconds. Therefore, the hardware input distribution did not match the training data distribution. In V2, the MIT-BIH RR features were converted from sample counts to seconds using the 360 Hz sampling frequency. The ESP32 extracts the same hardware-compatible features, including pre-RR interval, post-RR interval, RR difference and BPM. These features are sent to the Render Flask API, where the trained machine learning model predicts Normal or Abnormal, stores the result in PostgreSQL and displays the output on the dashboard.

=====================================================
J. IMPORTANT LIMITATION
=====================================================
This is a prototype educational ECG arrhythmia detection system. It is not a clinical diagnostic device. The AD8232 single-lead setup is suitable for rhythm/BPM-based detection, but it cannot replace a certified 12-lead ECG machine for full cardiac diagnosis.
