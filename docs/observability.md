# Logs et observabilité

### Logs

Chaque script configure un log console et un log fichier. Les fichiers tournent
chaque jour a minuit et gardent 30 jours d'archives.

- `logs/ingestion.log` : orchestration `main_ingestion.py`.
- `logs/enrichment.log` : enrichissements IMDb/BetaSeries.
- `logs/sync.log` : synchronisation de l'historique local vers BetaSeries.
- `logs/diagnostics.log` : outils de diagnostic.
- `logs/rpa-delete.log` : suppression RPA d'un historique plateforme.
- `logs/platforms/<plateforme>.log` : logs dedies a une plateforme, par exemple
  `logs/platforms/netflix.log` ou `logs/platforms/prime_video.log`.

Quand l'ingestion traite toutes les plateformes, chaque bloc RPA ajoute aussi
ses lignes dans le fichier de la plateforme concernee.

### Grafana / Loki

Le dossier `observability/` fournit un connecteur local Grafana via Loki et
Promtail. Promtail lit directement les fichiers `logs/*.log` et
`logs/platforms/*.log`, puis ajoute les labels `script`, `platform`, `level`,
`logger` et `source`.

Lancement :

```bash
cd observability
docker compose up -d
```

Acces :

- Grafana : `http://localhost:3000`
- Identifiant par defaut : `admin`
- Mot de passe par defaut : `admin`
- Datasource provisionnee : `Loki`
- Dashboard provisionne : `RPA Streaming Logs`

Requetes Loki utiles :

```logql
{job="rpa_streaming"}
{job="rpa_streaming", source="platform", platform="netflix"}
{job="rpa_streaming", source="script", script="ingestion"}
{job="rpa_streaming"} | level =~ "ERROR|WARNING"
```

Arret :

```bash
cd observability
docker compose down
```

Documentation des services : [details series BetaSeries](https://developers.betaseries.com/docs/api/get-shows-display/),
[details films BetaSeries](https://developers.betaseries.com/docs/api/get-movies-movie/),
[API officielle IMDb](https://data.imdb.com/documentation/api-documentation/sample-queries/search/).
