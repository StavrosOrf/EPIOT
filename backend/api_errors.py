"""One error shape for the JSON API."""
from flask import jsonify, request
from werkzeug.exceptions import HTTPException


def register_json_errors(app, blueprints):
    """Report HTTP errors raised in these blueprints as {"error": ...}.

    The endpoints already return that shape for the errors they handle; this
    makes `abort(400, ...)` agree with them. Pages and static files keep
    Flask's HTML errors.
    """
    names = set(blueprints)

    @app.errorhandler(HTTPException)
    def json_api_errors(error):
        if request.blueprint in names:
            return jsonify(error=error.description), error.code
        return error
