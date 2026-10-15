"""'
This is the main file for the Flask server. It contains the endpoints for the data that is displayed on the map.
"""

import gzip
import mimetypes
import os
import threading

from flask import Flask, render_template, jsonify, request, url_for, send_from_directory
from flask_alembic import Alembic
from flask_sqlalchemy_lite import SQLAlchemy
from sqlalchemy import text


def env_flag(name, default):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


# The Werkzeug debugger and reloader run only when the file is started directly
# (`python app.py`). A WSGI server importing `app:app` is production, with
# ProxyFix, unless EPIOT_DEBUG=1; EPIOT_DEBUG=0 turns debug off for `python app.py`.
DEBUG = env_flag("EPIOT_DEBUG", default=__name__ == "__main__")

# The vendored icon and text fonts (static/vendor) are not in every platform's MIME table
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

if not DEBUG:
    # Use ProxyFix only in production when behind a proxy
    from werkzeug.middleware.proxy_fix import ProxyFix

from sqlalchemy import event
from geoalchemy2 import load_spatialite
from backend.api_errors import register_json_errors
from backend.models import Model
from backend.spatialite import configure_spatialite
from backend.views import station_data
from backend.features import features_data
from backend.kpi.user import kpi_data

configure_spatialite()

db = SQLAlchemy()
app = Flask(
    __name__,
    static_url_path="",
    static_folder="static",
    template_folder="templates",
)
app.config["SQLALCHEMY_ENGINES"] = {"default": "sqlite:///default.sqlite"}
# Debug mode would pretty-print JSON, which triples the charger payloads
app.json.compact = True
app.config.from_prefixed_env()
db.init_app(app)


app.config["station_data.db"] = db


def warm_start_view():
    """Read the Amsterdam start view's tiles before the first visitor asks."""
    from backend.map_density import density_version
    from backend.models import Location
    from backend.station_cache import StationCache
    from backend.views import station_columns
    try:
        with app.app_context():
            cache = app.extensions.setdefault("station_cache", StationCache())
            version = density_version(app, db.engine)
            cache.warm(db.session, station_columns(), Location, version, (4.5, 52.1, 5.3, 52.6))
    except Exception as error:  # a cold cache is only slower
        app.logger.warning("Could not warm the charger cache: %s", error)


@app.after_request
def compress_json(response):
    """Gzip large JSON bodies (the charger and transformer lists run to megabytes)."""
    if (response.mimetype == "application/json" and not response.direct_passthrough
            and response.status_code == 200 and "Content-Encoding" not in response.headers
            and "gzip" in request.headers.get("Accept-Encoding", "")):
        body = response.get_data()
        if len(body) > 4096:
            response.set_data(gzip.compress(body, compresslevel=5))
            response.headers["Content-Encoding"] = "gzip"
            response.headers.add("Vary", "Accept-Encoding")
    return response


app.register_blueprint(station_data, url_prefix="/stations")
app.register_blueprint(features_data, url_prefix="/features")
app.register_blueprint(kpi_data, url_prefix="/kpi")

with app.app_context():

    @event.listens_for(db.get_engine(), "connect")
    def load_spatialite_inernal(dbapi_conn, _):
        load_spatialite(dbapi_conn)


alembic = Alembic(metadatas=Model.metadata)
alembic.init_app(app)

if not DEBUG:
    # Use ProxyFix only in production when behind a proxy
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

register_json_errors(app, {"station_data", "features_data", "kpi"})


@app.route("/healthz")
def healthz():
    """Liveness for a reverse proxy: the database answers and SpatiaLite is loaded."""
    try:
        version = db.session.execute(text("SELECT spatialite_version()")).scalar()
    except Exception:
        app.logger.exception("Health check failed")
        return jsonify(status="error"), 503
    response = jsonify(status="ok", spatialite=version)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/static/<path:filename>")
def serve_static(filename):
    # Some Windows registries map .js to text/plain, which browsers refuse for
    # ES modules, so scripts get an explicit type; everything else is guessed.
    mimetype = "application/javascript" if filename.endswith((".js", ".mjs")) else None
    return send_from_directory("static", filename, mimetype=mimetype)


@app.route("/")
def index():
    """This is the main endpoint for the web application. It renders the index.html file."""
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory("static/images", "favicon.ico", mimetype="image/x-icon")


@app.route("/marker_icon", methods=["GET"])
def get_marker_icon():
    return jsonify(
        {
            "charge_icon": url_for(
                "static", filename="images/charger_icon.png", _external=True
            ),
            "transformer_icon": url_for(
                "static", filename="images/transformer_icon.png", _external=True
            ),
            "flexibility_icon": url_for(
                "static", filename="images/flexibility_icon.png", _external=True
            ),
            "enter_icon": url_for(
                "static", filename="images/enter_icon.png", _external=True
            ),
            "drive2X_LOGO": url_for(
                "static", filename="images/drive2X_LOGO.png", _external=True
            ),
            "eu_logo": url_for("static", filename="images/eu_logo.png", _external=True),
            "ukri_logo": url_for(
                "static", filename="images/ukri_logo.png", _external=True
            ),
            "info_icon": url_for(
                "static", filename="images/information.png", _external=True
            ),
        }
    )


if __name__ == "__main__" and (not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
    threading.Thread(target=warm_start_view, daemon=True).start()

if __name__ == "__main__":

    if DEBUG:        
        # For development
        app.run(debug=True)
    else:
        # For production
        app.run(debug=False,
                host="0.0.0.0",
                port=5000)
