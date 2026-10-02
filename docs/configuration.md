# Configuration

## Configuration des plateformes

L'index `config/platforms.example.json` liste les fichiers actifs:

```json
[
  "config/platforms/netflix.json",
  "config/platforms/prime_video.json",
  "config/platforms/disney_plus.json"
]
```

Tu peux créer ton propre index:

```bash
cp config/platforms.example.json config/platforms.local.json
```

Puis modifier `.env`:

```text
PLATFORM_CONFIG_PATH=config/platforms.local.json
```

Chaque fichier plateforme contient:

- `strategy`: `rpa`, `api_then_rpa` ou futur `api`.
- `api`: disponibilité, variables attendues et notes.
- `rpa.start_url`: URL de départ.
- `rpa.wait_after_login_seconds`: délai pour laisser finir login, redirections et hydratation JS.
- `rpa.requires_browser_extension`: charge l'extension helper si nécessaire.
- `rpa.selectors`: sélecteurs initiaux avant self-healing.

## Variables d'environnement

Variables communes:

| Variable | Usage |
| --- | --- |
| `STREAMING_DB_PATH` | Chemin SQLite, par défaut `streaming.db` |
| `RPA_USER_DATA_DIR` | Profil Chromium persistant |
| `PLATFORM_CONFIG_PATH` | Index ou fichier plateforme |
| `RPA_BROWSER_EXTENSION_PATH` | Extension helper locale |
| `BETASERIES_CONFIG_FILE` | Fichier JSON BetaSeries |
| `OLLAMA_CONFIG_FILE` | Fichier JSON Ollama |
| `CRUNCHYROLL_CONFIG_FILE` | Fichier JSON Crunchyroll |
| `STREAMING_PROFILES_FILE` | Fichier JSON profils applicatifs |

## Fichiers de configuration services

Les secrets et paramètres longs sont stockés dans des fichiers JSON lisibles.
Les fichiers `.example.json` sont versionnés. Copie-les en `.local.json` pour
tes valeurs réelles, puis pointe `.env` vers ces fichiers locaux.

```text
BETASERIES_CONFIG_FILE=config/betaseries.local.json
OLLAMA_CONFIG_FILE=config/ollama.local.json
CRUNCHYROLL_CONFIG_FILE=config/crunchyroll.local.json
STREAMING_PROFILES_FILE=config/streaming_profiles.local.json
```

Exemple BetaSeries:

```json
{
  "api_key": "your_betaseries_api_key",
  "client_secret": "your_oauth2_key_or_secret_key",
  "access_token": "",
  "user_id": ""
}
```

Exemple Ollama:

```json
{
  "model": "gemma3:4b",
  "base_url": "http://localhost:11434",
  "num_ctx": 32768,
  "num_predict": 4096,
  "timeout": 300
}
```

Exemple Crunchyroll:

```json
{
  "email": "",
  "password": "",
  "authorization": "",
  "profile_id": "",
  "locale": "fr-FR"
}
```

## Profils applicatifs

Les profils utilisés par le web, l'API mobile et l'ingestion sont configurés
dans `STREAMING_PROFILES_FILE`. Le code ne doit jamais contenir de nom de profil
nominatif en dur.

```json
{
  "default_profile_key": "default",
  "profiles": {
    "default": {
      "label": "Profil principal",
      "technical_id": "default",
      "is_junior": false
    },
    "junior": {
      "label": "Profil junior",
      "technical_id": "junior",
      "is_junior": true
    }
  }
}
```

## Méta-profils et profils plateforme

L'administration web expose `/admin/profiles` pour relier plusieurs profils de
plateformes sous un même méta-profil applicatif. Ces méta-profils sont stockés
dans `.continue/meta_profiles.json` et exposés à l'application mobile via
`/api/mobile/bootstrap`.

Si aucune matrice n'existe encore, la page admin propose sa création à partir
des profils détectés automatiquement par `tools.discover_streaming_profiles`.
Seules les plateformes activées dans `STREAMING_PLATFORMS_FILE` sont affichées.
Chaque plateforme apparaît avec son badge et une liste déroulante des profils
préchargés par la synchro.

Une matrice peut aussi être déclarée manuellement en copiant:

```bash
cp config/profile_matrix.example.json config/profile_matrix.local.json
```

Le serveur lit `config/profile_matrix.local.json` tant que
`.continue/meta_profiles.json` n'a pas été créé depuis l'interface admin. Le
format attendu est:

```json
[
  {
    "key": "primary",
    "label": "Profil principal",
    "is_junior": false,
    "platforms": {
      "netflix": "Profil Netflix",
      "prime_video": "Profil Prime Video",
      "disney_plus": "Profil Disney+"
    }
  }
]
```

Lorsqu'une matrice existe, les sélecteurs web/mobile utilisent ses entrées comme
profils actifs. Les listes de séries, films, calendriers et endpoints mobiles
appliquent alors un filtrage strict sur `profile_key`: les données d'un autre
profil ne sont plus mélangées au profil actif.

La fiche détail d'un titre affiche aussi la progression du profil actif et des
autres profils de la matrice lorsque l'historique local contient ces données.

La page permet aussi de régler le seuil d'alerte de synchronisation mobile
(`sync_alert_hours`). La valeur par défaut est `24` heures et elle est stockée
dans `.continue/mobile_settings.json`.

