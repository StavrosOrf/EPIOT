# Data model

EPIOT stores everything in one SQLite database (`instance/default.sqlite`) with the SpatiaLite
extension. The schema is defined with SQLAlchemy 2 declarative models in `backend/models.py` and
versioned with Alembic migrations in `migrations/`.

## Entity–relationship diagram

```{mermaid}
erDiagram
    OPERATOR ||--o{ COLUMN : owns
    LOCATION ||--o{ COLUMN : hosts
    COLUMN ||--|{ CHARGING_POINT : "has connectors"
    CHARGING_POINT ||--o{ SESSION : records
    LOCATION ||--o| TRANSFORMER : positions
    TRANSFORMER ||--o{ GRID_CONNECTION : feeds
    COLUMN ||--o| GRID_CONNECTION : "connected via"

    OPERATOR {
        int id PK
        string name
    }
    LOCATION {
        int id PK
        string street
        string locator_designator
        string supplement
        string postal_name
        string zip_code
        string state
        string country
        float latitude
        float longitude
        geometry geom
    }
    COLUMN {
        int id PK
        int operator_id FK
        int location_id FK
        datetime comissioning_date
        float net_capacity
        string elaadnl_id
    }
    CHARGING_POINT {
        int id PK
        int column_id FK
        string type
        float power
    }
    SESSION {
        int id PK
        int cp_id FK
        datetime start
        datetime end
        float consumption
    }
    TRANSFORMER {
        int id PK
        int location_id FK
        string type
    }
    GRID_CONNECTION {
        int id PK
        int transformer_id FK
        int column_id FK
    }
    POWER_MIX {
        int id PK
        string country_zone
        datetime datetime
        float renewable_percentage
        float co2_intensity
        float fossil_free_percentage
        float power_consumption_total
    }
    GAMMA_DISTRIBUTION {
        int id PK
        int day_type
        int hour
        float shape
        float scale
    }
```

## Tables

| Table | Model | Purpose |
|---|---|---|
| `operators` | `Operator` | Charge point operators. ID `1` is reserved for *(Unknown Operator)*. |
| `locations` | `Location` | Geographic points shared by charging columns and transformers. `geom` is a SpatiaLite `POINT` in WGS 84 (SRID 4326); `supplement` stores the CBS neighbourhood code. |
| `columns` | `Column` | A physical charging station (pole or cabinet) at one location, owned by one operator. `elaadnl_id` links to ElaadNL data when known. |
| `charging_points` | `ChargingPoint` | One connector of a column. `type` is `fast` when the source marks the connection as fast-charge capable, otherwise `regular`; `power` is the rated power in kW. |
| `sessions` | `Session` | Charging sessions per charging point. Exposes a `duration` hybrid property (`end − start`). |
| `transformers` | `Transformer` | Grid assets from the Liander dataset. `type` is the voltage level. Transformer locations use IDs from 30 000 upwards to avoid collisions with charging locations. |
| `grid_connections` | `GridConnection` | Links each column to its nearest `Middle` (MV/LV) transformer. |
| `power_mixes` | `PowerMix` | Hourly power-mix history per country zone, from Electricity Maps. |
| `gamma_distributions` | `GammaDistribution` | Reserved for storing energy-demand distributions in the database (the configuration file is used today). |

## Hierarchy of charging infrastructure

```{mermaid}
flowchart LR
    O[Operator<br/><i>e.g. EVnetNL</i>] --> C1[Column<br/>pole at a location]
    L[Location<br/>street · lat/lon · buurt] --> C1
    C1 --> P1[Charging point<br/>11 kW regular]
    C1 --> P2[Charging point<br/>11 kW regular]
    P1 --> S1[Sessions]
    P2 --> S2[Sessions]
    C1 -. nearest MV/LV .-> T[Transformer · Middle]
```

Analyses work at the **charging point** level: the map shows one marker per charging point, and
sessions, rated power and IDs in the report all refer to charging points.

## Contents of the Amsterdam dataset

The local development database covers Amsterdam:

| Entity | Rows |
|---|---|
| Operators | 25 |
| Columns | 717 |
| Charging points | 1,399 (1,360 regular, 39 fast) |
| Transformers | 28,260 (25,919 Low · 2,329 Middle · 12 High) |
| Grid connections | 717 (one per column) |
| Sessions | ~318,000 (30 Aug 2025 – 10 Jan 2026) |
| Power-mix rows | 72 (NL, hourly) |

```{figure} ../_static/figures/db-charger-power.svg
:class: chart
:alt: Bar chart of charging points by rated power

Most public charging points in Amsterdam are rated at 11 kW; a few fast chargers reach 50–300 kW.
```

## Spatial queries

Area selection relies on SpatiaLite's `ST_Within` against the `locations.geom` point column:

```python
select(ChargingPoint.id, ChargingPoint.power, ...)
    .join(ChargingPoint.column).join(Location).join(Operator)
    .filter(func.ST_Within(Location.geom, func.ST_GeomFromEWKT(polygon)))
```

The SpatiaLite extension is loaded on every new connection by an SQLAlchemy `connect` event listener
registered in `app.py`.

## Migrations

Schema changes are managed with Flask-Alembic:

```bash
uv run flask --app app db upgrade       # apply migrations
uv run flask --app app db revision "describe change"   # create a new revision
```

The initial revision is `migrations/1729161651_init.py`. The environment-data loader also calls
`Model.metadata.create_all()` to create the `power_mixes` table if it is missing.
