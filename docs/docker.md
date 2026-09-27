# Docker web app et jobs RPA

La partie web/API tourne en conteneur. Depuis le panel admin, elle peut aussi
déclencher des jobs RPA Docker séparés qui appellent `main_ingestion.py`.

## Lancement

```bash
docker compose --env-file .env -f docker-compose.web.yml up -d --build
python tools/sync_db_to_web_container.py --restart
```

La web app écoute sur `http://localhost:5000` par défaut.

## Versioning des images

Les images Docker sont taguées explicitement. Les valeurs par défaut sont :

```text
rpa-streaming-web:0.3.0
rpa-streaming-rpa:0.3.0
```

Tu peux surcharger les noms ou tags via `.env` :

```env
STREAMING_WEB_IMAGE=rpa-streaming-web
STREAMING_WEB_TAG=0.3.0
STREAMING_RPA_IMAGE=rpa-streaming-rpa
STREAMING_RPA_TAG=0.3.0
```

Pour reconstruire une version précise :

```bash
docker compose --env-file .env -f docker-compose.web.yml build
docker compose --env-file .env -f docker-compose.rpa.yml build
```

Pour un accès depuis un téléphone ou une autre machine du réseau local, utilise
l'adresse IP LAN du serveur local, par exemple :

```text
http://192.168.1.170:5000
```

Sous Windows/WSL, ouvre le port dans le pare-feu Windows avec PowerShell lancé
en administrateur :

```powershell
New-NetFirewallRule `
  -DisplayName "Streaming DB Web 5000" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 5000 `
  -Profile Private
```

Pour exposer un autre port :

```bash
WEB_PORT=8080 docker compose --env-file .env -f docker-compose.web.yml up -d --build
```

## Volumes

Le conteneur utilise un volume Docker nommé pour la base :

```text
streaming-web-data:/data
```

La variable interne `STREAMING_DB_PATH` vaut `/data/streaming.db`.

Sous certaines intégrations Docker Desktop + WSL, les bind mounts de fichiers
WSL sont exposés comme des dossiers vides. Le compose utilise donc un volume
Docker nommé. Après une ingestion, copie la base locale dans le conteneur :

```bash
python tools/sync_db_to_web_container.py --restart
```

Equivalent manuel :

```bash
docker cp streaming.db streaming-web:/data/streaming.db
docker restart streaming-web
```

## Jobs RPA Docker

Le conteneur web embarque le client Docker et monte le socket Docker hôte :

```text
/var/run/docker.sock:/var/run/docker.sock
```

Quand une ingestion est relancée depuis l'admin, le worker exécute :

```bash
docker compose -f /app/docker-compose.rpa.yml run --rm rpa-job \
  python main_ingestion.py --platform <plateforme> \
  --cdp-url http://host.docker.internal:9222 \
  --skip-crunchyroll-api
```

Le job RPA partage le volume `streaming-web-data`, donc il écrit directement
dans `/data/streaming.db`, la même base que celle lue par la web app.

Les identifiants ne sont pas copiés dans l'image. Ils sont lus depuis les
fichiers `config/*.local.json` montés en lecture seule dans les conteneurs. Le
`.env` ne contient que les chemins vers ces fichiers et quelques réglages
runtime.

Pour lancer un job RPA Docker à la main depuis WSL :

```bash
docker compose --env-file .env -f docker-compose.rpa.yml build rpa-job
docker compose --env-file .env -f docker-compose.rpa.yml run --rm rpa-job \
  python main_ingestion.py --platform netflix \
  --cdp-url http://host.docker.internal:9222 \
  --skip-crunchyroll-api
```

Sous Docker/WSL, le job RPA joint Chrome via `host.docker.internal:9222`.
Chrome doit donc être lancé avec `--remote-debugging-address=0.0.0.0`.
L'image RPA démarre aussi des proxys locaux internes pour Chrome CDP et Ollama,
afin que les URLs `127.0.0.1` renvoyées par Chrome restent utilisables depuis
le conteneur.

Chrome doit être lancé côté Windows/hôte avec CDP sur le port `9222`. Depuis
PowerShell :

```powershell
powershell.exe -NoProfile -Command "Start-Process chrome.exe '--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --remote-allow-origins=* --user-data-dir=$env:LOCALAPPDATA\Google\Chrome\User Data'"
```

## Sécurité

- Le fichier `.env` n'est pas copié dans les images.
- Les fichiers `config/*.local.json` sont montés en lecture seule et ignorés par
  git.
- `ADMIN_TOKEN` peut être injecté via l'environnement ou via ton shell avant `docker compose`.
- Les dossiers `artifacts/`, `backups/`, `logs/` et les bases locales ne sont pas copiés dans l'image.
- La web app ajoute des en-têtes de durcissement HTTP compatibles avec une
  démarche ISO 27001 : interdiction de framing, limitation des permissions
  navigateur et réduction du risque MIME sniffing.
- Le montage `/var/run/docker.sock` donne au conteneur web le droit de lancer
  des conteneurs sur l'hôte. Cette configuration doit rester réservée à ton
  serveur local ou à une machine de confiance.

## Planification RPA

Un cron utilisateur peut lancer automatiquement le RPA sur le serveur local :

```bash
python tools/install_rpa_cron.py
```

La crontab installée depuis `ops/cron/rpa_streaming.crontab` exécute :

- un full tous les jours à `04:00` ;
- un différentiel toutes les 4 heures sur les autres créneaux : `00:00`,
  `08:00`, `12:00`, `16:00`, `20:00`.

## API mobile

Le conteneur expose aussi les endpoints utilisés par l'application Android :

```text
GET /api/mobile/bootstrap
GET /api/mobile/titles?type=series
GET /api/mobile/titles?type=movie
GET /api/mobile/titles/<id>
GET /api/mobile/calendar?month=YYYY-MM
```
