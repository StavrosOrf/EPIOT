# /path/to/run_script.sh
#!/usr/bin/env bash

source ~/miniconda3/bin/activate
conda activate epiot
cd /home/sorfanoudakis/epiot
export SPATIALITE_LIBRARY_PATH=mod_spatialite.so
source ~/.bashrc
/home/sorfanoudakis/miniconda3/envs/epiot/bin/python update_database.py
