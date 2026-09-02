from json import JSONDecodeError
from flask import abort, jsonify, request
import geojson as gj
from shapely.geometry import shape
from shapely.errors import GeometryTypeError
from backend.models import Transformer, Location
from backend.utils import transformers_to_geojson

from sqlalchemy import select, func

from flask import current_app, Blueprint


features_data = Blueprint("features_data", "features_data")


@features_data.route("/transformers/within", methods=["POST"])
def get_transformers_wtithin():
    db = current_app.config["station_data.db"]
    try:
        data = gj.loads(request.data)        
        polygon = str(shape(data))
        transformer_type = data.get("tr_type", None)
    except (JSONDecodeError, KeyError, GeometryTypeError, TypeError):
        abort(400, "Could not handle request, expected GeoJSON")
    statement = (
        select(
            Transformer.id,
            Transformer.type,
            Location.latitude,
            Location.longitude,
        )
        .join(Location)
        .filter(func.ST_Within(Location.geom, func.ST_GeomFromEWKT(polygon)))
    )

        # Add a filter for the transformer type if provided
    if transformer_type:
        statement = statement.filter(Transformer.type == transformer_type)
    
    query_result = db.session.execute(statement)
    return jsonify(transformers_to_geojson(query_result))
