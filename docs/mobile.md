# Application Android StreamPilot

Le dossier `android/` contient l'application Android native `StreamPilot`.
Elle consomme l'API web du serveur local, fonctionne offline après synchronisation
et ne lance pas le RPA.

Version actuelle : `0.3.0`. Le numéro de version est visible dans l'écran
`Admin` de l'application.

## Synchronisation avec le serveur local

1. Lance la web app/API sur le serveur local :

```bash
docker compose -f docker-compose.web.yml up -d --build
python tools/sync_db_to_web_container.py --restart
```

2. Depuis le téléphone, vérifie que le serveur local est joignable sur le réseau local :

```text
http://ADRESSE_IP_DU_SERVEUR_LOCAL:5000/api/mobile/bootstrap
```

Sous Windows/WSL, il peut être nécessaire d'autoriser explicitement le port
web dans le pare-feu Windows. Lance PowerShell en administrateur :

```powershell
New-NetFirewallRule `
  -DisplayName "Streaming DB Web 5000" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 5000 `
  -Profile Private
```

Si le navigateur du téléphone ne charge pas l'URL `/api/mobile/bootstrap`, le
problème est réseau ou pare-feu avant d'être un problème applicatif.

3. Dans l'application Android, renseigne l'URL du serveur local, par exemple :

```text
http://192.168.1.50:5000
```

L'application stocke cette URL dans ses préférences locales et interroge ensuite les endpoints `/api/mobile/*`.

## Mode offline

Le bouton `Synchro` télécharge les données depuis le serveur local quand le
téléphone est connecté au même réseau local :

- bootstrap mobile ;
- liste complète des séries ;
- liste complète des films ;
- détail de chaque titre ;
- calendriers mensuels préchargés, de 6 mois avant le mois courant à 12 mois après.

Ces payloads sont conservés dans le stockage local de l'application. Après une
synchro réussie, les vues `Séries`, `Films`, `Calendrier`, `Détails` et
`Admin`
continuent donc à fonctionner sans accès réseau. Les boutons `Ouvrir` gardent
les deeplinks connus, mais l'ouverture effective dépend naturellement des apps
de streaming et de la connexion disponible.

Fonctionnalités mobiles :

- liste des séries et films par pages de 10 ;
- image et titre sur la vue principale ;
- détail avec affiche, synopsis, historique et prochaines sorties ;
- badges plateforme dans les détails ;
- tri des listes par dernière date de visionnage ;
- recherche offline ;
- calendrier jour par jour avec carrousel d'affiches ;
- retour Android natif vers l'écran précédent ;
- écran `Admin` pour configurer l'URL du serveur local, lancer la synchro,
  régler la grille/pagination, voir les KPIs offline et lire le log de debug
  de synchronisation.
- sélecteur de langue par drapeaux : français, anglais et espagnol.
- sélection dynamique du profil depuis la matrice exposée par
  `/api/mobile/bootstrap`, avec application automatique du profil par défaut.

Le cache mobile utilise des fichiers JSON et un cache local d'images dans le
stockage privé de l'application. Une erreur sur une fiche n'arrête plus toute
la synchro : elle est reportée dans le bloc `Debug synchro`.

Quand un profil est sélectionné dans `Admin`, la prochaine synchronisation
télécharge les séries, films et calendriers filtrés pour ce profil. Le choix est
conservé dans les préférences locales de l'application.

Pour rafraîchir les données, reconnecte le téléphone au réseau local du
serveur local puis appuie à nouveau sur `Synchro`.

## Deep links streaming

Les boutons `Ouvrir` utilisent des liens HTTPS de plateforme :

- lien épisode collecté dans `history.episode_url` si disponible ;
- lien épisode calendrier `calendar.episode_url` si disponible ;
- fallback recherche plateforme, par exemple Crunchyroll, Netflix, Prime Video, Disney+ ou CANAL+.

Android transmet ces liens au système avec `Intent.ACTION_VIEW`. Si l'application de streaming associée est installée et déclare le domaine correspondant, elle s'ouvre directement. Sinon, Android ouvre le navigateur.

## Build debug

Depuis une machine avec Android Studio ou le SDK Android :

```bash
export ANDROID_HOME="$PWD/android-sdk"
export ANDROID_SDK_ROOT="$PWD/android-sdk"
.local/gradle/gradle-8.10.2/bin/gradle -p android :app:assembleDebug
```

Si tu utilises Android Studio, ouvre le dossier `android/` puis lance la configuration `app`.

L'APK debug est généré dans :

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

## Limites

- L'application mobile lit uniquement les données synchronisées sur le serveur local.
- Les opérations admin et RPA ne sont pas exposées dans l'application.
- Les images sont mises en cache dans le stockage privé de l'application après
  synchronisation ou première consultation.
