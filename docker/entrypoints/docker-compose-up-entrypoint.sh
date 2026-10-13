#!/bin/env bash

bash ./Entrypoints/wait-for-it.sh yse_db:3306 --timeout=0 &&
echo "**** LET'S GO GAMERS! ****" &&
# Schema + seed data are provisioned by docker/db_init/*.sql on a fresh DB
# volume; YSE_django_migrations_insert.sql records which migrations that schema
# represents. Model changes go through YSE_App/migrations/. We intentionally do
# NOT run `manage.py migrate` on start: a human migrates shared/live DBs
# (see docker/README.md, "Migrations").
# python3 manage.py migrate --noinput &&
# Multiple workers/threads so one slow view can't freeze the whole app, and a
# finite --timeout so a stuck request is recycled instead of wedging forever
# (a single sync worker with --timeout=0 takes the entire server down on the
# first blocking request, e.g. an astropy network call).
gunicorn YSE_PZ.wsgi:application --bind 0.0.0.0:8000 \
    --workers 3 --threads 4 --timeout 120 --graceful-timeout 30
#&& bash ./Entrypoints/wait-for-it.sh yse_nginx:80 --timeout=0

#python3 manage.py collectstatic --noinput &&

#echo "***** SLEEP FOR 30 seconds... *****"; sleep 30;
#python3 manage.py runserver 0.0.0.0:8000
#python manage.py makemigrations &&
#python manage.py migrate &&
#python manage.py loaddata setup_survey_data.yaml &&
#python manage.py loaddata setup_filter_data.yaml &&
#python manage.py loaddata setup_catalog_data.yaml &&
#python manage.py loaddata setup_test_transient.yaml &&
#python manage.py loaddata setup_tasks.yaml &&
#python manage.py loaddata setup_status.yaml &&
#python manage.py loaddata setup_test_task_register.yaml &&
#gunicorn app.wsgi:application --bind 0.0.0.0:8000