# Airflow Weather Data Pipeline


Projet de Data Engineering réalisé avec Apache Airflow, Docker, PostgreSQL, pgAdmin, Metabase et l’API OpenWeatherMap


## Objectif :


Construire un pipeline ETL automatisé qui récupère des données météorologiques depuis l’API OpenWeatherMap, les stocke dans PostgreSQL et les visualise dans Metabase.


## Architecture :



```text
OpenWeatherMap API
        |
        v
Apache Airflow
   weather_etl DAG
        |
        v
PostgreSQL
   weatherdb
      /   \
     /     \
pgAdmin   Metabase
            |
            v
     Weather Dashboard
```

## Technologies utilisées

* Apache Airflow 2.9.1
* Docker / Docker Compose
* PostgreSQL 13
* pgAdmin 4
* Metabase
* Python
* OpenWeatherMap API
* psycopg2
* requests

## Fonctionnement du pipeline

Le DAG Airflow `weather_etl` est planifié avec :

```text
@daily
```

Il récupère les données météo de plusieurs villes britanniques :

* London
* Birmingham
* Manchester
* Glasgow
* Liverpool
* Leeds
* Sheffield
* Bristol
* Newcastle
* Nottingham

Pour chaque ville, le pipeline récupère :

* la température
* l’humidité
* la description météo
* la date

Les données sont ensuite insérées dans la table PostgreSQL `weather`.

## Fiabilité de la collecte et résultat par ville

Chaque ville est traitée de façon indépendante : l'échec d'une ville ne bloque
jamais les autres et ne laisse aucune ligne partielle ou `NULL` en base
(la transaction de la ville en échec est annulée par un `ROLLBACK`).

À la fin de chaque exécution, le DAG produit un résultat vérifiable pour
chacune des dix villes, contenant au minimum :

```text
city            nom de la ville
status          success | failed | skipped
reason          cause en échec/skip (None en succès)
rows_inserted   nombre de lignes réellement ajoutées (0 ou 1)
date            date de la collecte
```

Les raisons d'échec sont distinguées en trois catégories explicites :

```text
http_error        réponse HTTP non 2xx (ou erreur réseau/timeout)
invalid_response  HTTP 2xx mais champ requis absent
                  (main.temp, main.humidity ou weather[0].description)
db_error          exception PostgreSQL (lecture ou écriture)
```

Cas de doublon : si une ligne existe déjà pour le couple `(ville, date)`,
la ville est marquée `skipped` / `duplicate_date` et aucune ligne
supplémentaire n'est insérée. Deux villes différentes le même jour
n'interfèrent pas entre elles.

Ce rapport est consultable par l'exploitation de deux façons :

* dans le **log de la tâche** Airflow, sous forme de tableau récapitulatif
  suivi d'une ligne de synthèse (`success=… failed=… skipped=… rows inserted=…`) ;
* via **XCom** : clés `city_results` (liste détaillée par ville) et
  `run_summary` (agrégats de l'exécution).

La tâche est marquée `failed` dans Airflow si au moins une ville échoue,
mais uniquement après journalisation et archivage XCom du rapport complet ;
les villes ayant réussi restent bien enregistrées. Une ré-exécution le même
jour est idempotente grâce à la détection de doublon.

### Tests locaux

Le cœur de la logique vit dans `dags/weather_pipeline.py`, qui ne dépend pas
d'Airflow et peut donc être testé localement.

Tests unitaires (réponses HTTP et base simulées, aucun réseau) :

```bash
python -I -m unittest discover -s tests -v
```

Test d'intégration contre un vrai PostgreSQL (le HTTP reste simulé ;
la couche SQL/transaction/doublon est réelle) :

```bash
docker run -d --name wtest-pg -e POSTGRES_USER=tuser \
  -e POSTGRES_PASSWORD=tpass -e POSTGRES_DB=weatherdb -p 55433:5432 postgres:13
POSTGRES_HOST=localhost POSTGRES_PORT=55433 POSTGRES_DB=weatherdb \
  POSTGRES_USER=tuser POSTGRES_PASSWORD=tpass \
  python -I tests_integration/integration_postgres.py
docker rm -f wtest-pg
```

Ces bouchons (`mock`) servent uniquement à valider la logique ; en
production la tâche appelle bien l'API OpenWeatherMap et PostgreSQL avec les
variables d'environnement existantes (`OPENWEATHER_API_KEY`, `POSTGRES_*`).

## Structure des données

La table `weather` contient les champs suivants :

```text
id
city
temperature
humidity
weather_description
date
```

## Ports utilisés

Pour éviter les conflits avec d’autres environnements Docker locaux, certains ports ont été modifiés.

```text
Airflow      : http://localhost:8083
pgAdmin      : http://localhost:5050
Metabase     : http://localhost:3000
PostgreSQL   : localhost:5433
```

À l’intérieur du réseau Docker, PostgreSQL reste accessible via :

```text
postgres:5432
```

## Installation

Cloner le projet :

```bash
git clone https://github.com/datasifaw/airflow-weather-pipeline.git
cd airflow-weather-pipeline
```

Créer le fichier `.env` :

```bash
cp .env.example .env
```

Puis renseigner les variables nécessaires :

```env
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=weatherdb

PGADMIN_DEFAULT_EMAIL=
PGADMIN_DEFAULT_PASSWORD=

AIRFLOW_USER=
AIRFLOW_PASSWORD=

OPENWEATHER_API_KEY=
```

Le fichier `.env` est ignoré par Git afin de protéger les informations sensibles.

## Lancement

Démarrer l’environnement :

```bash
docker compose up -d
```

Vérifier les conteneurs :

```bash
docker compose ps
```

## Apache Airflow

Interface :

```text
http://localhost:8083
```

DAG principal :

```text
weather_etl
```

Le pipeline est exécuté quotidiennement avec Airflow.

## PostgreSQL

La base utilisée est :

```text
weatherdb
```

Exemple de vérification :

```bash
docker compose exec postgres psql -U airflow_weather -d weatherdb -c "SELECT COUNT(*) FROM weather;"
```

Afficher quelques données :

```bash
docker compose exec postgres psql -U airflow_weather -d weatherdb -c "SELECT * FROM weather LIMIT 10;"
```

## pgAdmin

Interface :

```text
http://localhost:5050
```

Connexion PostgreSQL depuis pgAdmin :

```text
Host     : postgres
Port     : 5432
Database : weatherdb
```

## Metabase

Interface :

```text
http://localhost:3000
```

Metabase est connecté directement à PostgreSQL via le réseau Docker :

```text
Host     : postgres
Port     : 5432
Database : weatherdb
```

## Dashboard

Le dashboard final contient plusieurs visualisations :

* Température moyenne par ville
* Humidité moyenne par ville
* Évolution quotidienne de la température
* Répartition des conditions météo

## Pipeline complet

```text
OpenWeatherMap
      |
      | API REST
      v
Apache Airflow
      |
      | PythonOperator
      v
PostgreSQL
      |
      +------> pgAdmin
      |
      +------> Metabase
                   |
                   v
          Weather Dashboard
```

## Sécurité

Les secrets ne sont pas stockés dans Git.

Le fichier suivant est ignoré :

```text
.env
```

Il contient notamment :

* clé API OpenWeatherMap
* mot de passe PostgreSQL
* identifiants pgAdmin
* identifiants Airflow

## Auteur

https://github.com/datasifaw
