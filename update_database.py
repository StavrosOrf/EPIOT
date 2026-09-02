from flask import Flask
from flask_alembic import Alembic
from flask_sqlalchemy_lite import SQLAlchemy
import datetime
from sqlalchemy import event

from geoalchemy2 import load_spatialite
from backend.charge_sessions import (
    load_daily_charging_sessions,
)

from backend.models import Model
from backend.api_calls.env_data_api import (
    create_tables_if_not_exist,
    load_electricity_data_for_supported_countries
)

import os
from sys import platform

if os.environ.get("SPATIALITE_LIBRARY_PATH") is None:

    if platform == "linux" or platform == "linux2":
        os.environ["SPATIALITE_LIBRARY_PATH"] = "mod_spatialite.so"
    elif platform == "darwin":
        os.environ["SPATIALITE_LIBRARY_PATH"] = "mod_spatialite.dylib"
    elif platform == "win32":
        os.environ["SPATIALITE_LIBRARY_PATH"] = "mod_spatialite"
    else:
        raise EnvironmentError("Unsupported platform")

app = Flask(__name__)
alembic = Alembic(metadatas=Model.metadata)
app.config["SQLALCHEMY_ENGINES"] = {"default": "sqlite:///default.sqlite"}
app.config.from_prefixed_env()
db = SQLAlchemy()
db.init_app(app)
alembic.init_app(app)

app.config["station_data.db"] = db

with app.app_context():

    @event.listens_for(db.engine, "connect")
    def load_spatialite_internal(dbapi_conn, connection_record):
        load_spatialite(dbapi_conn)


if __name__ == "__main__":

    # Load AMS data and transformer data
    date = datetime.datetime.now().date()  - datetime.timedelta(days=20)
    for _ in range(100):
        
        
        load_daily_charging_sessions(
            app, db, date=date, method="MC", scope="NL")
        date += datetime.timedelta(days=1)

    # Load electricity data from Electricity Maps API
    # Create tables if they don't exist
    create_tables_if_not_exist(app, db)
    load_electricity_data_for_supported_countries(app, db)
