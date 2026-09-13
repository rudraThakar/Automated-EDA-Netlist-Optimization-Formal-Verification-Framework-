from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from planners.base import BasePlanner


class GeminiPlanner(BasePlanner):
    """
    Gemini planner adapter.

    Gemini is only used to emit a JSON tool call. Execution remains in the
    deterministic backend after schema validation.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        schema: Dict[str, Any],
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        timeout_sec: int = 25,
        fallback: Optional[BasePlanner] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.schema = schema
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_sec = timeout_sec
        self.fallback = fallback

        # Debug state read by ICCADApp when --debug is enabled.
        self.last_used: str = "not_called"
        self.last_error: Optional[str] = None
        self.last_raw_response: Optional[str] = None

    def plan(self, user_request: str) -> str:
        self.last_error = None
        self.last_raw_response = None

        if not self.api_key:
            self.last_used = "heuristic_fallback_no_api_key"
            self.last_error = "Gemini API key is missing. Set GEMINI_API_KEY or gemini.api_key in config."
            if self.fallback:
                return self.fallback.plan(user_request)
            raise RuntimeError(self.last_error)

        prompt = self._build_prompt(user_request)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = self._extract_text(data)
            self.last_used = "gemini"
            self.last_raw_response = text
            return text
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            self.last_used = "heuristic_fallback_after_gemini_error"
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self.fallback:
                return self.fallback.plan(user_request)
            raise RuntimeError(f"Gemini planner failed: {exc}") from exc

    def _build_prompt(self, user_request: str) -> str:
        tool_specs = json.dumps(self.schema["tool_specs"], indent=2, sort_keys=True)
        allowed = json.dumps(self.schema["properties"]["tool"]["enum"])
        return f"""
You are a planner for an ICCAD 2026 gate-level netlist tool.

Return only one valid JSON object.
Do not include markdown.
Do not explain.

Required output shape:
{{"tool":"<allowed tool>","arguments":{{...}}}}

Allowed tools:
{allowed}

Tool argument specifications:
{tool_specs}

Rules:
- Choose exactly one tool.
- Do not invent tools.
- Do not invent signal names.
- Use only signal names, net names, instance names, and paths mentioned by the user.
- For read requests, return read_netlist.
- For write/output requests, return write_netlist.
- If the request asks to check external tools, return check_external_tools.
- If the request is unsupported, choose the closest supported tool only when safe.

User request:
{user_request}
""".strip()

    @staticmethod
    def _extract_text(data: Dict[str, Any]) -> str:
        candidates = data.get("candidates", [])
        if not candidates:
            raise KeyError("No Gemini candidates returned")
        parts = candidates[0]["content"].get("parts", [])
        if not parts:
            raise KeyError("No Gemini text parts returned")
        return parts[0].get("text", "")