Les profils plateforme continuent d'être alimentés depuis la configuration
serveur, mais le contrat API est prévu pour accepter des profils découverts par
l'ingestion lorsque les connecteurs RPA savent les lister. En cas d'absence de
découverte, le fallback reste la matrice déclarée dans `.env`/JSON.

- `default_profile_key` : profil appliqué automatiquement au démarrage.
- `label` : texte affiché dans les sélecteurs web/mobile.
- `technical_id` : valeur libre pour faire le lien avec une plateforme
  ou un annuaire si nécessaire.
- `is_junior` : active le filtre junior.

Les anciennes variables `STREAMING_PROFILES` et `DEFAULT_PROFILE_KEY` restent
supportées en fallback.

Résumé des fichiers JSON de services:

| Fichier | Usage |
| --- | --- |
| `config/betaseries.local.json` | Clé API, secret OAuth, token membre et identifiant utilisateur optionnel |
| `config/ollama.local.json` | Modèle, URL locale, contexte, budget de sortie et timeout |
| `config/crunchyroll.local.json` | Identifiants API non officielle Crunchyroll et locale |
| `config/streaming_profiles.local.json` | Profils applicatifs et profil par défaut |
| `config/profile_matrix.local.json` | Matrice manuelle optionnelle de méta-profils inter-plateformes |

Variables RPA de connexion:

```text
STREAMING_PLATFORMS_FILE=config/streaming_platforms.local.json
STREAMING_PLATFORM_CONFIG_FILE=config/streaming_platform_config.local.json
```

`STREAMING_PLATFORMS_FILE` pointe vers un JSON qui active ou désactive chaque
plateforme. Une plateforme à `false` est ignorée par l'orchestrateur RPA, sauf
si elle est explicitement demandée ailleurs.

```json
{
  "crunchyroll": true,
  "netflix": true,
  "prime_video": true,
  "disney_plus": true,
  "canal_plus": true
}
```

`STREAMING_PLATFORM_CONFIG_FILE` pointe vers un JSON contenant les informations
de connexion RPA par plateforme:

```json
{
  "netflix": {
    "email": "user@example.test",
    "password": "mot_de_passe",
    "profile_name": "Profil affiché",
    "profiles": {
      "default": "Profil adulte sur Netflix",
      "junior": "Profil enfant sur Netflix"
    }
  }
}
```

- `profile_name` reste le profil plateforme utilisé par défaut pour le profil
  applicatif par défaut.
- `profiles` permet de mapper chaque profil applicatif vers le nom exact à
  sélectionner dans l'écran de profil de la plateforme. Les clés doivent
  correspondre aux clés déclarées dans `config/streaming_profiles.local.json`.
- Si `profiles.default` est absent, `profile_name` est utilisé pour le profil
  applicatif par défaut.

Les deux fichiers d'exemple sont disponibles dans `config/` :

- `config/streaming_platforms.example.json`
- `config/streaming_platform_config.example.json`

Copie-les en `.local.json` pour les valeurs réelles. Les fichiers `.local.json`
sont ignorés par git.

La clé canonique est `profile_name`. La variante `profil_name` est acceptée pour
tolérer les anciennes saisies, mais la documentation utilise `profile_name`.
Les variables compactes `STREAMING_PLATFORMS` et `STREAMING_PLATFORM_CONFIG`
restent supportées, tout comme les anciennes variables `NETFLIX_EMAIL`,
`NETFLIX_PASSWORD`, `NETFLIX_PROFILE_NAME`, etc. Ces fallbacks évitent de casser
les environnements existants.

Les valeurs sensibles et les noms de profil ne sont pas écrits dans les logs. La
connexion manuelle ne reste nécessaire que pour les validations interactives
comme MFA, CAPTCHA ou approbation d'un nouvel appareil.

## Structure recommandée du `.env`

Le `.env` local est volontairement court et structuré par sections:

```text
# -----------------------------------------------------------------------------
# Core runtime
# -----------------------------------------------------------------------------
STREAMING_DB_PATH=streaming.db
RPA_USER_DATA_DIR=.playwright-profile
ADMIN_TOKEN=...

# -----------------------------------------------------------------------------
# Service configs
# -----------------------------------------------------------------------------
BETASERIES_CONFIG_FILE=config/betaseries.local.json
OLLAMA_CONFIG_FILE=config/ollama.local.json
CRUNCHYROLL_CONFIG_FILE=config/crunchyroll.local.json
STREAMING_PROFILES_FILE=config/streaming_profiles.local.json

# -----------------------------------------------------------------------------
# Streaming platform activation and RPA login config
# -----------------------------------------------------------------------------
STREAMING_PLATFORMS_FILE=config/streaming_platforms.local.json
STREAMING_PLATFORM_CONFIG_FILE=config/streaming_platform_config.local.json
```

## Securite et conformite

Ce projet est conçu pour un usage personnel local:

- Ne commit jamais `.env`.
- Ne stocke pas de cookies hors du profil Playwright.
- Ne partage pas `artifacts/rpa`, car les captures peuvent contenir des informations personnelles.
- Respecte les conditions d'utilisation des plateformes.
- Evite les cadences agressives; ce projet n'est pas un scraper massif.

## Limites connues

- Les plateformes changent souvent leurs interfaces.
- Les historiques visibles peuvent être partiels selon profil, pays et abonnement.
- Les modèles vision locaux peuvent produire un JSON imparfait; les erreurs sont loggées pour inspection.
- Les sélecteurs corrigés par self-healing sont mis à jour en mémoire; recopie-les dans le fichier config après validation.
