ECG Dashboard - Tabbed Fixed Version

This version fixes:
1. Sidebar menu: only one section appears when clicked.
2. Active menu colour changes according to the selected section.
3. Correct feature units:
   - 0_pre-RR: ms (converted from seconds if raw value is below 10)
   - 0_post-RR: ms (converted from seconds if raw value is below 10)
   - 0_rPeak: ADC/raw amplitude
   - 0_qrs_interval: ms (converted from seconds if raw value is below 10)
4. Project team photos and roles:
   - Supervisor: Puan Siti Sabariah Binti Salihin
   - Team Member 1: Safiah binti Azmi - Hardware Development & Dashboard System
   - Team Member 2: Guganeswari A/P Nagendrian - Report Documentation & Hardware Development
5. No CardioSense branding.

How to run:
1. Create database ecg_db in pgAdmin.
2. Run create_table.sql in pgAdmin Query Tool.
3. Rename .env.example to .env and insert your PostgreSQL password.
4. Install packages:
   pip install -r requirements.txt
5. Insert sample data:
   python insert_sample_data.py
6. Run dashboard:
   python app.py
7. Open browser:
   http://127.0.0.1:5000
