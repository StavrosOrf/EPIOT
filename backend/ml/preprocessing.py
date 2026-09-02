import pandas as pd
import numpy as np

class Processing:
    def __init__(self):   
        return
    
    def remove_outliers(self, data):
        """Remove outliers."""
        # Implement outlier removal logic (e.g., using IQR or Z-score)
        return data[data < data.quantile(0.95)]  

    def fill_missing_values(self, data):
        """Handle missing values."""
        return data.fillna(method='ffill').fillna(method='bfill')

    def _parse_date(self, date_str):
        """ Parse dates"""
        formats = ['%Y-%m-%d %H:%M:%S%z', '%Y-%m-%d %H:%M:%S.%f%z', '%Y-%m-%d %H:%M:%S.%f']
        for fmt in formats:
            try:
                return pd.to_datetime(date_str, format=fmt)
            except ValueError:
                pass
        # If parsing fails for all formats, print the timestamp and return NaT (Not a Time)
        print(f"Error parsing timestamp: {date_str}")
        return pd.NaT
     
    def process(self, data):
        """ Process the data"""
        tower_ids = [137, 187, 213, 214, 215, 216]
        filtered_data = data[data['tower_id'].isin(tower_ids)].copy()
        filtered_data['timestamp'] = pd.to_datetime(filtered_data['timestamp'], errors='coerce')
        filtered_data['kwh_diff'] = filtered_data.groupby(['tower_id', 'plug_number'])['kwh'].diff()
        columns_to_retrieve = ['timestamp', 'tower_id', 'plug_number', 'tower_latitude', 'tower_longitude', 'kwh_diff']
        df = filtered_data[columns_to_retrieve]

        df['timestamp'] = df['timestamp'].apply(lambda x: self._parse_date(str(x))) 
        df = df.dropna(subset=['timestamp'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df['kwh_diff'] = df['kwh_diff'].fillna(0)

        df = df.set_index('timestamp')
        
        # Define how to resample
        resampled_df = (
            df.groupby(['tower_id', 'plug_number'])
            .resample('1h')
            .agg({
                'kwh_diff': 'sum',  # Summing kWh_diff over each hour
                'tower_latitude': 'first',  
                'tower_longitude': 'first'
            })
            .reset_index()
        )
        resampled_df['kwh_diff'] = resampled_df['kwh_diff'].fillna(0)
        #print('data before pivot:\n', resampled_df)

        df_pivot = resampled_df.pivot_table(
          index='timestamp', 
          columns='tower_id', 
          values='kwh_diff', 
          aggfunc='sum'  # Use an aggregation function suitable for your data
      )
        df_pivot = df_pivot.fillna(0)
        #df_pivot = resampled_df.pivot(index='timestamp', columns='tower_id', values=['kwh_diff'])

        #print('Processed data:\n', df_pivot.head)
        return df_pivot
        
    def create_input_sequence(self, data, look_back):
      return data[-look_back:]
        