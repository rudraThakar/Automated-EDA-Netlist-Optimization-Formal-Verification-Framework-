from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from planners.base import BasePlanner
from planners.gemini import GeminiPlanner
from planners.heuristic import HeuristicBootstrapPlanner
from planners.nvidia import NvidiaPlanner
from schema import STRICT_TOOL_SCHEMA


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ICCAD 2026 Problem A solver")
    parser.add_argument("-config", "--config", dest="config", default=None, help="LLM config file path")
    parser.add_argument("--no-llm", action="store_true", help="Force deterministic heuristic planner")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print planner/tool/debug information to stderr without breaking stdout protocol",
    )
    parser.add_argument(
        "--require-llm",
        action="store_true",
        help="Fail loudly instead of falling back to the heuristic planner when LLM setup/call fails",
    )
    parser.add_argument(
        "--verification-policy",
        choices=["strict", "permissive", "dry_run"],
        default=None,
        help="Transformation commit policy: strict requires proven equivalence, permissive allows inconclusive checks, dry_run never commits edits",
    )
    return parser.parse_args(argv)


def load_config(path: Optional[str]) -> Dict[str, Any]:
    load_dotenv()
    if not path:
        return {"provider": "heuristic"}
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    text = cfg_path.read_text(encoding="utf-8")
    if cfg_path.suffix.lower() == ".json":
        return json.loads(text)
    return _parse_simple_yaml(text)


def load_dotenv(path: str = ".env") -> None:
    """Load simple KEY=VALUE entries from a local .env file without overriding env vars."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def make_planner_from_config(
    config: Dict[str, Any],
    no_llm: bool = False,
    require_llm: bool = False,
) -> BasePlanner:
    fallback = HeuristicBootstrapPlanner()

    if no_llm:
        return fallback

    provider = str(config.get("provider", "heuristic")).lower()
    generation = config.get("generation", {}) if isinstance(config.get("generation", {}), dict) else {}
    temperature = float(generation.get("temperature", 0.2))
    max_output_tokens = int(generation.get("max_output_tokens", 1024))

    if provider == "gemini":
        gemini = config.get("gemini", {}) if isinstance(config.get("gemini", {}), dict) else {}
        api_key = str(gemini.get("api_key") or os.environ.get("GEMINI_API_KEY", ""))
        model = str(gemini.get("model", "gemini-2.5-flash"))
        timeout_sec = int(gemini.get("timeout_sec", 25))

        return GeminiPlanner(
            api_key=api_key,
            model=model,
            schema=STRICT_TOOL_SCHEMA,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_sec=timeout_sec,
            fallback=None if require_llm else fallback,
        )

    if provider == "nvidia":
        nvidia = config.get("nvidia", {}) if isinstance(config.get("nvidia", {}), dict) else {}
        api_key = str(nvidia.get("api_key") or os.environ.get("NVIDIA_API_KEY", ""))
        model = str(nvidia.get("model", "nvidia/nemotron-3-super-120b-a12b"))
        base_url = str(nvidia.get("base_url", "https://integrate.api.nvidia.com/v1"))
        timeout_sec = int(nvidia.get("timeout_sec", 25))

        return NvidiaPlanner(
            api_key=api_key,
            model=model,
            base_url=base_url,
            schema=STRICT_TOOL_SCHEMA,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_sec=timeout_sec,
            fallback=None if require_llm else fallback,
        )

    if require_llm:
        raise RuntimeError(f"Requested --require-llm, but unsupported provider: {provider}")

    # Official OpenAI/Anthropic adapters can be added later using the same BasePlanner API.
    return fallback


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """
    Tiny YAML subset parser for simple contest configs.
    Supports top-level scalars and one-level nested maps, e.g.:
      provider: "gemini"
      gemini:
        api_key: "..."
        model: "gemini-2.5-flash"
    """
    root: Dict[str, Any] = {}
    current_section: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()

        if indent == 0:
            if value == "":
                root[key] = {}
                current_section = key
            else:
                root[key] = _coerce_scalar(value)
                current_section = None
        else:
            if current_section is None:
                continue
            section = root.setdefault(current_section, {})
            if isinstance(section, dict):
                section[key] = _coerce_scalar(value)
    return root


def _coerce_scalar(value: str) -> Any:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value
