from flask import Flask
from flask_alembic import Alembic
from flask_sqlalchemy_lite import SQLAlchemy

from sqlalchemy import event

from geoalchemy2 import load_spatialite
from backend.spatialite import configure_spatialite
from backend.loaders import (
    load_ams_data,
    load_transformer_data,
    load_distributions,
    reset_grid_connections,
    add_grid_connections,
)
from backend.charge_sessions import (
    load_daily_charging_sessions,
    charging_sessions_overview,
    plot_sessions_for_charger,
    reset_charging_session_db,
)

from backend.models import Model, PowerMix, Session, ChargingPoint, Column, Location, Operator, Transformer, GridConnection, GammaDistribution
from backend.api_calls.env_data_api import (
    create_tables_if_not_exist,
    load_electricity_data_for_supported_countries
)

from getpass import getpass
from sqlalchemy import select

configure_spatialite()

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
            
    # Uncomment the following lines to reload data after emptying
    # load_ams_data(app, db)
    # load_transformer_data(app, db)
    # reset_grid_connections(app, db)
    # add_grid_connections(app, db)

    # # ### reset charging session database
    # # reset_charging_session_db(app, db)

    # date = datetime.datetime.now().date() - datetime.timedelta(days=20)
    # for i in range(1, 50):
    #     load_daily_charging_sessions(
    #         app, db, date=date, method="MC", scope="NL")
    #     date = date + datetime.timedelta(days=1)

    # Load electricity data from Electricity Maps API
    # Create tables if they don't exist
    create_tables_if_not_exist(app, db)
    load_electricity_data_for_supported_countries(app, db)
    
    # ### plot charging sessions for specific charger
    # plot_sessions_for_charger(app, db, charger_id=6801)
    # plot_sessions_for_charger(app, db, charger_id=6802)

    # charging_sessions_overview(app, db)
