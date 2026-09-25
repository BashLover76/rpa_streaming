# Installation

## Prérequis

- Python 3.10 ou supérieur.
- SQLite, inclus avec Python.
- Ollama installé localement.
- Un modèle Ollama vision, par exemple `llava:latest`.
- Un compte BetaSeries avec clé API.
- Comptes personnels sur les plateformes que tu veux synchroniser.
- Chromium Playwright.

## Installation

Installation automatique des composants système et Python selon l'OS détecté
(Windows, Linux natif ou WSL) :

```bash
python tools/install_system_dependencies.py
```

Options utiles :

```bash
# Afficher les commandes sans les exécuter
python tools/install_system_dependencies.py --dry-run

# Installer aussi Ollama quand le gestionnaire système le permet
python tools/install_system_dependencies.py --with-ollama
```

Le script installe ou prépare :

- Windows : Python, Git, Google Chrome via `winget` quand disponible.
- WSL : paquets Ubuntu/Debian requis, venv Python et dépendances projet. Chrome
  reste lancé côté Windows via CDP.
- Linux natif : paquets Ubuntu/Debian requis, Google Chrome stable, venv Python
  et dépendances projet.
- Tous les OS : `pip install -r requirements.txt` et `playwright install chromium`.

Installation manuelle équivalente :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
ollama pull llava:latest
```

Le fichier `.env` est généré avec des valeurs vides. Renseigne au minimum:

```text
BETASERIES_API_KEY=
BETASERIES_ACCESS_TOKEN=
OLLAMA_MODEL=gemma3:4b
OLLAMA_BASE_URL=http://localhost:11434
```

Pour Crunchyroll via API non officielle:

```text
CRUNCHYROLL_EMAIL=
CRUNCHYROLL_PASSWORD=
CRUNCHYROLL_AUTHORIZATION=
CRUNCHYROLL_PROFILE_ID=
CRUNCHYROLL_LOCALE=fr-FR
```
