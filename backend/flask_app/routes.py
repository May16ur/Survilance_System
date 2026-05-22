from flask import Blueprint

# Compatibility shim for older imports. New routes live in flask_app.blueprints.*
main = Blueprint("main", __name__)
