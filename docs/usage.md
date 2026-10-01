# Utilisation

### Lancement multi-OS

Chrome doit etre accessible via son port CDP et connecte aux profils
souhaites. Sous WSL, Chrome est lance cote Windows ; sous Linux natif, Chrome ou
Chromium est lance localement ; sous Windows natif, Chrome est lance via
PowerShell. Les identifiants BetaSeries restent dans `config/betaseries.local.json`. Ollama reste utile
pour les cartes non structurees et la reparation de selecteurs ; les cartes
lisibles sont extraites directement du DOM.

```bash
# Depuis WSL : laisser le script relancer Chrome Windows avec CDP + extension
python main_ingestion.py --cdp-url http://127.0.0.1:9222 --force-restart-chrome

# Depuis Linux natif si tu veux lancer Chrome manuellement
google-chrome --remote-debugging-port=9222 --remote-allow-origins='*' --user-data-dir="$HOME/.config/rpa-streaming-chrome" >/dev/null 2>&1 &

# Verification rapide du port CDP
curl http://127.0.0.1:9222/json/version

# Toutes les plateformes configurees, tous les types de contenus
python main_ingestion.py --cdp-url http://127.0.0.1:9222 --cdp-timeout-ms 30000

# Desactiver le lancement automatique de Chrome si le port CDP ne repond pas
python main_ingestion.py --cdp-url http://127.0.0.1:9222 --no-auto-start-chrome

# Si Chrome est deja ouvert sans CDP/extension, le fermer et le relancer automatiquement
python main_ingestion.py --cdp-url http://127.0.0.1:9222 --force-restart-chrome

# Mode full : parcours complet selon les limites de chaque plateforme
python main_ingestion.py --cdp-url http://127.0.0.1:9222 --rpa-mode full

# Mode differentiel : collecte uniquement les cartes nouvelles et s'arrete
# apres 20 cartes deja connues consecutives
python main_ingestion.py --cdp-url http://127.0.0.1:9222 --rpa-mode differential

# Premiere reprise du catalogue existant : reidentification et dedoublonnage
python main_ingestion.py --cdp-url http://127.0.0.1:9222 --cdp-timeout-ms 30000 --reconcile-existing --retry-unresolved

# Reprendre uniquement les donnees locales, sans ouvrir les plateformes
python main_ingestion.py --skip-rpa --skip-crunchyroll-api --reconcile-existing --retry-unresolved

# Collecter maintenant, identifier plus tard
python main_ingestion.py --cdp-url http://127.0.0.1:9222 --cdp-timeout-ms 30000 --skip-resolution --skip-betaseries

# Diagnostic en lecture seule d'un titre, sans modifier sa fiche
python -m tools.enrich_imdb_metadata --inspect-title "Alien: Romulus" --platform disney_plus

# Rapport des titres ambigus et des erreurs (aucun appel reseau)
python -m tools.enrich_imdb_metadata --report
```

`--platform prime_video` limite le traitement a une plateforme. Les anciennes
fiches jamais verifiees sont reprises automatiquement, avec sauvegarde SQLite
coherente dans `backups/`. `--reconcile-existing` permet de toutes les reverifier.
`--retry-unresolved` reprend les observations ambigues ou en erreur.
Les sauvegardes contiennent l'historique personnel : les garder localement.
Si Chrome ne repond pas encore sur `/json/version`, l'ingestion tente de le
lancer automatiquement avec la commande CDP documentee ci-dessus.
Si Chrome repond sur `/json/version` mais que Playwright reste bloque sur le
WebSocket CDP, l'ingestion RPA est ignoree apres `--cdp-timeout-ms` et la phase
de reconciliation/enrichissement continue sur les donnees deja collectees.
Un verrou fichier `.continue/ingestion.lock` empeche deux ingestions concurrentes.
Il peut etre desactive ponctuellement avec `--no-lock`.

### Full et differentiel

Le RPA accepte deux modes :

