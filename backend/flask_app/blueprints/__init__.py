from flask_app.blueprints.blacklist import bp as blacklist_bp
from flask_app.blueprints.dashboard import bp as dashboard_bp
from flask_app.blueprints.health import bp as health_bp
from flask_app.blueprints.notifications import bp as notifications_bp
from flask_app.blueprints.logs import bp as logs_bp
from flask_app.blueprints.reports import bp as reports_bp
from flask_app.blueprints.streams import bp as streams_bp
from flask_app.blueprints.vehicles import bp as vehicles_bp


def register_blueprints(app):
    for blueprint in (
        health_bp,
        notifications_bp,
        streams_bp,
        logs_bp,
        dashboard_bp,
        reports_bp,
        vehicles_bp,
        blacklist_bp,
    ):
        app.register_blueprint(blueprint)
