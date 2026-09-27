# GitFlow strict

Ce projet suit un GitFlow strict. Aucun changement fonctionnel ne doit être
poussé directement sur `main`.

## Branches longues

- `main` : état publié uniquement. Elle reçoit des merges de release ou de
  hotfix, puis un tag de version.
- `develop` : intégration des fonctionnalités validées avant préparation de
  release.

## Branches courtes

| Type | Format | Destination |
| --- | --- | --- |
| Fonctionnalité | `feature/<scope>-<description>` | `develop` |
| Correctif non urgent | `fix/<scope>-<description>` | `develop` |
| Documentation | `docs/<scope>-<description>` | `develop` |
| Release | `release/<version>` | `main` et `develop` |
| Hotfix production | `hotfix/<version>` | `main` et `develop` |

## Règles obligatoires

1. Créer une branche dédiée avant toute modification suivie par git.
2. Ne jamais commit directement sur `main`, sauf commit de merge de release ou
   hotfix.
3. Mettre à jour la version et le changelog sur la branche `release/<version>`.
4. Exécuter les tests adaptés avant merge.
5. Merger la release dans `main` avec `--no-ff`.
6. Tagger `main` avec `v<version>`.
7. Merger ensuite `main` vers `develop` pour réaligner l'intégration.
8. Pousser les branches et tags explicitement.

## Commandes type

Préparer une fonctionnalité :

```bash
git switch develop
git pull --ff-only origin develop
git switch -c feature/config-json-files
```

Finaliser une release :

```bash
git switch develop
git switch -c release/0.4.0
# bump version + changelog + tests
git commit -m "chore(release): prepare 0.4.0"
git switch main
git merge --no-ff release/0.4.0 -m "merge: release 0.4.0"
git tag -a v0.4.0 -m "Release 0.4.0"
git switch develop
git merge --no-ff main -m "merge: main back into develop"
git push origin main develop release/0.4.0 --tags
```

Hotfix production :

```bash
git switch main
git pull --ff-only origin main
git switch -c hotfix/0.4.1
# fix + tests + changelog
git commit -m "fix(scope): short description"
git switch main
git merge --no-ff hotfix/0.4.1 -m "merge: hotfix 0.4.1"
git tag -a v0.4.1 -m "Release 0.4.1"
git switch develop
git merge --no-ff main -m "merge: hotfix 0.4.1 back into develop"
git push origin main develop hotfix/0.4.1 --tags
```

## Checklist avant release

- `CHANGELOG.md` contient une entrée datée pour la version.
- Les versions Android, Docker et documentation sont alignées.
- `.env` et `config/*.local.json` ne sont pas suivis par git.
- Les tests Python passent.
- Le build Android passe si la release touche l'application mobile.
- `docker compose config` passe si la release touche Docker.
