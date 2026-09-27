# Changelog

Tous les changements notables de ce projet sont documentés ici.

Le format suit l'esprit de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet utilise pour l'instant un versionnement interne non tagué.

## [0.4.0] - 2026-09-27

### Ajouté

- Matrice de profils configurable via `.env` avec `STREAMING_PROFILES` et
  `DEFAULT_PROFILE_KEY`.
- Mapping JSON `STREAMING_PLATFORMS` et `STREAMING_PLATFORM_CONFIG` pour gérer
  l'activation, les credentials RPA et les profils par plateforme.
- Fichiers JSON dédiés `STREAMING_PLATFORMS_FILE` et
  `STREAMING_PLATFORM_CONFIG_FILE` pour garder une configuration plateformes
  aérée et lisible.
- Fichiers JSON dédiés BetaSeries, Ollama, Crunchyroll et profils applicatifs
  pour éviter les longues variables `.env`.
- Colonnes SQLite `profile_key` et `suitable_for_junior` pour les titres et les
  historiques.
- Sélecteur de profil dans les vues web séries, films et calendrier.
- Exposition des profils dans l'API mobile et sélection du profil actif dans
  l'écran Admin Android.
- Documentation de configuration des profils et du comportement mobile associé.

### Modifié

- Les flux web et API mobile filtrent selon le profil actif et le flag junior.
- Les listes séries et films sont triées en priorité par dernière date de
  visionnage ou d'ingestion en ordre antéchronologique.
- L'ingestion annote les nouveaux historiques avec le profil par défaut sans
  valeur nominative hardcodée.
- Le compose RPA lit maintenant `.env` et transmet la configuration JSON des
  plateformes au conteneur.
- Les compose web/RPA montent `./config` en lecture seule pour lire les fichiers
  `.local.json` sans les intégrer aux images Docker.

## [0.3.0] - 2026-09-26

### Ajouté

- Versioning explicite des images Docker web/RPA avec tags configurables.
- Versioning Android `0.3.0` visible depuis l'écran Admin mobile.
- Support multilingue français, anglais et espagnol pour les vues web principales.
- Sélecteur de langue web par drapeaux avec persistance cookie.
- Support multilingue français, anglais et espagnol dans l'application Android.
- Sélecteur de langue mobile par drapeaux dans l'écran Admin.
- En-têtes HTTP de durcissement web : `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy` et `Permissions-Policy`.

### Modifié

- Vue mobile `Reprendre` filtrée pour exclure les séries déjà totalement vues.
- Vue détail mobile : prochaines sorties avant historique récent, avec bloc masqué
  pour les films.
- Grille mobile responsive selon la largeur écran et les paramètres de grille.
- Documentation Docker/mobile mise à jour pour le versioning et l'i18n.

## [Unreleased]

### Ajouté

- Ingestion unifiée films/séries avec historique brut conservé avant résolution.
- Résolution et enrichissement des titres via IMDb et BetaSeries.
- RPA Playwright compatible Chrome CDP, Windows, Linux et WSL.
- Démarrage automatique de Chrome avec CDP et extension locale.
- Option `--force-restart-chrome` pour fermer Chrome et le relancer avec CDP + extension.
- Login RPA par plateforme depuis les fichiers JSON locaux référencés par `.env`.
- Modes RPA `full` et `differential`.
- Logs par script et par plateforme, avec rotation quotidienne.
- Connecteur Grafana/Loki via `observability/`.
- Interface web séries, films, calendrier, détails, administration, logs et KPIs.
- Documentation découpée dans `docs/`.
- Dockerisation de la web app/API via `Dockerfile.web` et `docker-compose.web.yml`.
- API mobile `/api/mobile/*` pour consultation séries, films, calendrier et détails.
- Squelette d'application Android native synchronisée avec l'API du serveur local.

### Modifié

- Le `README.md` racine est devenu une page d'entrée courte.
- Les détails d'installation, configuration, architecture, usage et observabilité ont été déplacés dans `docs/`.
- Les connecteurs Apple TV+, Max, Paramount+ et OCS sont traités via le parcours CANAL+ quand ils sont inclus dans le compte.

### Sécurité

- Les secrets restent centralisés dans `.env` et les fichiers `config/*.local.json`
  ignorés par git.
- Les credentials RPA ne sont pas écrits dans les logs.
- Les opérations destructrices distantes restent en dry-run par défaut et demandent `--apply`.
