# Changelog

Tous les changements notables de ce projet sont documentés ici.

Le format suit l'esprit de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet utilise pour l'instant un versionnement interne non tagué.

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
- Login RPA par plateforme depuis les variables `*_EMAIL` et `*_PASSWORD` du `.env`.
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

- Les secrets restent centralisés dans `.env`.
- Les credentials RPA ne sont pas écrits dans les logs.
- Les opérations destructrices distantes restent en dry-run par défaut et demandent `--apply`.
