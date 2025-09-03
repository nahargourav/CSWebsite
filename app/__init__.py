# __init__.py

from flask import Flask
from app.routes import main
import os

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "default_secret_key")
    # Set the upload folder path
    app.config['UPLOAD_FOLDER'] = os.path.join('app/static', 'uploads')

    app.register_blueprint(main)

    return app
