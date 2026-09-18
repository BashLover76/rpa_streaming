from __future__ import annotations

import argparse
import logging
from pathlib import Path

import httpx

from ingestion.ollama_client import OllamaClient
from ingestion.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test Ollama without writing streaming data"
    )
    parser.add_argument("--image", type=Path, help="Optional screenshot to test vision")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    print(f"Endpoint: {settings.ollama_base_url}; model: {settings.ollama_model}")
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
        response.raise_for_status()
        models = [item["name"] for item in response.json().get("models", [])]
    if settings.ollama_model not in models:
        raise SystemExit(f"Model not installed: ollama pull {settings.ollama_model}")
    ollama = OllamaClient(
        settings.ollama_base_url,
        settings.ollama_model,
        settings.ollama_timeout,
        num_ctx=settings.ollama_num_ctx,
        num_predict=settings.ollama_num_predict,
    )
    schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }
    result = ollama.json_chat(
        prompt='Return JSON with key text set to "OK".', schema=schema, max_tokens=128
    )
    if result != {"text": "OK"}:
        raise SystemExit(f"Unexpected text response: {result!r}")
    print("Text + JSON test: OK")
    if args.image:
        result = ollama.json_chat(
            prompt="Read the main title of this screenshot into the JSON key text. Use an empty string if unreadable.",
            schema=schema,
            image_paths=[args.image],
            max_tokens=256,
        )
        print(f"Vision result (check visually): {result!r}")


if __name__ == "__main__":
    main()
