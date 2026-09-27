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
| `OLLAMA_BASE_URL` | URL Ollama locale |
| `OLLAMA_MODEL` | Modèle vision/chat utilisé |
| `RPA_USER_DATA_DIR` | Profil Chromium persistant |
| `PLATFORM_CONFIG_PATH` | Index ou fichier plateforme |
| `RPA_BROWSER_EXTENSION_PATH` | Extension helper locale |

## Profils applicatifs

Les profils utilisés par le web, l'API mobile et l'ingestion sont configurés
dans `.env`. Le code ne doit jamais contenir de nom de profil nominatif en dur.

```text
STREAMING_PROFILES=default|Profil principal|default|false;junior|Profil junior|junior|true
DEFAULT_PROFILE_KEY=default
```

Format de `STREAMING_PROFILES` :

```text
cle|libelle affichage|identifiant technique|profil junior
```

- `cle` : clé stable envoyée par les interfaces et stockée dans SQLite.
- `libelle affichage` : texte affiché dans les sélecteurs web/mobile.
- `identifiant technique` : valeur libre pour faire le lien avec une plateforme
  ou un annuaire si nécessaire.
- `profil junior` : `true`, `false`, `1`, `0`, `yes` ou `no`.

`DEFAULT_PROFILE_KEY` doit pointer vers une entrée de la matrice. Si la variable
est absente, le premier profil de la matrice est utilisé. Les historiques ingérés
reçoivent ce profil par défaut, puis les vues peuvent filtrer dynamiquement par
profil. Un profil marqué junior applique aussi le filtre `suitable_for_junior`.

Variables API:

| Variable | Usage |
| --- | --- |
| `BETASERIES_API_KEY` | Clé API BetaSeries |
| `BETASERIES_CLIENT_SECRET` | `oauth2 key` ou secret OAuth de l'application BetaSeries |
| `BETASERIES_ACCESS_TOKEN` | Token OAuth utilisateur BetaSeries, pas la clé secrète application |
| `BETASERIES_USER_ID` | Identifiant membre optionnel pour le planning |
| `CRUNCHYROLL_EMAIL` | Compte Crunchyroll pour wrapper non officiel |
| `CRUNCHYROLL_PASSWORD` | Mot de passe Crunchyroll |
| `CRUNCHYROLL_AUTHORIZATION` | Header `Basic ...` optionnel si le client embarqué du wrapper Crunchyroll est inactif |
| `CRUNCHYROLL_PROFILE_ID` | Profil Crunchyroll optionnel |
| `CRUNCHYROLL_LOCALE` | Locale, par défaut `fr-FR` |

Variables RPA de connexion:

```text
STREAMING_PLATFORMS={"crunchyroll":true,"netflix":true,"prime_video":true,"disney_plus":true,"canal_plus":true}
STREAMING_PLATFORM_CONFIG={"netflix":{"email":"","password":"","profile_name":""},"disney_plus":{"email":"","password":"","profile_name":""}}
```

`STREAMING_PLATFORMS` active ou désactive chaque plateforme. Une plateforme à
`false` est ignorée par l'orchestrateur RPA, sauf si elle est retirée de la
configuration plateforme.

`STREAMING_PLATFORM_CONFIG` contient les informations de connexion RPA par
plateforme:

```json
{
  "netflix": {
    "email": "user@example.test",
    "password": "mot_de_passe",
    "profile_name": "Profil affiché"
  }
}
```

La clé canonique est `profile_name`. La variante `profil_name` est acceptée pour
tolérer les anciennes saisies, mais la documentation utilise `profile_name`.
Les anciennes variables `NETFLIX_EMAIL`, `NETFLIX_PASSWORD`,
`NETFLIX_PROFILE_NAME`, etc. restent supportées en fallback pour ne pas casser
les environnements existants. Les valeurs sensibles et les noms de profil ne
sont pas écrits dans les logs. La connexion manuelle ne reste nécessaire que
pour les validations interactives comme MFA, CAPTCHA ou approbation d'un nouvel
appareil.

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
