import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

# Define the base URL for the Energy-Charts API
BASE_URL = 'https://api.energy-charts.info/price'


def retrieve_day_ahead_prices(date: str,
                              days_ahead: int = 1,
                              country_code: str = 'NL') -> pd.DataFrame:
    """
    Retrieve day-ahead electricity prices for a specific date and country.

    Parameters:
    - date (str): Date in 'YYYY-MM-DD' format.
    - country_code (str): Country code (e.g., 'NL' for Netherlands).

    Returns:
    - pd.DataFrame: DataFrame with timestamps and prices.
    """
    start_date = datetime.strptime(date, "%Y-%m-%d")
    end_date = start_date + timedelta(days=days_ahead - 1)
    params = {
        'bzn': country_code,
        'start': f'{start_date.strftime("%Y-%m-%d")}T00:00Z',
        'end': f'{end_date.strftime("%Y-%m-%d")}T23:59Z'
    }
    # print(f'params: {params}')

    response = requests.get(BASE_URL, params=params)

    if response.status_code == 200:
        data = response.json()
        prices_list = []
        for timestamp, price in zip(data['unix_seconds'], data['price']):
            prices_list.append({
                "Timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                "Price (EUR/MWh)": price
            })

        df = pd.DataFrame(prices_list)
        # Ensure the 'Timestamp' column is in datetime format
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])

        # Set 'Timestamp' as the index
        df.set_index('Timestamp', inplace=True)

        # Create explicit 10-minute intervals for exactly 48 hours (288 intervals)
        start_time = df.index[0].replace(minute=0, second=0, microsecond=0)
        time_range = pd.date_range(start=start_time, periods=288, freq='10min')

        # convert from 1-hourly to 10-minute intervals by repeating each value 6 times
        resampled_df = df.reindex(time_range, method='ffill')

        # convert to numpy array
        resampled_array = resampled_df['Price (EUR/MWh)'].to_numpy()
        return resampled_array
    else:
        raise Exception(
            f"Failed to retrieve data: {response.status_code}, {response.text}")
