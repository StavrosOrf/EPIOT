import numpy as np

def stations_to_geojson(query_result):
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"{i}",
                "geometry": {"type": "Point", "coordinates": [r[5], r[4]]},
                "properties": {
                    "area_code": r[7],
                    "id": r[0],
                    "name": r[6],
                    "power": r[1],
                    "type": r[2],
                    "operator": r[3],
                    # Untagged rows are the Amsterdam pilot chargers
                    **({"source": r[8] or "pilot", "city": r[9], "country": r[10]} if len(r) > 10 else {}),
                },
            }
            for i, r in enumerate(query_result)
        ],
    }

    return feature_collection


def transformers_to_geojson(query_result):
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"{i}",
                "geometry": {"type": "Point", "coordinates": [r[3], r[2]]},
                "properties": {
                    "id": r[0],
                    "type": r[1],
                },
            }
            for i, r in enumerate(query_result)
        ],
    }

    return feature_collection


def find_charger_availability(charging_sessions, start_date, end_date):

    ev_info = {}    
    availability = {}
    # Calculate the difference in seconds
    time_difference = end_date - start_date
    # Convert the time difference into 30-minute intervals
    number_of_steps = int(time_difference.total_seconds() // (30 * 60))  # 30 minutes = 30 * 60 seconds
    
    # print(f'start_date: {start_date}')
    # print(f'end_date: {end_date}')
    # print(f'number_of_steps: {number_of_steps}')
    
    for session in charging_sessions:
        ev_id = session[0]
        if ev_id not in ev_info:
            
            availability[ev_id] = np.zeros(number_of_steps)
            ev_info[ev_id] = {"info": "info"}

    #  how many 30 min intervals have past since the start of the day
        start_step = int((session[1] - start_date).total_seconds() / (30*60))
        end_step = int((session[2] - start_date).total_seconds() / (30*60))
        availability[ev_id][start_step:end_step] += 1
        
    aggregated_availability = np.zeros(number_of_steps)   
    percentage_availability = [] 
    for ev_id in availability:
        aggregated_availability += availability[ev_id]

        availability[ev_id] = np.clip(availability[ev_id], 0, 1)
        percentage_availability.append(np.sum(availability[ev_id])/number_of_steps)
    
    
    weekday_availability = np.zeros(48)
    weekend_availability = np.zeros(48)
    
    starting_day_of_week = start_date.weekday() + 1
    # print(f'starting_day_of_week: {starting_day_of_week}')
    for i in range(0, number_of_steps // 48):
        if (starting_day_of_week + i) % 7 < 5:
            weekday_availability += aggregated_availability[i*48:(i+1)*48]
        else:
            weekend_availability += aggregated_availability[i*48:(i+1)*48]

    occupation_ratio = percentage_availability
    
    # print(f'percentage_availability: {percentage_availability}')
    # print(f'aggregated_availability: {aggregated_availability}')
    # print(f'weekday_availability: {weekday_availability}')
    # print(f'weekend_availability: {weekend_availability}')
    return weekday_availability, weekend_availability, occupation_ratio