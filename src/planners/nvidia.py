from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from planners.base import BasePlanner


class NvidiaPlanner(BasePlanner):
    """
    NVIDIA NIM planner adapter.

    NVIDIA's hosted NIM API is OpenAI-compatible. This adapter uses Chat
    Completions only to emit one strict JSON tool call; execution remains in the
    deterministic backend after schema validation.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        schema: Dict[str, Any],
        base_url: str = "https://integrate.api.nvidia.com/v1",
        temperature: float = 0.0,
        max_output_tokens: int = 1024,
        timeout_sec: int = 25,
        fallback: Optional[BasePlanner] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.schema = schema
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_sec = timeout_sec
        self.fallback = fallback

        self.last_used: str = "not_called"
        self.last_error: Optional[str] = None
        self.last_raw_response: Optional[str] = None

    def plan(self, user_request: str) -> str:
        self.last_error = None
        self.last_raw_response = None

        if not self.api_key:
            self.last_used = "heuristic_fallback_no_api_key"
            self.last_error = "NVIDIA API key is missing. Set NVIDIA_API_KEY or nvidia.api_key in config."
            if self.fallback:
                return self.fallback.plan(user_request)
            raise RuntimeError(self.last_error)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": user_request},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
            "extra_body": {
                "chat_template_kwargs": {
                    "enable_thinking": False,
                    "force_nonempty_content": True,
                }
            },
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = self._extract_text(data)
            self.last_used = "nvidia"
            self.last_raw_response = text
            return text
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            self.last_used = "heuristic_fallback_after_nvidia_error"
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self.fallback:
                return self.fallback.plan(user_request)
            raise RuntimeError(f"NVIDIA planner failed: {exc}") from exc

    def _system_prompt(self) -> str:
        tool_specs = json.dumps(self.schema["tool_specs"], indent=2, sort_keys=True)
        allowed = json.dumps(self.schema["properties"]["tool"]["enum"])
        return f"""
You are a planner for VeriFlow, a gate-level Verilog EDA automation tool.

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
""".strip()

    @staticmethod
    def _extract_text(data: Dict[str, Any]) -> str:
        choices = data.get("choices", [])
        if not choices:
            raise KeyError("No NVIDIA choices returned")
        message = choices[0].get("message", {})
        text = message.get("content", "")
        if not text:
            raise KeyError("No NVIDIA message content returned")
        return text