- `--rpa-mode full` : comportement complet, chaque plateforme defile jusqu'a la
  fin visible ou jusqu'a `max_scroll_steps`.
- `--rpa-mode differential` : collecte uniquement les cartes non encore connues,
  puis s'arrete apres `--rpa-differential-known-threshold` cartes deja presentes
  dans `raw_history_cards` consecutives. Le seuil par defaut est `20`.

Planning conseille :

- full quotidien a 04:00.
- differentiel a 00:00, 08:00, 12:00, 16:00 et 20:00. Le full de 04:00 remplace
  le differentiel de ce creneau. Le differentiel planifie ne passe pas
  `--retry-unresolved` pour eviter de retraiter les anciens cas ambigus toutes
  les 4 heures ; le full quotidien s'en charge.

Installation systemd utilisateur :

```bash
python -m tools.install_ingestion_timers
systemctl --user list-timers 'rpa-streaming-*'
```

Si systemd n'est pas actif dans WSL, utiliser cron :

```bash
crontab ops/cron/rpa_streaming.crontab
crontab -l
```

### Identification et qualite des donnees

- Les dates de lecture sont celles exposees par la plateforme. Une date absente
  reste inconnue ; la date d'import ne devient pas une date de visionnage.
- Les dates et libelles Netflix parasites, suffixes de saison et repetitions
  de titres sont retires de la recherche sans modifier les observations brutes.
- IMDb fournit le type et l'identifiant. Les suggestions web IMDb sont un
  service non documente, distinct de l'API commerciale IMDb, et peuvent changer.
  Elles fournissent principalement titre, type, annee et affiche : notes,
  synopsis et langues ne sont pas garantis par ce service.
- BetaSeries est interroge pour les films ET les series. Le titre localise,
  l'identifiant IMDb commun, l'annee disponible et les plateformes SVOD servent
  a departager les candidats. La plateforme est un indice : les catalogues
  changent et un titre peut etre disponible sur plusieurs services.
- Une correspondance avec une autre annee ou plusieurs homonymes equivalents
  reste `unresolved`. Un premier resultat de recherche n'est jamais une preuve.
- Les details BetaSeries (synopsis, affiche, fond, genres, saisons, episodes,
  statut, annee, duree selon le type) enrichissent la fiche associee au meme IMDb.
- Les films utilisent `betaseries_movie_id`, les series `betaseries_id` : leurs
  identifiants numeriques peuvent se recouper sans designer la meme oeuvre.
- Seules deux fiches ayant le meme `resolved_imdb_id` verifie sont fusionnees
  par ce flux. Les alias, sources, liens, calendriers et lectures sont rattaches
  a l'identifiant local conserve. Les dates et plateformes distinctes restent
  des lectures distinctes. Le retraitement du meme evenement est idempotent.
- Ce flux enrichit la base locale. Il ne marque pas automatiquement des contenus
  comme vus sur le compte BetaSeries ; les outils de restitution d'historique
  restent des commandes distinctes.

### Etendue de la collecte

Netflix et Prime Video parcourent le chargement supplementaire et le defilement.
Prime Video garde sa limite de 300 et Crunchyroll de 500. Atteindre la limite
produit un avertissement de collecte partielle. Les cartes deja vues sont
conservees pendant le parcours pour les listes virtualisees.

Disney+ et CANAL+ exposent ici leurs rails de reprise : le collecteur recupere
toutes les cartes accessibles, mais ces rails ne contiennent pas l'historique
complet des lectures terminees. Les recommandations ne sont pas importees.
Apple TV+, Max, Paramount+ et OCS suivent la session CANAL+ configuree.
Un historique exhaustif de ces comptes exige une source/export d'historique
supplementaire de la plateforme. Le journal indique explicitement cette limite.

Les tests du nouveau flux sont disponibles via :

```bash
python -m unittest discover -s tests
```

## Execution

### Connexion a Chrome Windows via CDP

Le mode CDP permet au RPA de reutiliser l'instance Chrome Windows deja
connectee aux plateformes. Playwright ouvre des onglets dans le contexte Chrome
existant et ne gere pas les cookies lui-meme.

