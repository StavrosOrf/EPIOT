import json
from collections import defaultdict
import datetime
import numpy as np

def create_ReFlex_Query(chargers, charging_sessions, prices, start_date):
    """
    charging_sessions: A list of dicts, each with:
        {
            "id": "ev-0001",
            "minChargePower": 1000,       # optional, defaults in script if missing
            "maxChargePower": 11000,      # optional, defaults in script if missing
            "startTime": "2024-09-26T00:00:00Z",
            "endTime": "2024-09-26T03:00:00Z",
            "energyToCharge": 360000000
        }

    prices: A list of floats representing the energy price for each timestep.
            For 288 timesteps, you'd have 288 values here.
    """
    year = int(start_date.split("-")[0])
    month = int(start_date.split("-")[1])
    day = int(start_date.split("-")[2])
    start_date = datetime.datetime(year, month, day, 0, 0, 0)

    # Initialize the top-level JSON structure
    result = {
        "runType": "singleRunConfig",

        # No congestion points
        "congestionPoints": [],

        # Global target with one element per price timestep
        "globalTarget": {
            "start": f"{start_date.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            # 288 timesteps over 24 hours => 5-minute steps: PT5M
            #  If using 15-minute steps for fewer timesteps, use "PT15M", etc.
            "timeStepDuration": "PT10M",
            "elements": []
        },

        # Assets block: only EV charge points, no non-flexible assets
        "assets": {
            "evChargePoints": [],
            "nonFlexibleAssets": []
        }
    }

    # Build the list of energy price elements
    for price in prices:
        result["globalTarget"]["elements"].append({
            "targetType": "price", 
            "value": price # price / units of energy
        })

    # Group charge sessions by EV id (in case multiple sessions belong to the same EV)
    ev_sessions_by_id = defaultdict(list)
    ev_info = {}
    
    availability = {}

    for session in charging_sessions:
        ev_id = session[0]
        if ev_id not in ev_info:
            power_limit = chargers[ev_id]
            if power_limit is None or power_limit <= 0:
                power_limit = 11
            
            availability[ev_id] = np.zeros(288)
                
            ev_info[ev_id] = {
                # Default min/max if not provided
                "minChargePower": int(0),
                "maxChargePower": int(power_limit*1000)
            }

        ev_sessions_by_id[ev_id].append({
            "startTime": session[1].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": session[2].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "energyToCharge": int(session[3] *  3.6e6)  # Convert from kWh to J
        })
        # find how many 10 min intervals have past since the start of the day
        start_step = int((session[1] - start_date).seconds / 600)
        end_step = int((session[2] - start_date).seconds / 600)
        availability[ev_id][start_step:end_step] = 1

    # Populate the "evChargePoints" list in the final JSON
    for ev_id, sessions in ev_sessions_by_id.items():
        result["assets"]["evChargePoints"].append({
            "id": f"{ev_id}",
            "minChargePower": ev_info[ev_id]["minChargePower"],
            "maxChargePower": ev_info[ev_id]["maxChargePower"],
            "chargeSessions": sessions
        })

    return result, availability