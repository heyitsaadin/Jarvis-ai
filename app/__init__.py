"""Jarvis AI application package (app factory)."""
import os
from datetime import timedelta
from flask import Flask

from app.config import SECRET_KEY, FLASK_CONFIG, BASE_DIR
from app.extensions import limiter


def create_app():
    app = Flask(
        __name__,
        # templates/ and static/ stay at the project root, unchanged.
        template_folder=os.path.join(BASE_DIR, "templates"),
        static_folder=os.path.join(BASE_DIR, "static"),
    )
    app.secret_key = SECRET_KEY
    app.config.update(FLASK_CONFIG)
    app.permanent_session_lifetime = timedelta(days=90)

    limiter.init_app(app)

    from app.routes import register_blueprints
    register_blueprints(app)

    # Same startup behaviour as the original: create tables, open the pool.
    from app.services.database import init_db, init_db_pool
    init_db()
    init_db_pool()

    return app
