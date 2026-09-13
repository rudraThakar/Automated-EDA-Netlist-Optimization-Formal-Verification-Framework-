from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class ValidationError(RuntimeError):
    """Raised when JSON tool calls violate schema or safety constraints."""


class ToolName(str, Enum):
    READ_NETLIST = "read_netlist"
    WRITE_NETLIST = "write_netlist"
    GET_FANOUT = "get_fanout"
    GET_MAX_DEPTH = "get_max_depth"
    FIND_PATH = "find_path"
    REMOVE_DANGLING_LOGIC = "remove_dangling_logic"
    CHECK_EXTERNAL_TOOLS = "check_external_tools"
    # New tools for transformations and verification
    NORMALIZE_DESIGN = "normalize_design"
    CHECK_EQUIVALENCE = "check_equivalence"
    CHECK_MAX_FANOUT = "check_max_fanout"
    INSERT_AND_BEFORE_BUFFERS = "insert_and_before_buffers"
    OPTIMIZE_CONE = "optimize_cone"
    REPLACE_GATES = "replace_gates"


STRICT_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["tool", "arguments"],
    "additionalProperties": False,
    "properties": {
        "tool": {"type": "string", "enum": [tool.value for tool in ToolName]},
        "arguments": {"type": "object"},
    },
    "tool_specs": {
        "read_netlist": {
            "required": ["path"],
            "additionalProperties": False,
            "properties": {"path": {"type": "string", "minLength": 1}},
        },
        "write_netlist": {
            "required": ["path"],
            "additionalProperties": False,
            "properties": {"path": {"type": "string", "minLength": 1}},
        },
        "get_fanout": {
            "required": ["node_or_net"],
            "additionalProperties": False,
            "properties": {"node_or_net": {"type": "string", "minLength": 1}},
        },
        "get_max_depth": {
            "required": ["source", "sink"],
            "additionalProperties": False,
            "properties": {
                "source": {"type": "string", "minLength": 1},
                "sink": {"type": "string", "minLength": 1},
            },
        },
        "find_path": {
            "required": ["source", "sink"],
            "additionalProperties": False,
            "properties": {
                "source": {"type": "string", "minLength": 1},
                "sink": {"type": "string", "minLength": 1},
                "avoid": {"type": "string", "minLength": 1},
            },
        },
        "remove_dangling_logic": {
            "required": [],
            "additionalProperties": False,
            "properties": {},
        },
        "check_external_tools": {
            "required": [],
            "additionalProperties": False,
            "properties": {},
        },
        "normalize_design": {
            "required": [],
            "additionalProperties": False,
            "properties": {},
        },
        "check_equivalence": {
            "required": [],
            "additionalProperties": False,
            "properties": {},
        },
        "check_max_fanout": {
            "required": ["max_fanout"],
            "additionalProperties": False,
            "properties": {"max_fanout": {"type": "integer", "minimum": 1}},
        },
        "insert_and_before_buffers": {
            "required": ["pattern", "control_signal"],
            "additionalProperties": False,
            "properties": {
                "pattern": {"type": "string", "minLength": 1},
                "control_signal": {"type": "string", "minLength": 1},
            },
        },
        "optimize_cone": {
            "required": ["output_signal"],
            "additionalProperties": False,
            "properties": {
                "output_signal": {"type": "string", "minLength": 1},
                "max_depth": {"type": "integer", "minimum": 1},
                "minimize_gates": {"type": "boolean"},
            },
        },
        "replace_gates": {
            "required": ["from_gate", "to_gate"],
            "additionalProperties": False,
            "properties": {
                "from_gate": {"type": "string", "minLength": 1},
                "to_gate": {"type": "string", "minLength": 1},
                "pattern": {"type": "string"},
            },
        },
    },
}


@dataclass(frozen=True)
class ToolCall:
    tool: ToolName
    arguments: Dict[str, Any]


@dataclass
class ValidationResult:
    ok: bool
    tool_call: Optional[ToolCall] = None
    clarification: Optional[str] = None
    error: Optional[str] = None


class ToolCallValidator:
    """Strict standard-library validator for LLM-generated JSON tool calls."""

    def __init__(self, schema: Dict[str, Any]) -> None:
        self.schema = schema

    def parse_llm_json(self, raw_text: str) -> ValidationResult:
        cleaned = self._extract_json_object(raw_text)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return self._clarification(
                f"Malformed JSON from planner: {exc.msg} at position {exc.pos}."
            )
        return self.validate_payload(payload)

    def validate_payload(self, payload: Any) -> ValidationResult:
        if not isinstance(payload, dict):
            return self._clarification("Planner output must be a JSON object.")

        required = set(self.schema["required"])
        actual = set(payload.keys())
        missing = required - actual
        extra = actual - set(self.schema["properties"].keys())
        if missing:
            return self._clarification(f"Missing top-level fields: {sorted(missing)}.")
        if extra:
            return self._clarification(f"Unexpected top-level fields: {sorted(extra)}.")

        tool_raw = payload.get("tool")
        args = payload.get("arguments")

        if tool_raw not in self.schema["properties"]["tool"]["enum"]:
            return self._clarification(
                f"Unsupported tool '{tool_raw}'. Allowed tools: {self.schema['properties']['tool']['enum']}."
            )
        if not isinstance(args, dict):
            return self._clarification("'arguments' must be a JSON object.")

        tool_spec = self.schema["tool_specs"][tool_raw]
        required_args = set(tool_spec["required"])
        actual_args = set(args.keys())
        missing_args = required_args - actual_args
        extra_args = actual_args - set(tool_spec["properties"].keys())
        if missing_args:
            return self._clarification(
                f"Tool '{tool_raw}' is missing required arguments: {sorted(missing_args)}."
            )
        if extra_args:
            return self._clarification(
                f"Tool '{tool_raw}' received unexpected arguments: {sorted(extra_args)}."
            )

        for arg_name, arg_spec in tool_spec["properties"].items():
            if arg_name not in args:
                continue
            value = args[arg_name]
            if arg_spec["type"] == "string":
                if not isinstance(value, str):
                    return self._clarification(
                        f"Argument '{arg_name}' for tool '{tool_raw}' must be a string."
                    )
                if len(value.strip()) < arg_spec.get("minLength", 0):
                    return self._clarification(
                        f"Argument '{arg_name}' for tool '{tool_raw}' cannot be empty."
                    )

        return ValidationResult(ok=True, tool_call=ToolCall(tool=ToolName(tool_raw), arguments=args))

    @staticmethod
    def _extract_json_object(raw_text: str) -> str:
        """Accept pure JSON, or a model response that accidentally wraps JSON in text/fences."""
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        if text.startswith("{") and text.endswith("}"):
            return text
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start : end + 1]
        return text

    def _clarification(self, msg: str) -> ValidationResult:
        clarification = (
            "I could not safely execute the requested operation because the planner output "
            f"was invalid. Please restate the request clearly. Details: {msg}"
        )
        return ValidationResult(ok=False, clarification=clarification, error=msg)