Ferme d'abord toutes les fenetres Chrome Windows, puis lance PowerShell :

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
$profileDir = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data'
Start-Process $chrome -ArgumentList @(
  '--remote-debugging-port=9222',
  '--remote-debugging-address=0.0.0.0',
  '--remote-allow-origins=*',
  "--user-data-dir=$profileDir"
)
```

Si Chrome est installe dans le dossier utilisateur :

```powershell
$chrome = "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
$profileDir = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data'
Start-Process $chrome -ArgumentList @(
  '--remote-debugging-port=9222',
  '--remote-debugging-address=0.0.0.0',
  '--remote-allow-origins=*',
  "--user-data-dir=$profileDir"
)
```

Reconnecte-toi ensuite aux plateformes dans cette fenetre Chrome. Depuis WSL,
verifie le port :

```bash
curl http://127.0.0.1:9222/json/version
```

Depuis un conteneur Docker RPA, le port doit aussi être visible via
`host.docker.internal`. Si ce test échoue, Chrome n'écoute probablement pas sur
`0.0.0.0` :

```bash
docker compose --env-file .env -f docker-compose.rpa.yml run --rm rpa-job \
  curl -fsS http://host.docker.internal:9222/json/version
```

Lance ensuite le RPA en mode CDP :

```bash
cd /path/to/rpa_streaming
source .venv/bin/activate
python main_ingestion.py \
  --cdp-url http://127.0.0.1:9222 \
  --skip-betaseries \
  --skip-crunchyroll-api
```

Pour lancer BetaSeries, Crunchyroll et le RPA dans le meme flux :

```bash
python main_ingestion.py \
  --cdp-url http://127.0.0.1:9222 \
  --betaseries-days-before 30 \
  --betaseries-days-after 365
```

Le reglage peut aussi etre place dans `.env` :

```dotenv
RPA_CDP_URL=http://127.0.0.1:9222
```

Le self-healing et l'extraction de donnees utilisent Ollama. `llava:latest`
peut boucler sur les captures complexes et ne pas produire le JSON attendu.
Le modele configure est `gemma3:4b`. Il est deja installe sur cette machine et
a produit un JSON valide sur un test d'extraction des six lignes Prime Video.
`qwen2.5vl:7b` reste configurable, mais la lecture de la capture a produit des
resultats inexacts dans les tests locaux :

```bash
ollama serve
ollama pull gemma3:4b
curl http://127.0.0.1:11434/api/tags
```

Dans `config/ollama.local.json`, configure :

```json
{
  "model": "gemma3:4b",
  "base_url": "http://localhost:11434",
  "num_ctx": 32768,
  "num_predict": 4096,
  "timeout": 300
}
```

`NUM_CTX` borne le contexte d'entree; `NUM_PREDICT` borne la sortie. Le
self-healing utilise 768 tokens de sortie et l'extraction procede par lots de
dix lignes. Le client agrege les messages NDJSON du serveur et conserve un
schema JSON explicite lors des nouvelles tentatives. Les balises script/style
sont retirees du DOM transmis. Les lignes DOM sont prioritaires lorsqu'elles
existent; la vision est utilisee quand il n'y a pas de lignes textuelles.

Diagnostic sans modification de la base ni synchronisation BetaSeries :

```bash
python -m tools.ollama_diagnostics
python -m tools.ollama_diagnostics --image artifacts/rpa/prime_video/CAPTURE.png
```

Le second test affiche un titre lu dans l'image; compare-le avec la capture.
Une reponse JSON valide ne garantit pas une lecture visuelle exacte. Les logs
indiquent le modele reel, les budgets, les compteurs de tokens et la raison
d'arret. Si la sortie est tronquee, reduis les lots ou augmente le budget de
sortie. Augmenter seulement le contexte ne corrige pas une boucle de generation.

Le test `/api/tags` doit retourner un JSON contenant `gemma3:4b`. Si Ollama
tourne sous Windows et non dans WSL, remplace `base_url` dans
`config/ollama.local.json` par l'adresse de l'hote Windows accessible depuis
WSL, par exemple `http://$(ip route | awk '/default/ {print $3}'):11434`, puis
relance le test.
Une erreur HTTP 404 sur `/api/chat` indique que le port cible n'est pas le
serveur Ollama attendu.

