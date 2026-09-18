from __future__ import annotations

import os
import time

import httpx
from dotenv import load_dotenv

BASE_URL = "https://api.betaseries.com"


def main() -> None:
    load_dotenv()
    api_key = os.getenv("BETASERIES_API_KEY", "")
    client_secret = os.getenv("BETASERIES_CLIENT_SECRET") or os.getenv(
        "BETASERIES_OAUTH2_KEY", ""
    )
    if not api_key:
        raise SystemExit("BETASERIES_API_KEY is missing in .env")
    if not client_secret:
        raise SystemExit("BETASERIES_CLIENT_SECRET is missing in .env")

    headers = {
        "X-BetaSeries-Key": api_key,
        "X-BetaSeries-Version": "3.3",
        "User-Agent": "rpa_streaming/0.1",
        "Accept": "application/json",
    }

    with httpx.Client(timeout=30.0) as client:
        print("Demande d'un code device à BetaSeries...", flush=True)
        device_response = client.post(f"{BASE_URL}/oauth/device", headers=headers)
        print(f"Réponse /oauth/device: HTTP {device_response.status_code}", flush=True)
        device_response.raise_for_status()
        device = device_response.json()

        print("Ouvre cette URL dans ton navigateur:", flush=True)
        print(device["verification_url"], flush=True)
        print(flush=True)
        print("Puis saisis ce code:", flush=True)
        print(device["user_code"], flush=True)
        print(flush=True)
        print("En attente de validation BetaSeries...", flush=True)

        interval = int(device.get("interval", 5))
        expires_at = time.monotonic() + int(device.get("expires_in", 1800))
        while time.monotonic() < expires_at:
            token_response = client.post(
                f"{BASE_URL}/oauth/access_token",
                headers=headers,
                data={
                    "client_id": api_key,
                    "client_secret": client_secret,
                    "code": device["device_code"],
                },
            )
            if token_response.status_code == 200:
                token_payload = token_response.json()
                token = (
                    token_payload.get("access_token")
                    or token_payload.get("token")
                    or token_payload.get("member", {}).get("token")
                )
                if token:
                    print()
                    print("Token utilisateur obtenu. Mets cette valeur dans .env:")
                    print(f"BETASERIES_ACCESS_TOKEN={token}")
                    return
                print(token_payload)
                raise SystemExit("Réponse OAuth reçue, mais token introuvable.")

            time.sleep(interval)

    raise SystemExit("Le code d'authentification a expiré.")


if __name__ == "__main__":
    main()
