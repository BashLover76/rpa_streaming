"""Resolve observed titles conservatively across IMDb and BetaSeries."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote

import httpx


def title_key(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).casefold()
    return "".join(char for char in text if char.isalnum())


def clean_title(title: str) -> str:
    text, _episode_title = split_streaming_title(title)
    return text.strip()


def split_streaming_title(title: str) -> tuple[str, str | None]:
    text = re.sub(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s+", "", title)
    text = re.split(
        r"\s+(?:Report a problem|Signaler un probl[eè]me)\b", text, flags=re.I
    )[0]
    episode_title = None
    quoted = re.search(r':\s*["“]([^"”]+)["”]?\s*$', text)
    if quoted:
        episode_title = quoted.group(1).strip()
        text = text[: quoted.start()].strip()
    season_split = re.split(r"\s*:\s*(?:Season|Saison)\s+\d+\b", text, flags=re.I)
    if len(season_split) > 1:
        text = season_split[0]
    text = re.sub(r"\s+-\s+(?:Season|Saison)\s+\d+\s*$", "", text, flags=re.I)
    text = _dedupe_colon_title(text)
    return text.strip(), episode_title


def _dedupe_colon_title(text: str) -> str:
    parts = text.split(": ")
    for split in range(1, len(parts)):
        left, right = ": ".join(parts[:split]), ": ".join(parts[split:])
        if title_key(left) == title_key(right):
            return left
    return text.strip()


def imdb_kind(candidate: dict) -> str | None:
    kind = candidate.get("qid") or candidate.get("q") or ""
    key = title_key(kind)
    if key in {"movie", "feature", "tvmovie", "video", "short", "tvshort"}:
        return "movie"
    if key in {"tvseries", "tvminiseries", "series", "miniseries"}:
        return "series"
    return None


class IMDbClient:
    """IMDb web suggestions: limited metadata, not the licensed GraphQL API."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self.cache: dict[str, list[dict]] = {}

    def search(self, title: str) -> list[dict]:
        if title in self.cache:
            return self.cache[title]
        response = self.client.get(
            f"https://v3.sg.media-imdb.com/suggestion/x/{quote(title, safe='')}.json"
        )
        if response.status_code == 404:
            self.cache[title] = []
            return []
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("d", []), list):
            raise ValueError("Invalid IMDb suggestion response")
        results = []
        for item in payload.get("d", []):
            if not isinstance(item, dict):
                continue
            if (
                re.fullmatch(r"tt\d+", str(item.get("id", "")))
                and isinstance(item.get("l"), str)
                and imdb_kind(item)
            ):
                results.append(item)
        self.cache[title] = results
        return results


PLATFORM_NAMES = {
    "netflix": {"netflix"},
    "prime_video": {"amazonprimevideo", "primevideo", "amazon"},
    "disney_plus": {"disney", "disneyplus"},
    "crunchyroll": {"crunchyroll"},
    "canal_plus": {
        "canal",
        "canalplus",
        "mycanal",
        "appletv",
        "max",
        "hbo",
        "paramount",
        "ocs",
    },
}


def platform_matches(details: dict, platform: str) -> bool:
    names = set()

    def visit(value):
        if isinstance(value, list):
            for entry in value:
                visit(entry)
        elif isinstance(value, dict):
            for key, entry in value.items():
                if key in {"name", "platform"} and isinstance(entry, str):
                    names.add(title_key(entry))
                elif isinstance(entry, (list, dict)):
                    visit(entry)

    for field in ("platforms", "platforms_svod", "svods"):
        visit(details.get(field))
    return bool(names & PLATFORM_NAMES.get(platform, {title_key(platform)}))


@dataclass
class Resolution:
    imdb: dict
    kind: str
    beta: dict | None = None


class TitleResolver:
    def __init__(self, imdb: IMDbClient, beta=None):
        self.imdb = imdb
        self.beta = beta
        self.cache: dict[tuple, Resolution | None] = {}

    def resolve(
        self, title: str, platform: str, *, episodic=False, year=None
    ) -> Resolution | None:
        title = clean_title(title)
        key = (title_key(title), platform, episodic, year)
        if key in self.cache:
            return self.cache[key]
        candidates = {item["id"]: item for item in self.imdb.search(title)}
        beta_matches = {}
        if self.beta:
            kinds = ("series", "movie")
            for kind in kinds:
                for summary in self.beta.search_titles(title, kind)[:8]:
                    names = (
                        summary.get("title", ""),
                        summary.get("original_title", ""),
                    )
                    if title_key(title) not in {
                        title_key(name) for name in names if name
                    }:
                        continue
                    details = self.beta.title_details(summary["id"], kind)
                    external_id = str(
                        details.get("imdb_id") or details.get("imdbId") or ""
                    )
                    if not re.fullmatch(r"tt\d+", external_id):
                        continue
                    # Exact external IDs connect localized titles; suggestions alone
                    # cannot establish availability on a streaming platform.
                    for item in self.imdb.search(external_id):
                        if item["id"] == external_id and imdb_kind(item) == kind:
                            candidates[external_id] = item
                            beta_matches[external_id] = details

        ranked = []
        for external_id, candidate in candidates.items():
            kind = imdb_kind(candidate)
            if year and candidate.get("y") != year:
                continue
            beta = beta_matches.get(external_id)
            exact = title_key(candidate.get("l", "")) == title_key(title)
            if not exact and beta is None:
                continue
            score = 10 + (3 if beta and platform_matches(beta, platform) else 0)
            if episodic and kind == "series":
                score += 4
            ranked.append((score, Resolution(candidate, kind, beta)))
        ranked.sort(key=lambda match: match[0], reverse=True)
        result = None
        if ranked and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
            result = ranked[0][1]
            if self.beta and not result.beta:
                details = self.beta.title_details(
                    result.imdb["id"], result.kind, imdb=True
                )
                external_id = details.get("imdb_id") or details.get("imdbId")
                if external_id == result.imdb["id"]:
                    result.beta = details
        self.cache[key] = result
        return result