`--cdp-url` est prioritaire sur `RPA_CDP_URL` dans `.env`. Sans URL CDP, Playwright conserve son
comportement historique et lance un Chromium persistant avec
`RPA_USER_DATA_DIR`.

Une extension ne peut pas etre injectee dynamiquement dans un contexte Chrome
deja ouvert via CDP. Si CDP ne repond pas, le script peut fermer Chrome et le
relancer avec CDP + extension via `--force-restart-chrome`. Sans ce flag, il
propose l'action en interactif quand l'entree standard le permet. Si tu lances
Chrome manuellement, ajoute `--load-extension=browser_extension/streaming-rpa-helper`
pour les plateformes qui declarent `requires_browser_extension=true`.

Synchronisation complète:

```bash
python main_ingestion.py
```

Uniquement BetaSeries:

```bash
python main_ingestion.py --skip-rpa
```

Avec une fenêtre de calendrier plus large:

```bash
python main_ingestion.py --skip-rpa --betaseries-days-before 365 --betaseries-days-after 365
```

Uniquement RPA:

```bash
python main_ingestion.py --skip-betaseries
```

Mode headless après stabilisation des connexions:

```bash
python main_ingestion.py --skip-betaseries --headless
```

## Synchroniser l'historique vers BetaSeries

Les plateformes exposent des niveaux de précision différents:

- Crunchyroll donne souvent un vrai couple série/saison/épisode via l'historique visible.
- Netflix et Prime Video exposent l'historique web, mais les détails épisode peuvent demander une extraction plus fine page par page.
- Disney+ expose surtout l'état "Continuer à regarder"; ce n'est pas toujours un historique complet.
- CANAL+ donne des rails récents et des états de reprise, selon les pages et le profil.

Le projet synchronise donc uniquement les lignes fiables: il faut au minimum `saison` et `episode`, puis l'outil recherche la série dans BetaSeries, récupère ses épisodes et vérifie le couple saison/épisode avant tout envoi.

Dry-run, sans écriture sur le compte BetaSeries:

```bash
python -m tools.sync_history_to_betaseries --limit 50
```

Limiter à une plateforme:

```bash
python -m tools.sync_history_to_betaseries --platform crunchyroll --limit 100
```

Envoyer réellement les épisodes reconnus à BetaSeries:

```bash
python -m tools.sync_history_to_betaseries --platform crunchyroll --apply
```

Marquer aussi les épisodes précédents comme vus côté BetaSeries:

```bash
python -m tools.sync_history_to_betaseries --platform crunchyroll --apply --bulk
```

L'API BetaSeries utilisée est `POST /episodes/watched`. Par sécurité, `--apply` n'est jamais implicite.

Enrichir les séries locales avec les posters, synopsis et calendriers BetaSeries:

```bash
python -m tools.enrich_betaseries_metadata --limit 140 --calendar-days-after 365
```

Enrichir en fallback IMDb les titres qui restent pauvres ou absents de BetaSeries:

```bash
python -m tools.enrich_imdb_metadata --limit 200
```

Limiter le fallback IMDb à une plateforme:

```bash
python -m tools.enrich_imdb_metadata --platform disney_plus --limit 80
```

Nettoyer les doublons d'historique causés par les lignes sans saison/épisode:

```bash
python tools/dedupe_history.py
```

Contrôler les compteurs d'enrichissement:

```bash
python tools/enriched_stats.py
```

## Premier lancement RPA

Le flux recommandé est maintenant le plus automatique possible:

1. Renseigne `email`, `password`, `profile_name` et, si besoin, la matrice
   `profiles` dans `config/streaming_platform_config.local.json`.
