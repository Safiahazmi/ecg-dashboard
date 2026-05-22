ECG Dashboard Update - Heart Rate Improvement

Changes made:
1. Removed the ECG Feature Trend chart from the main Dashboard page.
2. Removed the Live ECG navigation button and Live ECG page.
3. Added Heart Rate (BPM) display to the Dashboard and Prediction page.
4. Added Heart Rate Status using 60-100 BPM as Normal range; values below 60 or above 100 are marked Abnormal.
5. Added Heart Rate and Heart Rate Status columns to the History table and CSV export.
6. Updated Flask API to receive heart_rate from ESP32 or calculate it from RR interval if not provided.
7. Updated PostgreSQL table setup to include a heart_rate column.
8. Updated ESP32 WiFi code to send heart_rate and show HR/BPM on OLED.

After uploading to Render, restart/redeploy the service so the ALTER TABLE command can add the new heart_rate column automatically.
