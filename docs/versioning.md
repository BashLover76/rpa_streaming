# Versioning, branches et commits

## Version applicative

Le projet suit un versioning sémantique simple :

- `MAJOR` : rupture de compatibilité API, mobile ou base de données.
- `MINOR` : nouvelle fonctionnalité compatible.
- `PATCH` : correctif sans changement fonctionnel majeur.

Version courante : `0.3.0`.

Les emplacements à mettre à jour ensemble sont :

- `android/app/build.gradle.kts` : `versionCode` et `versionName`.
- `android/app/src/main/java/fr/local/streamingdb/MainActivity.java` : `APP_VERSION`.
- `docker-compose.web.yml` : tag par défaut de l'image web.
- `docker-compose.rpa.yml` : tag par défaut de l'image RPA.
- `.env.example` : tags Docker documentés.
- `CHANGELOG.md`.

## Branches

Convention recommandée :

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
release/0.3.0
```

La branche actuelle peut rester telle quelle tant que le travail est local. Pour
préparer une publication propre, crée une branche `release/0.3.0` ou renomme la
branche de travail avant merge.

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

Évite de réécrire l'historique déjà partagé. Si l'historique n'a pas été poussé,
un squash interactif peut regrouper les micro-commits en commits lisibles par
domaine fonctionnel.
