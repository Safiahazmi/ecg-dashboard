RENDER DEPLOYMENT NOTES

Build Command:
pip install -r requirements.txt

Start Command:
gunicorn app:app

Environment Variable on Render Web Service:
DATABASE_URL = paste the Internal Database URL from Render PostgreSQL

For your local ESP32 bridge connecting to Render PostgreSQL:
In your local .env file, use DATABASE_URL = paste the External Database URL from Render PostgreSQL.
Then run: python python_features_ml_bridge_postgresql.py
