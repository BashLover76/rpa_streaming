# Versioning, branches et commits

## Version applicative

Le projet suit un versioning sémantique simple :

- `MAJOR` : rupture de compatibilité API, mobile ou base de données.
- `MINOR` : nouvelle fonctionnalité compatible.
- `PATCH` : correctif sans changement fonctionnel majeur.

Version courante : `0.7.0`.

Les emplacements à mettre à jour ensemble sont :

- `android/app/build.gradle.kts` : `versionCode` et `versionName`.
- `android/app/src/main/java/fr/local/streamingdb/MainActivity.java` : `APP_VERSION`.
- `docker-compose.web.yml` : tag par défaut de l'image web.
- `docker-compose.rpa.yml` : tag par défaut de l'image RPA.
- `.env.example` : tags Docker documentés.
- `CHANGELOG.md`.

## Branches

La politique de branche est définie dans [GitFlow strict](gitflow.md). Résumé :

```text
feature/<scope>-<description>
fix/<scope>-<description>
docs/<scope>-<description>
chore/<scope>-<description>
release/<version>
```

Exemples :

```text
feature/mobile-i18n
feature/docker-versioning
fix/mobile-resume-filter
docs/security-versioning
release/0.7.0
```

`main` ne reçoit pas de commits directs. Elle reçoit uniquement des merges
`--no-ff` depuis `release/<version>` ou `hotfix/<version>`, puis un tag
annoté `v<version>`.

## Commits

Format recommandé :

```text
type(scope): résumé court
```

Types utilisés :

- `feat` : nouvelle fonctionnalité.
- `fix` : correction.
- `docs` : documentation.
- `chore` : maintenance, versioning, outillage.
- `test` : tests.
- `refactor` : restructuration sans changement fonctionnel.

Découpage conseillé pour les changements récents :

```text
feat(mobile): add offline i18n and resume filtering
feat(web): add language selector and translated core views
chore(docker): version web and rpa images
docs: document i18n versioning and docker tags
```

Toute correction d'historique partagé doit rester exceptionnelle, être demandée
explicitement, et être suivie d'un `--force-with-lease`. En dehors de ce cas,
on corrige par nouveau commit sur une branche appropriée.
