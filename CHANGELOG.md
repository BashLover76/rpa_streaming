# Changelog

Tous les changements notables de ce projet sont documentés ici.

Le format suit l'esprit de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet utilise pour l'instant un versionnement interne non tagué.

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

### Modifié

- Le `README.md` racine est devenu une page d'entrée courte.
- Les détails d'installation, configuration, architecture, usage et observabilité ont été déplacés dans `docs/`.
- Les connecteurs Apple TV+, Max, Paramount+ et OCS sont traités via le parcours CANAL+ quand ils sont inclus dans le compte.

### Sécurité

- Les secrets restent centralisés dans `.env`.
- Les credentials RPA ne sont pas écrits dans les logs.
- Les opérations destructrices distantes restent en dry-run par défaut et demandent `--apply`.
