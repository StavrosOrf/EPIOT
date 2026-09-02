from shapely import Point
from shapely.geometry import box
from sqlalchemy import func, select
import geopandas as gpd
from backend.models import (
    Location,
    Column,
    Operator,
    ChargingPoint,
    Transformer,
    GammaDistribution,
    GridConnection,
)
import json
import pandas as pd
import re

GDF_CITY = gpd.read_file("./data/wijkenbuurten_2022_v2_amsterdam.gpkg")
GDF_CITY = GDF_CITY.to_crs("EPSG:4326")
GDF_CITY.crs = "EPSG:4326"

# download from https://service.pdok.nl/liander/elektriciteitsnetten/atom/liander_elektriciteitsnetten.xml
TRANSFORMERS = "./data/liander_elektriciteitsnetten.gpkg"


def load_ams_data(app, db):
    with app.app_context():
        with open("./data/chargers_data_ams.json", "r") as f:
            data_entries = json.load(f)
        for entry in data_entries:
            address_info = entry["AddressInfo"]
            operator_info = entry["OperatorInfo"]
            operators_reference = entry.get("OperatorsReference", None)
            if operators_reference is not None:
                elaadnl_id = re.findall(r"EVnetNL (.*)", operators_reference)
                if len(elaadnl_id) > 0:
                    elaadnl_id = elaadnl_id[0]
                else:
                    elaadnl_id = None
            else:
                elaadnl_id = None
            # Messy because source data is messy, we can do better but may need geocoding or cleaning
            db.session.merge(
                Location(
                    id=address_info["ID"],
                    street=address_info["AddressLine1"],
                    locator_designator=address_info["AddressLine2"],
                    postal_name=address_info["Town"],
                    zip_code=address_info["Postcode"],
                    state=address_info["StateOrProvince"],
                    country=address_info["Country"]["Title"],
                    supplement=match_buurten(
                        address_info["Longitude"], address_info["Latitude"]
                    ),
                    latitude=address_info["Latitude"],
                    longitude=address_info["Longitude"],
                    geom="POINT({} {})".format(
                        address_info["Longitude"], address_info["Latitude"]
                    ),
                )
            )
            if operator_info is not None:
                db.session.merge(
                    Operator(id=operator_info["ID"],
                             name=operator_info["Title"])
                )
                operator_id = operator_info["ID"]
                operator_name = operator_info["Title"]
            else:
                operator_id = 1
                operator_name = "(Unknown Operator)"
                db.session.merge(Operator(id=operator_id, name=operator_name))

            db.session.merge(
                Column(
                    id=entry["ID"],
                    operator_id=operator_id,
                    location_id=address_info["ID"],
                    elaadnl_id=elaadnl_id,
                )
            )
            for conn in entry["Connections"]:
                type_ = "fast" if conn["Level"]["IsFastChargeCapable"] else "regular"
                db.session.merge(
                    ChargingPoint(
                        id=conn["ID"],
                        column_id=entry["ID"],
                        type=type_,
                        power=conn["PowerKW"],
                    )
                )

        db.session.commit()


def match_buurten(longitude, latitude):
    possible_codes = GDF_CITY.loc[
        GDF_CITY.contains(Point(longitude, latitude)), "buurtcode"
    ]
    if len(possible_codes) > 0:
        code = possible_codes.values[0]
    else:
        code = None
    return code


def load_transformer_data(app, db):
    with app.app_context():
        layers = {
            "laagspanningsverdeelkasten": "Low",
            "middenspanningsinstallaties": "Middle",
            "onderstations": "High",
        }
        # use 30K to avoid id conflicts
        current_id = 30000
        for layer, voltage in layers.items():
            data = gpd.read_file(TRANSFORMERS, layer=layer)
            data = data.to_crs("EPSG:4326")
            data.crs = "EPSG:4326"
            data = data.loc[data.within(box(*GDF_CITY.unary_union.bounds))]
            for row in data.iterrows():
                db.session.merge(
                    Location(
                        id=current_id,
                        latitude=row[1].geometry.y,
                        longitude=row[1].geometry.x,
                        geom=row[1].geometry.wkt,
                    )
                )
                db.session.merge(
                    Transformer(
                        id=row[1].id,
                        location_id=current_id,
                        type=voltage,
                    )
                )
                current_id += 1
        db.session.commit()


