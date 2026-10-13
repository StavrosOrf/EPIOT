"""'
This is the main file for the Flask server. It contains the endpoints for the data that is displayed on the map.
"""

DEBUG = True

from flask import Flask, render_template, jsonify, url_for, send_from_directory
from flask_alembic import Alembic
from flask_sqlalchemy_lite import SQLAlchemy

if not DEBUG:
    # Use ProxyFix only in production when behind a proxy
    from werkzeug.middleware.proxy_fix import ProxyFix

from sqlalchemy import event
from geoalchemy2 import load_spatialite
from backend.models import Model
from backend.spatialite import configure_spatialite
from backend.views import station_data
from backend.features import features_data
from backend.kpi.user import kpi_data

from pathlib import Path
import yaml

configure_spatialite()

db = SQLAlchemy()
app = Flask(
    __name__,
    static_url_path="",
    static_folder="static",
    template_folder="templates",
)
app.config["SQLALCHEMY_ENGINES"] = {"default": "sqlite:///default.sqlite"}
app.config.from_prefixed_env()
db.init_app(app)


app.config["station_data.db"] = db


fp_config = Path("./backend/config.yaml")
with open(fp_config) as ipf:
    cfg = yaml.load(ipf, Loader=yaml.SafeLoader)

app.config["aggregator_config"] = cfg
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

@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory("static", filename, mimetype="application/javascript")


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


if __name__ == "__main__":

    if DEBUG:        
        # For development
        app.run(debug=True)
    else:
        # For production
        app.run(debug=False,
                host="0.0.0.0",
                port=5000)
