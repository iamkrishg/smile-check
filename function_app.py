"""
Azure Functions entry point for Smile Check.

Azure Functions runs this file. It wraps the normal Flask app (app.py),
so the same website works on your laptop (python app.py) AND on Azure.

Settings (endpoint, key, deployment) come from the Function App's
"Environment variables" in the Azure portal instead of the .env file.
"""
import logging

import azure.functions as func

from app import app as flask_app, azure_ready, AZURE_DEPLOYMENT

logging.info("Smile Check starting on Azure Functions. AI mode: %s",
             f"Azure {AZURE_DEPLOYMENT}" if azure_ready() else "PRACTICE (check Environment variables)")

# Sends every web address (/, /home, /api/check, /static/...) to the Flask app.
app = func.WsgiFunctionApp(app=flask_app.wsgi_app,
                           http_auth_level=func.AuthLevel.ANONYMOUS)
