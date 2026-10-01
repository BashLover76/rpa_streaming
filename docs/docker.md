# Docker web app et jobs RPA

La partie web/API tourne en conteneur. Depuis le panel admin, elle peut aussi
déclencher des jobs RPA Docker séparés qui appellent `main_ingestion.py`.

## Lancement

```bash
python tools/sync_config_to_docker_volume.py
docker compose --env-file .env -f docker-compose.web.yml up -d --build
python tools/sync_db_to_web_container.py --restart
```

La web app écoute sur `http://localhost:5000` par défaut.

## Versioning des images

Les images Docker sont taguées explicitement. Les valeurs par défaut sont :

```text
rpa-streaming-web:0.8.1
rpa-streaming-rpa:0.8.1
```

Tu peux surcharger les noms ou tags via `.env` :

```env
STREAMING_WEB_IMAGE=rpa-streaming-web
STREAMING_WEB_TAG=0.8.1
STREAMING_RPA_IMAGE=rpa-streaming-rpa
STREAMING_RPA_TAG=0.8.1
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
Les fichiers de configuration locaux sont copiés dans un volume Docker nommé :

```text
streaming-web-config:/app/config
```

Ils restent exclus du contexte de build Docker via `.dockerignore`; ils ne sont
donc pas copiés dans les images. Après une modification de `config/*.local.json`,
resynchronise ce volume :

```bash
python tools/sync_config_to_docker_volume.py
docker restart streaming-web
```

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

Quand une ingestion est relancée depuis l'admin, le worker exécute le compose
d'ingestion embarqué dans l'image web :

```bash
docker compose -f /app/docker-compose.ingestion.yml run --rm rpa-job \
  python main_ingestion.py --platform <plateforme> \
  --cdp-url http://127.0.0.1:9222 \
  --skip-crunchyroll-api
```

Ce compose lance aussi un service `rpa-chrome` dédié à l'ingestion. Chrome
utilise un profil éphémère dans le conteneur et expose CDP dans le même
namespace réseau que `rpa-job`; `127.0.0.1:9222` pointe donc vers le Chrome
conteneurisé, pas vers le navigateur du poste client.

Le job RPA partage le volume `streaming-web-data`, donc il écrit directement
dans `/data/streaming.db`, la même base que celle lue par la web app.

Les identifiants ne sont pas copiés dans l'image. Ils sont lus depuis les
fichiers `config/*.local.json` montés en lecture seule dans les conteneurs. Le
`.env` ne contient que les chemins vers ces fichiers et quelques réglages
runtime.

Pour lancer un job RPA Docker à la main depuis WSL :

```bash
docker compose --env-file .env -f docker-compose.ingestion.yml build rpa-job
docker compose --env-file .env -f docker-compose.ingestion.yml run --rm rpa-job \
  python main_ingestion.py --platform netflix \
  --cdp-url http://127.0.0.1:9222 \
  --skip-crunchyroll-api
```

Le Chrome utilisé par cette commande est le service `rpa-chrome` du compose
d'ingestion. Il n'est donc plus nécessaire que le navigateur du poste client ou
du poste Windows appelant soit lancé avec CDP pour les relances Docker.

Le profil Chrome Docker est volontairement éphémère. Si une plateforme reste
sur un écran de connexion, MFA ou sélection de profil, le RPA refuse désormais
les sélecteurs proposés par self-healing lorsqu'ils ciblent le formulaire de
login. Le log admin affiche alors une erreur explicite : vérifie les identifiants
et les profils dans `config/streaming_platform_config.local.json`, puis relance
la plateforme.

Pour les plateformes qui refusent la connexion headless, comme Netflix selon
les comptes, utilise le Chrome Windows déjà authentifié avec le compose RPA
historique. Le conteneur ouvre un proxy local `127.0.0.1:9222` vers
`host.docker.internal:9222`, ce qui évite le problème WebSocket CDP retourné en
`127.0.0.1` par Chrome :

```bash
docker compose --env-file .env -f docker-compose.rpa.yml run --rm rpa-job \
  python main_ingestion.py \
  --platform netflix \
  --cdp-url http://127.0.0.1:9222 \
  --rpa-mode differential \
  --skip-crunchyroll-api \
  --no-auto-start-chrome
```

### Rejouer une ingestion Docker

Avant une relance, synchronise les fichiers de configuration locaux dans le
volume Docker partagé :

```bash
python tools/sync_config_to_docker_volume.py
```

### Partager la session Chrome locale avec Chrome Docker

Le dossier de profil Chrome Windows ne doit pas être monté directement dans le
conteneur : les cookies y sont chiffrés par Windows et le profil peut être
verrouillé. Pour initialiser les connexions localement puis les réutiliser dans
le Chrome Docker, exporte plutôt le `storage_state` Playwright depuis Chrome CDP.

1. Lance Chrome Windows avec CDP et connecte-toi aux plateformes.

```powershell
powershell.exe -NoProfile -Command "Start-Process chrome.exe '--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --remote-allow-origins=* --user-data-dir=$env:LOCALAPPDATA\Google\Chrome\User Data'"
```

2. Depuis WSL, exporte les cookies/localStorage du Chrome local :

```bash
python -m tools.export_chrome_storage_state \
  --cdp-url http://127.0.0.1:9222 \
  --output .continue/browser-storage-state.json
```

3. Copie cet état dans le volume Docker RPA :

```bash
python -m tools.sync_storage_state_to_docker_volume \
  --source .continue/browser-storage-state.json
```

4. Lance l'ingestion Docker. Le job importe automatiquement
`/app/.continue/browser-storage-state.json` si le fichier existe :

```bash
docker compose --env-file .env -f docker-compose.ingestion.yml run --rm rpa-job \
  python main_ingestion.py \
  --platform netflix \
  --cdp-url http://127.0.0.1:9222 \
  --rpa-mode differential \
  --skip-crunchyroll-api
```

Ce fichier contient des cookies de session. Ne le copie pas hors de la machine,
ne le commit jamais et régénère-le si une plateforme invalide la session.

Relancer toutes les plateformes en différentiel :

```bash
docker compose --env-file .env -f docker-compose.ingestion.yml run --rm rpa-job \
  python main_ingestion.py \
  --cdp-url http://127.0.0.1:9222 \
  --rpa-mode differential \
  --skip-crunchyroll-api
```

Relancer une seule plateforme en différentiel :

```bash
docker compose --env-file .env -f docker-compose.ingestion.yml run --rm rpa-job \
  python main_ingestion.py \
  --platform crunchyroll \
  --cdp-url http://127.0.0.1:9222 \
  --rpa-mode differential \
  --skip-crunchyroll-api
```

Relancer toutes les plateformes en full :

```bash
docker compose --env-file .env -f docker-compose.ingestion.yml run --rm rpa-job \
  python main_ingestion.py \
  --cdp-url http://127.0.0.1:9222 \
  --rpa-mode full \
  --skip-crunchyroll-api
```

Suivre les logs du job lancé depuis l'admin web :

```bash
docker compose --env-file .env -f docker-compose.web.yml exec -T streaming-web \
  tail -f /app/logs/admin-rpa-<plateforme>-<timestamp>.log
```

Après une ingestion lancée hors conteneur web, resynchronise la base dans le
volume web si nécessaire :

```bash
python tools/sync_db_to_web_container.py --restart
```

### Ancien mode Chrome hôte

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
