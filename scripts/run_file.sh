
source ~/miniconda3/bin/activate
conda activate epiot
cd /home/sorfanoudakis/epiot
export SPATIALITE_LIBRARY_PATH=mod_spatialite.so
source ~/.bashrc
/home/sorfanoudakis/miniconda3/envs/epiot/bin/gunicorn --limit-request-line 18190 -w 4 --threads 4 --timeout 300 -b 127.0.0.1:5000 app:app