2. Lance Chrome en CDP, ou laisse `main_ingestion.py` le démarrer si `RPA_CDP_URL` est défini.
3. L'ingestion charge automatiquement l'extension locale au démarrage de Chrome et tente le login RPA sur chaque plateforme.
4. Si une plateforme impose MFA, CAPTCHA ou validation appareil, termine cette étape dans Chrome; la session restera conservée ensuite.

Commande Windows/WSL validée pour démarrer Chrome manuellement en CDP:

```powershell
$profileDir = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data'
Start-Process chrome.exe -ArgumentList @(
  '--remote-debugging-port=9222',
  '--remote-debugging-address=0.0.0.0',
  '--remote-allow-origins=*',
  "--user-data-dir=$profileDir"
)
```

Si Chrome est déjà ouvert sans `--remote-debugging-port`, le script propose de le fermer et de le relancer avec CDP + extension. Pour accepter automatiquement, utilise `--force-restart-chrome`. Une extension Chrome ne peut pas être injectée dans une session CDP déjà ouverte; elle est chargée automatiquement uniquement au lancement de Chrome.

Les artefacts de debug sont créés dans:

```text
artifacts/rpa/<plateforme>/
```

Pour ingérer tous les profils applicatifs configurés et cliquer le bon profil
dans chaque service de streaming:

```bash
python main_ingestion.py \
  --cdp-url http://127.0.0.1:9222 \
  --all-profiles \
  --rpa-mode full
```

Pour ingérer un seul profil applicatif:

```bash
python main_ingestion.py \
  --cdp-url http://127.0.0.1:9222 \
  --profile-key junior \
  --rpa-mode differential
```

## Rejouer une ingestion

### Depuis l'environnement local WSL

Relancer toutes les plateformes en différentiel avec le Chrome CDP local :

```bash
python main_ingestion.py \
  --cdp-url http://127.0.0.1:9222 \
  --rpa-mode differential
```

Relancer une seule plateforme :

```bash
python main_ingestion.py \
  --platform crunchyroll \
  --cdp-url http://127.0.0.1:9222 \
  --rpa-mode differential \
  --skip-crunchyroll-api
```

Relancer toutes les plateformes en full :

```bash
python main_ingestion.py \
  --cdp-url http://127.0.0.1:9222 \
  --rpa-mode full
```

### Depuis Docker avec Chrome conteneurisé

Le compose `docker-compose.ingestion.yml` lance un Chrome dédié (`rpa-chrome`)
et le job RPA dans le même environnement réseau. C'est le mode recommandé pour
les relances depuis l'administration web ou depuis une autre machine du réseau.

Synchronise d'abord la configuration locale dans le volume Docker :

```bash
python tools/sync_config_to_docker_volume.py
```

Relancer toutes les plateformes en différentiel :

```bash
docker compose --env-file .env -f docker-compose.ingestion.yml run --rm rpa-job \
  python main_ingestion.py \
  --cdp-url http://127.0.0.1:9222 \
  --rpa-mode differential \
  --skip-crunchyroll-api
```

Relancer une seule plateforme :

```bash
docker compose --env-file .env -f docker-compose.ingestion.yml run --rm rpa-job \
  python main_ingestion.py \
  --platform netflix \
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

Tu y trouveras les captures PNG et les DOM HTML utilisés par le self-healing.

Si une plateforme refuse la connexion dans le Chrome Docker headless, relance
avec le Chrome Windows déjà authentifié. Démarre Chrome Windows avec CDP, puis
utilise `docker-compose.rpa.yml` :

```bash
docker compose --env-file .env -f docker-compose.rpa.yml run --rm rpa-job \
  python main_ingestion.py \
  --platform netflix \
  --cdp-url http://127.0.0.1:9222 \
  --rpa-mode differential \
  --skip-crunchyroll-api \
  --no-auto-start-chrome
```

## Verification rapide

```bash
python -m compileall ingestion main_ingestion.py
```
