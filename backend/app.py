from flask import Flask
from flask_migrate import Migrate
from flask_cors import CORS
from .database import db
from backend.models import Employee, Log


def create_app():
    app = Flask(__name__)
    CORS(app)

    # konfiguracja bazy danych (SQLite dla łatwości)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    Migrate(app, db)

    @app.route("/")
    def index():
        return {"status": "OK"}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
