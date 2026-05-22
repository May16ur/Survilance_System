import os
from flask import Flask

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def create_app():
    app = Flask(
        __name__,
        static_folder=os.path.join(BASE_DIR, "static")
    )

    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024

    from flask_app.blueprints import register_blueprints
    register_blueprints(app)

    return app
