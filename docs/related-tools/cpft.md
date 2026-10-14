# CPFT — Charge-Point Forecasting Tool

The **Charge-Point Forecasting Tool (CPFT)** is a deep-learning forecasting engine developed by the
Centre for Energy Sustainability at the University of Salford within DRIVE2X. It lives in
`others/CPFT-main/` and is the reference model for EPIOT's planned machine-learning session
prediction (see {doc}`../concepts/session-data`).

```{figure} ../_static/figures/cpft-workflow.png
:class: chart
:alt: CPFT workflow from data preprocessing to LSTM forecasting
:width: 100%

The CPFT forecasting workflow (from the CPFT repository).
```

## What it forecasts

CPFT forecasts two operational signals of a charging point at **hourly** resolution, 24 hours ahead:

| Signal | Model | Output |
|---|---|---|
| **Availability** (in use / not in use) | LSTM classifier, `binary_crossentropy`, sigmoid output | Probability that the charger is occupied |
| **Charge load** (kWh delivered per hour) | LSTM regressor, `mean_squared_error`, non-negative output | Hourly energy; forced to 0 when availability is 0 |

## Pipeline

```{mermaid}
flowchart TB
    A[Session logs<br/>connectionTime · disconnectTime ·<br/>doneChargingTime · kWh] --> B[Preprocessing<br/>clean · hourly aggregation ·<br/>fill missing hours with 0]
    B --> C[Features<br/>availability label · connected hours ·<br/>day type · month · season]
    C --> D[Sliding windows<br/>seq_len = 50<br/>65 % train / 35 % test]
    D --> E1[LSTM availability]
    D --> E2[LSTM charge load]
    E1 & E2 --> F[Evaluation<br/>MSE · RMSE · MAE · R²<br/>by season and day type]
    E1 & E2 --> G[24 h forecasts]
```

Models are evaluated against naive baselines (last hour, same hour of the previous day) and broken
down by season and by weekday versus weekend.

## Contents of `others/CPFT-main/CPFT-tool`

| Path | Content |
|---|---|
| `CPFT_pipeline_Python.py`, `CPFT_DriVe2X_Jupyter.ipynb` | End-to-end pipeline as a script and as a notebook |
| `CPFT_VS_Code_Python/` | Packaged version with `requirements.txt` and a SalfordX notebook |
| `CPFT_VS_Code_Python/outputs/` | Trained models (`best_availability.keras`, `best_kwh.keras`) and metric workbooks |
| `Station_2_39_139_28.csv` | Example session data |
| `CPFT_User_Manual_and_EPIOT_Integration_Guide.pdf` | User manual and guide for integrating CPFT into EPIOT |

## Running CPFT

CPFT uses TensorFlow/Keras and has its own dependencies, separate from EPIOT's environment:

```bash
pip install numpy pandas matplotlib scikit-learn tensorflow
python others/CPFT-main/CPFT-tool/CPFT_pipeline_Python.py
```

## Relation to EPIOT

CPFT predicts availability and hourly energy per charging point; EPIOT's simulators need individual
sessions (arrival, departure, energy) at 10-minute resolution. EPIOT's **CPFT session source** runs
the bundled checkpoints on synthetic histories and turns occupied hours into approximate sessions.
Without live charging data, those forecasts depend only on the calendar and the history's profile,
so the trajectories are computed once per model version (`scripts/build_cpft_library.py`) and
sampled per request; the web application never loads TensorFlow. See
{doc}`../concepts/on-request-scenarios`.

CPFT is released under the Apache License 2.0. Contributors: Peyman Afzali-Gorouh and Vahid
Vahidinasab.
