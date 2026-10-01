# Changelog

Tous les changements notables de ce projet sont documentés ici.

## [0.7.2] - 2026-10-01

### Corrigé

- Le RPA refuse désormais les sélecteurs self-healing qui pointent vers une interface de connexion au lieu d'un historique.
- Après une connexion RPA, l'ingestion vérifie que la page d'historique est réellement atteinte avant d'extraire les cartes.
- Les échecs d'authentification ou de sélection de profil produisent un message explicite dans les logs admin au lieu d'une ingestion vide ambiguë.

## [0.7.1] - 2026-10-01

### Corrigé

- Les statuts mobiles d'ingestion conservent le message d'erreur quand un log admin contient plusieurs evenements sur une seule ligne.

## [0.7.0] - 2026-10-01

### Ajouté

- Compose d'ingestion dedie avec un conteneur Chrome CDP separe du conteneur RPA.
- Les relances RPA depuis l'administration web utilisent le compose d'ingestion conteneurise par defaut.

### Modifié

- Le job RPA Docker cible  dans le reseau Docker d'ingestion au lieu du Chrome du poste client.

## [0.6.0] - 2026-10-01

### Modifié

- L'image Docker web utilise un healthcheck Go statique à la place de .
- Le runtime web évite l'installation de paquets système inutiles pour réduire la surface et accélérer le build incrémental.

## [0.5.1] - 2026-10-01

### Corrigé

- Les relances RPA Docker depuis l'administration web ne dépendent plus d'un fichier  absent dans le conteneur web.
- Le compose RPA lit les fichiers de configuration locaux depuis le volume Docker partagé.

### Ajouté

- L'API mobile expose les derniers statuts d'ingestion par plateforme.
- L'écran Admin Android affiche les derniers statuts d'ingestion avec OK/KO, nombre d'items ajoutés et erreur éventuelle.

## [0.5.0] - 2026-09-27

### Ajouté

- Matrice de profils de streaming par plateforme exposée dans l'API mobile.
- Écran Android Admin listant les profils plateforme associés aux profils
  applicatifs.
- Options d'ingestion `--all-profiles` et `--profile-key` pour lancer le RPA sur
  un ou plusieurs profils applicatifs.
- Annotation des historiques RPA avec le profil applicatif actif.

### Modifié

- Le RPA tente de sélectionner le profil plateforme configuré sur les écrans de
  sélection de profil Netflix, Prime Video, Disney+ et CANAL+.
- Les exemples de configuration documentent maintenant `profiles` par
  plateforme.
- La collecte CANAL+ possède un fallback de sélecteurs pour la vue
  `Mes vidéos > Vu récemment`.

### Sécurité

- Les fichiers `config/*.local.json` sont exclus du contexte Docker et copiés
  dans un volume Docker de configuration via un outil dédié.

## [0.4.3] - 2026-09-27

### Corrigé

- Démarrage Docker web corrigé lorsque Docker Desktop/WSL expose le bind mount
  config comme répertoire vide : l'image embarque désormais les fichiers de
  configuration au lieu de les masquer par défaut.
- Documentation et tags Docker alignés sur 0.4.3.

## [0.4.2] - 2026-09-27

### Corrigé

- Recherche mobile offline rendue réactive : les listes séries, films,
  calendrier et reprise se filtrent dès la saisie.
- Chargement automatique des profils dans l'écran Admin Android quand le
  bootstrap n'est pas encore présent dans le cache local.
- Protection contre les doubles chargements de bootstrap pendant la récupération
  des profils.

### Ajouté

- Wrapper Gradle Android `8.10.2` versionné pour produire l'APK sans dépendre du
  `gradle` système installé sur la machine.

## [0.4.1] - 2026-09-27

### Corrigé

- Tri API/mobile des séries et films par vraie date de visionnage uniquement :
  les valeurs invalides comme `unknown` ou `YYYY-MM-DD` ne passent plus devant
  les derniers visionnages Crunchyroll.
- Sélection de profil mobile : un profil local obsolète est remplacé par le
  profil par défaut exposé par le serveur, puis par le premier profil disponible
  si nécessaire.
- Cache mobile des listes et calendriers séparé par profil pour éviter les
  mélanges de flux après synchronisation.
- Écran Admin Android : ajout d'un chargement direct du bootstrap quand les
  profils ne sont pas encore présents dans le cache offline.

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
