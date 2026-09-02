To run the script fetch_env_data.sh every day at noon and log output to script.log, add the following line to your crontab (edit with `crontab -e`):

how to get system time?



```


0 12 * * * ./scripts/fetch_env_data.sh >> ./logs/fetch.log 2>&1