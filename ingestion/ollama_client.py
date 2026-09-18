from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 300.0,
        *,
        num_ctx: int = 32768,
        num_predict: int = 4096,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.num_predict = num_predict

    def chat(
        self,
        *,
        prompt: str,
        system: str | None = None,
        image_paths: list[Path] | None = None,
        json_mode: bool = False,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        images = []
        for image_path in image_paths or []:
            images.append(base64.b64encode(image_path.read_bytes()).decode("ascii"))

        message: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            message["images"] = images

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append(message)

        with httpx.Client(timeout=self.timeout) as client:
            request: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": 0.1,
                    "num_ctx": self.num_ctx,
                    "num_predict": max_tokens or self.num_predict,
                    "repeat_penalty": 1.15,
                    "repeat_last_n": 256,
                },
            }
            if json_mode:
                request["format"] = schema or "json"
            LOGGER.info(
                "Ollama request model=%s context=%s output=%s images=%s",
                self.model,
                self.num_ctx,
                request["options"]["num_predict"],
                len(images),
            )
            parts = []
            final: dict[str, Any] = {}
            with client.stream(
                "POST", f"{self.base_url}/api/chat", json=request
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    raise RuntimeError(
                        f"Ollama HTTP {response.status_code}, model={self.model}: {response.text[:500]}"
                    )
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    if payload.get("error"):
                        raise RuntimeError(
                            f"Ollama model {self.model}: {payload['error']}"
                        )
                    final = payload
                    parts.append(payload.get("message", {}).get("content", ""))
                    # Stop at a complete JSON value; avoid trailing repetition loops.
                    if json_mode:
                        try:
                            json.loads("".join(parts))
                        except json.JSONDecodeError:
                            pass
                        else:
                            final = {
                                **payload,
                                "done": True,
                                "done_reason": "json_complete",
                            }
                            break
                    if payload.get("done"):
                        break
            LOGGER.info(
                "Ollama response model=%s reason=%s prompt_tokens=%s generated_tokens=%s",
                self.model,
                final.get("done_reason"),
                final.get("prompt_eval_count"),
                final.get("eval_count"),
            )
            if final.get("done_reason") == "length":
                raise ValueError(
                    "Ollama output truncated; reduce batch size or increase OLLAMA_NUM_PREDICT"
                )
            if final.get("done") is False:
                raise ValueError(
                    "Ollama connection ended before the final message; check the service or API proxy"
                )
            result = "".join(parts).strip()
            if not result:
                raise ValueError(
                    f"Ollama model {self.model} returned empty content (reason={final.get('done_reason')})"
                )
            return result

    def json_chat(
        self,
        *,
        prompt: str,
        system: str | None = None,
        image_paths: list[Path] | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        raw = self.chat(
            prompt=prompt,
            system=system,
            image_paths=image_paths,
            json_mode=True,
            schema=schema,
            max_tokens=max_tokens,
        )
        try:
            return json.loads(_strip_code_fences(raw))
        except json.JSONDecodeError:
            LOGGER.warning(
                "Ollama returned invalid JSON; retrying with the same schema: %s",
                raw[:500],
            )
            retry_prompt = f"{prompt}\n\nIMPORTANT: return one valid JSON value only, with no explanation or Markdown."
            retry_raw = self.chat(
                prompt=retry_prompt,
                system=system,
                image_paths=image_paths,
                json_mode=True,
                schema=schema,
                max_tokens=max_tokens,
            )
            try:
                return json.loads(_strip_code_fences(retry_raw))
            except json.JSONDecodeError:
                LOGGER.warning(
                    "Ollama returned non-JSON output after retry: %s", retry_raw[:500]
                )
                raise ValueError(
                    "Ollama did not return valid JSON after two attempts. "
                    f"Raw response: {retry_raw[:500]!r}"
                ) from None


def _strip_code_fences(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1]
    if stripped.endswith("```"):
        stripped = stripped.rsplit("\n", 1)[0]
    if stripped.startswith("json\n"):
        stripped = stripped[5:]
    return stripped.strip()
