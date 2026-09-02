## these packages should be imported for the predictive module
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler

from backend.ml.preprocessing import Processing

import pandas as pd
import numpy as np


class DataScaler:
    def __init__(self):
        self.scaler = MinMaxScaler()
        self.is_fitted = False  # Track if scaler has been initialized with data

    def fit_update(self, data):
        """Fit or update the scaler incrementally with new data."""
        if not self.is_fitted:
            self.scaler.fit(data)  # Initial fitting
            self.is_fitted = True
        else:
            self.scaler.partial_fit(data)  # Incremental update with new data

    def transform(self, data):
        return self.scaler.transform(data)

    def inverse_transform(self, data):
        return self.scaler.inverse_transform(data)

class DummyModel(nn.Module):
    def __init__(self, input_size, hidden_size, output_size, num_layers, prediction_length, dropout_prob=0.3):
        super(DummyModel, self).__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.prediction_length = prediction_length
        
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
        
        # Fully connected layer maps hidden state output to the required output size
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x):
        h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
        c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
        
        out, _ = self.lstm(x, (h0, c0))  # LSTM outputs all time steps
        out = out[:, -1, :]
        # We want predictions for each time step, so pass all LSTM outputs through the fully connected layer
        out = self.fc(out)  # (batch_size, sequence_length, output_size)
        
        return out
    
##This class should be part of the Predictive Module
class PredictiveModel:
    def __init__(self, model_path, scaler):
        
        # Model parameters
        input_size = 6  
        hidden_size = 16
        output_size = 6  
        num_layers = 2
        prediction_length = 1
        self.model = DummyModel(input_size=input_size, hidden_size=hidden_size, output_size=output_size, num_layers=num_layers, prediction_length = prediction_length)
        self.model.load_state_dict(torch.load(model_path))
        #self.model = torch.load(model_path)   #!not recommended for production
        self.model.eval()  # Set model to evaluation mode
        self.scaler = scaler
        
    def predict(self, input_data):
        """Scale input, predict, and inverse scale output."""
        scaled_input = self.scaler.transform(input_data)
        scaled_input = np.expand_dims(scaled_input, axis=0)
        input_tensor = torch.tensor(scaled_input, dtype=torch.float32)
        with torch.no_grad():
            prediction = self.model(input_tensor).numpy()  # Model output
        return self.scaler.inverse_transform(prediction)  # Rescale output


if __name__ == "__main__":
            
    # Set up data sources,  and Load historical data
    historical_data_source = "path/to/historical_data.csv" #"path/to/historical_data.csv"
    historical_data = pd.read_csv(historical_data_source)
    # PRocess the data
    processing = Processing()
    processed_data = processing.process(historical_data)
    # Initialize data scaler and fit scaler
    data_scaler = DataScaler()
    data_scaler.fit_update(processed_data)

    # get the input sequence
    sequence = processing.create_input_sequence(processed_data, 24)

    # Initialize predictive module
    model_path = "path/to/model.pth" #"path/to/model.pth"
    predictive_module = PredictiveModel(model_path, data_scaler)

    predictions = predictive_module.predict(sequence)

    print(predictions)