import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import aliased

# models already in your file:
# from backend.models import Location, Column, Transformer, ChargingPoint, GridConnection

def add_grid_connections(app, db, within_m=50_000, voltage_type="Middle", reset_table=True, batch=2000):
    """
    Link each Column (charger cabinet/site) to its nearest Transformer(type==voltage_type)
    using haversine (SQLite-safe). Writes GridConnection (column_id, transformer_id).
    """
    with app.app_context():
        if reset_table:
            db.session.query(GridConnection).delete()
            db.session.commit()

        # ---- Columns with coords
        col_loc = aliased(Location, name="col_loc")
        rows_col = db.session.execute(
            select(Column.id, col_loc.latitude, col_loc.longitude)
            .join(col_loc, Column.location_id == col_loc.id)
            .where(col_loc.latitude.isnot(None), col_loc.longitude.isnot(None))
        ).all()
        if not rows_col:
            print("[grid] No columns with coordinates.")
            return

        col_ids  = np.array([r[0] for r in rows_col], dtype=np.int64)
        col_lats = np.array([r[1] for r in rows_col], dtype=float)
        col_lons = np.array([r[2] for r in rows_col], dtype=float)

        # ---- Middle transformers with coords
        tf_loc = aliased(Location, name="tf_loc")
        rows_tf = db.session.execute(
            select(Transformer.id, tf_loc.latitude, tf_loc.longitude)
            .join(tf_loc, Transformer.location_id == tf_loc.id)
            .where(Transformer.type == voltage_type)
            .where(tf_loc.latitude.isnot(None), tf_loc.longitude.isnot(None))
        ).all()
        if not rows_tf:
            print(f"[grid] No transformers with type '{voltage_type}'.")
            return

        tf_ids  = np.array([r[0] for r in rows_tf], dtype=np.int64)
        tf_lats = np.array([r[1] for r in rows_tf], dtype=float)
        tf_lons = np.array([r[2] for r in rows_tf], dtype=float)

        # ---- Haversine in vectorized batches
        R = 6371000.0
        tf_phi = np.radians(tf_lats)
        tf_lam = np.radians(tf_lons)

        def nearest(lat_chunk, lon_chunk):
            phi1 = np.radians(lat_chunk)[:, None]
            lam1 = np.radians(lon_chunk)[:, None]
            dphi = tf_phi[None, :] - phi1
            dlam = tf_lam[None, :] - lam1
            a = np.sin(dphi/2)**2 + np.cos(phi1) * np.cos(tf_phi) * np.sin(dlam/2)**2
            c = 2*np.arctan2(np.sqrt(a), np.sqrt(1-a))
            dist = R * c                                  # (m, n_tf)
            idx = np.argmin(dist, axis=1)                 # nearest tf per row
            dmin = dist[np.arange(dist.shape[0]), idx]
            return idx, dmin

        new_objs = []
        skipped = 0
        n = len(col_ids)
        for s in range(0, n, batch):
            e = min(s+batch, n)
            idx, dmin = nearest(col_lats[s:e], col_lons[s:e])
            tf_near = tf_ids[idx]
            for cid, tfid, d in zip(col_ids[s:e], tf_near, dmin):
                if within_m is not None and (not np.isfinite(d) or d > within_m):
                    skipped += 1
                    continue
                new_objs.append(GridConnection(transformer_id=int(tfid), column_id=int(cid)))

        # Bulk insert
        if new_objs:
            db.session.bulk_save_objects(new_objs)
            db.session.commit()

        print(f"[grid] Inserted {len(new_objs)} connections; skipped {skipped} beyond {within_m} m.")


def reset_grid_connections(app, db):
    with app.app_context():
        db.session.query(GridConnection).delete()
        db.session.commit()
        print("Grid connections reset")


def load_distributions(app, db):
    with app.app_context():
        # TODO: build distributions
        distributions = [
            {"day_type": 0, "hour": 17, "shape": 1.5, "scale": 16.0}]
        current_id = 0
        for dist in distributions:
            db.session.merge(GammaDistribution(**dist))
            current_id += 1
        db.session.commit()
