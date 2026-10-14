from sqlalchemy import ForeignKey, Date, DateTime, String, Float, Integer, Boolean
from geoalchemy2 import Geometry
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm import relationship
from typing import List
from sqlalchemy.ext.hybrid import hybrid_property


class Model(DeclarativeBase):
    pass


class Column(Model):
    __tablename__ = "columns"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    comissioning_date: Mapped[str] = mapped_column(DateTime, nullable=True)
    net_capacity: Mapped[float] = mapped_column(Float, nullable=True)
    elaadnl_id: Mapped[str] = mapped_column(String, nullable=True)

    charging_points: Mapped[List["ChargingPoint"]] = relationship(
        back_populates="column", cascade="all, delete-orphan"
    )
    location: Mapped["Location"] = relationship(back_populates="columns")
    operator: Mapped["Operator"] = relationship(back_populates="columns")


class ChargingPoint(Model):
    __tablename__ = "charging_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    column_id: Mapped[int] = mapped_column(ForeignKey("columns.id"))
    type: Mapped[str] = mapped_column(String, nullable=True)
    power: Mapped[float] = mapped_column(Float, nullable=True)

    column: Mapped["Column"] = relationship(back_populates="charging_points")


class Location(Model):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    street: Mapped[str] = mapped_column(String, nullable=True)
    locator_designator: Mapped[str] = mapped_column(String, nullable=True)
    supplement: Mapped[str] = mapped_column(String, nullable=True)
    postal_name: Mapped[str] = mapped_column(String, nullable=True)
    zip_code: Mapped[str] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=True)
    country: Mapped[str] = mapped_column(String, nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=True)
    geom: Mapped[Geometry] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326), nullable=True
    )

    columns: Mapped[List["Column"]] = relationship(
        back_populates="location", cascade="all, delete-orphan"
    )


class Operator(Model):
    __tablename__ = "operators"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)

    columns: Mapped[List["Column"]] = relationship(
        back_populates="operator", cascade="all, delete-orphan"
    )


class Transformer(Model):
    __tablename__ = "transformers"
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    type: Mapped[str] = mapped_column(String, nullable=True)


class GridConnection(Model):
    __tablename__ = "grid_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    transformer_id: Mapped[int] = mapped_column(ForeignKey("transformers.id"))
    column_id: Mapped[int] = mapped_column(ForeignKey("columns.id"))

class PowerMix(Model):
    __tablename__ = "power_mixes"
    id: Mapped[int] = mapped_column(primary_key=True)
    country_zone: Mapped[str] = mapped_column(String, nullable=False)
    datetime: Mapped[str] = mapped_column(DateTime, nullable=False)
    renewable_percentage: Mapped[float] = mapped_column(Float, nullable=False)
    co2_intensity: Mapped[float] = mapped_column(Float, nullable=False)
    fossil_free_percentage: Mapped[float] = mapped_column(Float, nullable=True)
    power_consumption_total: Mapped[float] = mapped_column(Float, nullable=True)

class Session(Model):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    cp_id: Mapped[int] = mapped_column(ForeignKey("charging_points.id"))
    start: Mapped[str] = mapped_column(DateTime, nullable=True)
    end: Mapped[str] = mapped_column(DateTime, nullable=True)
    consumption: Mapped[float] = mapped_column(Float, nullable=True)

    @hybrid_property
    def duration(self):
        return self.end - self.start


class GammaDistribution(Model):
    __tablename__ = "gamma_distributions"
    id: Mapped[int] = mapped_column(primary_key=True)
    day_type: Mapped[int] = mapped_column(Integer, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    shape: Mapped[float] = mapped_column(Float, nullable=False)
    scale: Mapped[float] = mapped_column(Float, nullable=False)


class ForecastRun(Model):
    """One explicitly identified forecast batch; timestamps are stored as UTC."""

    __tablename__ = "forecast_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    target_date = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String, nullable=False)
    issued_at = mapped_column(DateTime, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)


class ForecastHour(Model):
    __tablename__ = "forecast_hourly"
    run_id: Mapped[str] = mapped_column(ForeignKey("forecast_runs.id"), primary_key=True)
    cp_id: Mapped[int] = mapped_column(ForeignKey("charging_points.id"), primary_key=True)
    timestamp = mapped_column(DateTime, primary_key=True)
    occupancy_probability: Mapped[float] = mapped_column(Float, nullable=False)
    occupied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    energy_kwh: Mapped[float] = mapped_column(Float, nullable=False)


class ForecastSession(Model):
    """Approximate sessions derived from CPFT hourly occupancy, not observations."""

    __tablename__ = "forecast_sessions"
    run_id: Mapped[str] = mapped_column(ForeignKey("forecast_runs.id"), primary_key=True)
    cp_id: Mapped[int] = mapped_column(ForeignKey("charging_points.id"), primary_key=True)
    session_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    start = mapped_column(DateTime, nullable=False)
    end = mapped_column(DateTime, nullable=False)
    energy_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    start_censored: Mapped[bool] = mapped_column(Boolean, nullable=False)
    end_censored: Mapped[bool] = mapped_column(Boolean, nullable=False)
