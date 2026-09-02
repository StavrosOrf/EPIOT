
from backend.models import Model

from backend.models import PowerMix

import os
import requests
import time
import datetime

from sqlalchemy import select

def create_tables_if_not_exist(app, db):
    """Create all database tables if they don't exist"""
    with app.app_context():
        try:
            # Create all tables defined in the models
            Model.metadata.create_all(db.engine)
            print("Database tables created successfully (if they didn't exist)")
            
            # Specifically check if power_mixes table exists
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            if 'power_mixes' in tables:
                print("✓ power_mixes table exists")
            else:
                print("✗ power_mixes table not found, attempting to create...")
                PowerMix.__table__.create(db.engine, checkfirst=True)
                print("✓ power_mixes table created")
                
        except Exception as e:
            print(f"Error creating tables: {e}")
            import traceback
            traceback.print_exc()


def fetch_json(url, headers, params, attempts=3, timeout=20):
    """Fetch JSON data from API with retry logic"""
    last_err = None
    for k in range(attempts):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            # Helpful message if plan/endpoint mismatch
            if r.status_code in (401, 402, 403, 404):
                raise RuntimeError(f"{r.status_code} {url} :: {r.text[:200]}")
            r.raise_for_status()
        except Exception as e:
            last_err = e
            time.sleep(1.2 * (k + 1))
    raise last_err


def get_power_breakdown_latest(api_base, headers, params):
    """Get latest power breakdown from Electricity Maps API"""
    return fetch_json(f"{api_base}/power-breakdown/latest", headers, params)


def get_power_breakdown_history(api_base, headers, params):
    """Get power breakdown history from Electricity Maps API"""
    return fetch_json(f"{api_base}/power-breakdown/history", headers, params)


def get_carbon_intensity_latest(api_base, headers, params, emission_factor_type="lifecycle"):
    """Get latest carbon intensity from Electricity Maps API"""
    q = dict(params)
    if emission_factor_type:
        q["emissionFactorType"] = emission_factor_type
    url = f"{api_base}/carbon-intensity/latest"
    return fetch_json(url, headers, q)


def get_carbon_intensity_history(api_base, headers, params, emission_factor_type="lifecycle"):
    """Get carbon intensity history from Electricity Maps API"""
    q = dict(params)
    if emission_factor_type:
        q["emissionFactorType"] = emission_factor_type
    url = f"{api_base}/carbon-intensity/history"
    return fetch_json(url, headers, q)


def load_electricity_data_for_country(app, db, country_zone="NL"):
    """
    Fetch electricity data from Electricity Maps API and store in PowerMix table for a specific country
    """
    with app.app_context():
        API_BASE = "https://api.electricitymaps.com/v3"
        
        # Get API token from environment or use hardcoded token
        TOKEN = os.getenv("ELECTRICITYMAPS_API_TOKEN")
        if not TOKEN:
            TOKEN = "en2yFnGRFe90uF24DbpR"  # Use existing token
        
        HEADERS = {"auth-token": TOKEN}
        PARAMS = {"zone": country_zone}
        
        try:
            # Get latest data
            power_data = get_power_breakdown_latest(API_BASE, HEADERS, PARAMS)
            carbon_data = get_carbon_intensity_latest(API_BASE, HEADERS, PARAMS)
            
            # Get history data (last 24 hours)
            power_history = get_power_breakdown_history(API_BASE, HEADERS, PARAMS)
            carbon_history = get_carbon_intensity_history(API_BASE, HEADERS, PARAMS)
            
            print(f"Fetched latest data for {country_zone}:")
            # print(f'power_history: {power_history}')
            # print(f'carbon_history: {carbon_history}')

            # Process historical data
            power_history_data = power_history.get("history", [])
            carbon_history_data = carbon_history.get("history", [])
            
            # Create a mapping of carbon intensity by datetime
            carbon_by_datetime = {}
            for carbon_entry in carbon_history_data:
                dt_str = carbon_entry.get("datetime")
                if dt_str:
                    carbon_by_datetime[dt_str] = carbon_entry.get("carbonIntensity", 0.0)

            # Process each historical power data point
            entries_processed = 0
            for power_entry in power_history_data:
                breakdown = power_entry.get("powerConsumptionBreakdown", {})
                total_consumption = power_entry.get("powerConsumptionTotal", 0)
                
                # Define renewable sources
                renewable_sources = ["wind", "solar", "hydro", "biomass", "geothermal"]
                renewable_power = sum(breakdown.get(source, 0) for source in renewable_sources if breakdown.get(source) is not None)
                
                renewable_percentage = 0.0
                fossil_free_percentage = power_entry.get("fossilFreePercentage", 0.0) or 0.0
                
                if total_consumption and total_consumption > 0:
                    renewable_percentage = (renewable_power / total_consumption) * 100
                
                # Get timestamp
                timestamp_str = power_entry.get("datetime")
                if timestamp_str:
                    timestamp = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                else:
                    continue
                
                # Get corresponding CO2 intensity
                co2_intensity = carbon_by_datetime.get(timestamp_str, 0.0)
                
                print(f'At {timestamp_str}: R {renewable_percentage:.1f}%, CO2 {co2_intensity:.1f} gCO2eq/kWh, Total {total_consumption} MW, Fossil Free {fossil_free_percentage:.1f}%')
                
                # Check if entry already exists for this country and datetime
                existing_entries = db.session.execute(
                    select(PowerMix).where(
                        PowerMix.country_zone == country_zone,
                        PowerMix.datetime == timestamp
                    )
                ).scalars().all()
                
                if existing_entries:
                    # Update the first existing entry and delete any duplicates
                    existing_entry = existing_entries[0]
                    existing_entry.renewable_percentage = renewable_percentage
                    existing_entry.co2_intensity = co2_intensity
                    existing_entry.fossil_free_percentage = fossil_free_percentage
                    existing_entry.power_consumption_total = total_consumption
                    
                    # Delete any duplicate entries
                    for duplicate in existing_entries[1:]:
                        db.session.delete(duplicate)
                    
                    print(f"Updated existing entry (removed {len(existing_entries)-1} duplicates)")
                else:
                    # Create new entry
                    power_mix = PowerMix(
                        country_zone=country_zone,
                        datetime=timestamp,
                        renewable_percentage=renewable_percentage,
                        co2_intensity=co2_intensity,
                        fossil_free_percentage=fossil_free_percentage,
                        power_consumption_total=total_consumption
                    )
                    db.session.add(power_mix)
                
                entries_processed += 1
            
            print(f"Processed {entries_processed} historical entries for {country_zone}")
            db.session.commit()
            print(f"Successfully loaded electricity data for {country_zone} - {entries_processed} historical entries processed")
            
        except Exception as e:
            print(f"Error: {e}")
            db.session.rollback()


def load_electricity_data_for_supported_countries(app, db):
    """
    Load electricity data for supported countries (currently only Netherlands)
    """
    supported_countries = ["NL"]  # Add more country codes as needed
    
    for country in supported_countries:
        print(f"Loading electricity data for {country}...")
        load_electricity_data_for_country(app, db, country)
        # Add delay to avoid rate limiting
        time.sleep(2)