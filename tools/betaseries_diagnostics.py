from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

BASE_URL = "https://api.betaseries.com"


def main() -> None:
    load_dotenv()
    api_key = os.getenv("BETASERIES_API_KEY", "")
    token = os.getenv("BETASERIES_ACCESS_TOKEN", "")
    if not api_key or not token:
        raise SystemExit("BETASERIES_API_KEY and BETASERIES_ACCESS_TOKEN are required")

    headers = {
        "X-BetaSeries-Key": api_key,
        "X-BetaSeries-Version": "3.3",
        "X-BetaSeries-Token": token,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    with httpx.Client(timeout=30.0) as client:
        member = get_json(client, "/members/infos", headers)
        member_info = member.get("member", {})
        print("Member id:", member_info.get("id"))
        print("Login:", member_info.get("login"))
        print("Stats:", member_info.get("stats", {}))

        planning = get_json(
            client,
            "/planning/member",
            headers,
            params={
                "id": member_info.get("id"),
                "before": 365,
                "after": 365,
                "unseen": "false",
            },
        )
        print("Planning episodes:", len(planning.get("episodes", [])))

        shows = get_json(client, "/shows/member", headers)
        print("Member shows:", len(shows.get("shows", [])))


def get_json(
    client: httpx.Client,
    path: str,
    headers: dict[str, str],
    params: dict[str, object] | None = None,
) -> dict:
    response = client.get(f"{BASE_URL}{path}", headers=headers, params=params)
    print(path, "HTTP", response.status_code)
    if response.is_error:
        print(response.text[:500])
        return {}
    return response.json()


if __name__ == "__main__":
    main()
