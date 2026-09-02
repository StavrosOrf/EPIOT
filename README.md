## EPIOT - Drive2X WP5
This is the development repository of the Drive2X working package 5. The purpose of the tool to be developed is 
the following:

- provide short-term load forecasting for charge point operators and grid operators

The tool is supposed to be easily accessible and to provide a range of interfaces for researchers and developpers.


## Running Instructions

Initialize conda environment and install the dependencies.
```
#create a conda environment
conda create -n epiot python=3.9
conda activate epiot
```

## Setting up the database
#To set up the database for the first time you need to install the requirements and make #spatialite available in your system. Conda is the fastest way to do this on windows. 

```
conda install libspatialite -c conda-forge
```

##### Install the dependencies
```
pip install -r requirements.txt
```

##### If having trouble with the installation of libspatialite, try the following:

https://docs.djangoproject.com/en/5.1/ref/contrib/gis/install/spatialite/

###### For windows:
- Download the latest version of SpatiaLite from https://www.gaia-gis.it/gaia-sins/
- Unzip the file and copy the contents of the zip file to the folder where you want to install SpatiaLite. (I copied the contents to the source folder of my conda environment)

###### For Ubuntu:
```
sudo apt-get install libsqlite3-mod-spatialite
export SPATIALITE_LIBRARY_PATH=mod_spatialite.so
source ~/.bashrc
```


##### Once this is achieved you can first run two times:
```
flask db upgrade
```





##### Make sure you have the database files in the **./data** folder
- chargers_data_ams.json
- liander_elektriciteitsnetten.gpkg
- wijkenbuurten_2022_v2_amsterdam.gpkg

##### The first time it is run initiazes the database
```

python database_init.py
```

##### To run the Flask app
```
python app.py
```



The current development team consists of:

- Babak Ravanbach (DLR, product owner)
- Stavros Orfanoudakis (TU Delft, lead developper)
- Arellano Ruiz, Eugenio Salvador (DLR, developper)

Past developpers:
- Elif Turhan (DLR, developper)
- Niklas Wulff (DLR, developper)