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

Copie d'abord les fichiers d'exemple vers leurs variantes locales ignorées par git:

```bash
cp .env.example .env
cp config/betaseries.example.json config/betaseries.local.json
cp config/ollama.example.json config/ollama.local.json
cp config/crunchyroll.example.json config/crunchyroll.local.json
cp config/streaming_profiles.example.json config/streaming_profiles.local.json
cp config/streaming_platforms.example.json config/streaming_platforms.local.json
cp config/streaming_platform_config.example.json config/streaming_platform_config.local.json
```

Renseigne au minimum `config/betaseries.local.json`:

```json
{
  "api_key": "your_betaseries_api_key",
  "client_secret": "your_oauth2_key_or_secret_key",
  "access_token": "",
  "user_id": ""
}
```

Vérifie aussi `config/ollama.local.json` :

```json
{
  "model": "gemma3:4b",
  "base_url": "http://localhost:11434",
  "num_ctx": 32768,
  "num_predict": 4096,
  "timeout": 300
}
```

Pour Crunchyroll via API non officielle, complète `config/crunchyroll.local.json` :

```json
{
  "email": "",
  "password": "",
  "authorization": "",
  "profile_id": "",
  "locale": "fr-FR"
}
```
