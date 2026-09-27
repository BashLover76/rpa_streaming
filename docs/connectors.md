# Connecteurs

## Etat des connecteurs

| Plateforme | Stratégie | Config | Paramètres utiles |
| --- | --- | --- | --- |
| BetaSeries | API officielle | `config/betaseries.local.json` | `api_key`, `client_secret`, `access_token`, `user_id` optionnel |
| Crunchyroll | API non officielle puis RPA secours | `config/crunchyroll.local.json` + `config/platforms/crunchyroll.json` | `email`, `password`, `authorization`, `profile_id`, `locale` |
| Netflix | RPA | `config/streaming_platform_config.local.json` + `config/platforms/netflix.json` | `email`, `password`, `profile_name` ou session Chrome déjà connectée |
| Prime Video | RPA | `config/streaming_platform_config.local.json` + `config/platforms/prime_video.json` | `email`, `password`, `profile_name` ou session Chrome déjà connectée |
| Disney+ | RPA + extension helper | `config/streaming_platform_config.local.json` + `config/platforms/disney_plus.json` | `email`, `password`, `profile_name` ou session Chrome déjà connectée |
| CANAL+ | RPA + extension helper | `config/streaming_platform_config.local.json` + `config/platforms/canal_plus.json` | `email`, `password`, `profile_name` |
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
