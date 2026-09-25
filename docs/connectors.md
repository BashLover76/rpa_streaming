# Connecteurs

## Etat des connecteurs

| Plateforme | Stratégie | Config | Variables utiles |
| --- | --- | --- | --- |
| BetaSeries | API officielle | `.env` | `BETASERIES_API_KEY`, `BETASERIES_CLIENT_SECRET`, `BETASERIES_ACCESS_TOKEN`, `BETASERIES_USER_ID` optionnel |
| Crunchyroll | API non officielle puis RPA secours | `config/platforms/crunchyroll.json` | `CRUNCHYROLL_EMAIL`, `CRUNCHYROLL_PASSWORD`, `CRUNCHYROLL_PROFILE_ID`, `CRUNCHYROLL_LOCALE` |
| Netflix | RPA | `config/platforms/netflix.json` | `NETFLIX_EMAIL`, `NETFLIX_PASSWORD` ou session Chrome déjà connectée |
| Prime Video | RPA | `config/platforms/prime_video.json` | `PRIME_VIDEO_EMAIL`, `PRIME_VIDEO_PASSWORD` ou session Chrome déjà connectée |
| Disney+ | RPA + extension helper | `config/platforms/disney_plus.json` | `DISNEY_PLUS_EMAIL`, `DISNEY_PLUS_PASSWORD` ou session Chrome déjà connectée |
| CANAL+ | RPA + extension helper | `config/platforms/canal_plus.json` | `CANAL_PLUS_EMAIL`, `CANAL_PLUS_PASSWORD`, `CANAL_PLUS_PROFILE_NAME` |
| Apple TV+ | Via CANAL+ | `config/platforms/canal_plus.json` | Compte CANAL+ |
| HBO Max / Max | Via CANAL+ | `config/platforms/canal_plus.json` | Compte CANAL+ |
| Paramount+ | Via CANAL+ | `config/platforms/canal_plus.json` | Compte CANAL+ |
| OCS | Via CANAL+ | `config/platforms/canal_plus.json` | Compte CANAL+ |

## Notes API et RPA

- Crunchyroll: des wrappers Python non officiels existent et peuvent récupérer des données de compte selon les endpoints encore disponibles. Ces wrappers restent fragiles, donc la config prévoit `api_then_rpa`.
- Netflix: l'API publique a été retirée; l'historique officiel reste consultable dans les paramètres du compte. Le RPA cible cette page.
- Prime Video: pas d'API publique d'historique personnel; la page Watch History web est utilisée quand disponible.
- Disney+: pas d'historique complet exposé à l'utilisateur sur le web; le RPA exploite surtout les rails visibles comme Continue Watching.
- CANAL+, Apple TV+, Max, Paramount+, OCS: un seul parcours RPA CANAL+ est utilisé lorsque ces catalogues sont inclus dans le compte CANAL+.
- ARTE.tv: certains endpoints catalogue sont publics, mais l'historique personnel dépend du compte et reste traité en RPA.
