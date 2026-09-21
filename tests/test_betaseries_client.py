from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import httpx

from ingestion.betaseries_client import BetaSeriesClient


class _HTTPClient:
    responses: list[object] = []
    calls = 0

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self) -> "_HTTPClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get(self, *args, **kwargs):
        type(self).calls += 1
        response = type(self).responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("GET", "https://api.betaseries.com/test"),
    )


class BetaSeriesClientTest(unittest.TestCase):
    def setUp(self) -> None:
        _HTTPClient.responses = []
        _HTTPClient.calls = 0

    def test_fetch_calendar_retries_transient_timeout(self) -> None:
        _HTTPClient.responses = [
            httpx.ReadTimeout("slow"),
            _response(200, {"episodes": [{"id": 1}]}),
        ]
        client = BetaSeriesClient(
            api_key="key",
            access_token="token",
            db=Mock(),
            member_id=123,
        )

        with patch("ingestion.betaseries_client.httpx.Client", _HTTPClient):
            with patch("ingestion.betaseries_client.time.sleep"):
                episodes = client.fetch_calendar()

        self.assertEqual(episodes, [{"id": 1}])
        self.assertEqual(_HTTPClient.calls, 2)

    def test_fetch_calendar_raises_after_retries(self) -> None:
        _HTTPClient.responses = [
            httpx.ReadTimeout("slow"),
            httpx.ReadTimeout("still slow"),
            httpx.ReadTimeout("down"),
        ]
        client = BetaSeriesClient(
            api_key="key",
            access_token="token",
            db=Mock(),
            member_id=123,
        )

        with patch("ingestion.betaseries_client.httpx.Client", _HTTPClient):
            with patch("ingestion.betaseries_client.time.sleep"):
                with self.assertRaises(RuntimeError):
                    client.fetch_calendar()

        self.assertEqual(_HTTPClient.calls, 3)


if __name__ == "__main__":
    unittest.main()
