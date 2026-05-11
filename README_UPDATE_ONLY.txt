ECG Dashboard Update Files Only

Copy/replace these files into your existing dashboard folder:

1. app.py
2. create_table.sql
3. templates/index.html
4. static/js/dashboard.js
5. static/css/style.css

New additions:
- Project overview card on Dashboard page.
- Patient Biodata page and form for patient name and age.
- Latest patient biodata displayed on Dashboard page.
- Export Excel button on History page.
  Note: the export downloads an Excel-compatible CSV file named ecg_prediction_export.csv.
- Patient biodata table added in PostgreSQL.

After replacing files:
1. Push the updated files to GitHub if using Render.
2. Let Render redeploy.
3. The app.py file will auto-create the patients table on startup.
4. If you want to create it manually, run create_table.sql in pgAdmin/Render Query Tool.

Important:
- Do not upload your .env file to GitHub.
- Your DATABASE_URL stays in Render Environment Variables or your local .env file.
