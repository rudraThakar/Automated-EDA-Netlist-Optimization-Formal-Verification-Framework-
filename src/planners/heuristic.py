from __future__ import annotations

import re

from planners.base import BasePlanner
from utils import stable_json_dumps


READ_NETLIST_RE = re.compile(
    r"(?:read|load).*?(?:design\s+(?:in\s+)?from\s+|file\s+|from\s+)?[\"'`]?(?P<path>[A-Za-z0-9_\-./\\]+\.v)[\"'`]?(?:[\s.,;]|$)",
    re.IGNORECASE,
)
WRITE_NETLIST_RE = re.compile(
    r"(?:write|output).*?(?:current\s+design\s+to|design\s+(?:as|to)|netlist\s+(?:as|to)|to|into)\s+[\"'`]?(?P<path>[A-Za-z0-9_\-./\\]+\.v)[\"'`]?(?:[\s.,;]|$)",
    re.IGNORECASE,
)


class HeuristicBootstrapPlanner(BasePlanner):
    """Deterministic fallback planner so the scaffold works without an LLM/API key."""

    def plan(self, user_request: str) -> str:
        req = user_request.strip()

        m = READ_NETLIST_RE.search(req)
        if m:
            return stable_json_dumps({"tool": "read_netlist", "arguments": {"path": m.group("path")}})

        m = WRITE_NETLIST_RE.search(req)
        if m:
            return stable_json_dumps({"tool": "write_netlist", "arguments": {"path": m.group("path")}})

        low = req.lower()
        if "fanout" in low:
            # Check for "check max fanout" first
            if "check" in low and "max" in low:
                # Extract max fanout number, default to 8 if not specified
                fanout_match = re.search(r"fanout\s*(?:<=|≤|less\s+than\s+or\s+equal\s+to)?\s*(\d+)", req, re.I)
                max_fanout = int(fanout_match.group(1)) if fanout_match else 8
                return stable_json_dumps({"tool": "check_max_fanout", "arguments": {"max_fanout": max_fanout}})
            else:
                # Regular fanout query
                token = self._extract_quoted_or_last_identifier(req)
                return stable_json_dumps({"tool": "get_fanout", "arguments": {"node_or_net": token}})

        if ("insert" in low or "add" in low) and "and" in low and ("before" in low or "buffer" in low):
            # Look for pattern like "_gc__" and control signal like "_gc_ctrl"
            pattern_match = re.search(r"buffers?\s+(?:whose\s+)?(?:name\s+)?(?:includes?|matches?)\s+[\"'`]?([^\"'`\s]+)[\"'`]?", req, re.I)
            control_match = re.search(r"(?:connect|with)\s+(?:the\s+)?(?:other\s+)?(?:input\s+)?(?:to\s+)?[\"'`]?([A-Za-z_][A-Za-z0-9_$]*)[\"'`]?", req, re.I)
            if pattern_match and control_match:
                return stable_json_dumps({
                    "tool": "insert_and_before_buffers",
                    "arguments": {
                        "pattern": pattern_match.group(1),
                        "control_signal": control_match.group(1)
                    }
                })

        if "optimize" in low and "cone" in low:
            # Extract output signal and constraints
            output_match = re.search(r"cone\s+(?:of\s+)?[\"'`]?([A-Za-z_][A-Za-z0-9_$]*)[\"'`]?", req, re.I)
            depth_match = re.search(r"(?:maximum|max(?:imum)?)\s+(?:logic\s+)?depth\s+(?:is\s+)?(?:<=|≤|less\s+than\s+(?:or\s+equal\s+to)?)\s*(\d+)", req, re.I)
            minimize_match = re.search(r"(?:minimiz|reduc)\w+", req, re.I)
            if output_match:
                args = {"output_signal": output_match.group(1)}
                if depth_match:
                    args["max_depth"] = int(depth_match.group(1))
                if minimize_match:
                    args["minimize_gates"] = True
                return stable_json_dumps({"tool": "optimize_cone", "arguments": args})

        if ("replace" in low or "convert" in low) and ("gates" in low or "gate" in low):
            # Extract from_gate and to_gate
            from_match = re.search(r"replace\s+(?:all\s+)?([a-z]+(?:\s+gates?)?)", req, re.I)
            to_match = re.search(r"with\s+(?:equivalent\s+)?(?:logic\s+)?(?:built\s+)?(?:only\s+)?(?:from\s+)?([a-z]+(?:\s+and\s+[a-z]+)?)", req, re.I)
            if from_match and to_match:
                from_gate = from_match.group(1).strip()
                to_gate = to_match.group(1).strip()
                return stable_json_dumps({
                    "tool": "replace_gates",
                    "arguments": {"from_gate": from_gate, "to_gate": to_gate}
                })

        if "check" in low and "equivalence" in low:
            return stable_json_dumps({"tool": "check_equivalence", "arguments": {}})

        return stable_json_dumps({"tool": "unknown_tool", "arguments": {"request": user_request}})

    @staticmethod
    def _extract_quoted_or_last_identifier(text: str) -> str:
        quoted = re.findall(r"[\"'`]([A-Za-z_][A-Za-z0-9_$]*)[\"'`]", text)
        if quoted:
            return quoted[-1]
        ids = re.findall(r"\b([A-Za-z_][A-Za-z0-9_$]*)\b", text)
        ids = HeuristicBootstrapPlanner._drop_common_words(ids)
        return ids[-1] if ids else ""

    @staticmethod
    def _extract_signal_names(text: str):
        quoted = re.findall(r"[\"'`]([A-Za-z_][A-Za-z0-9_$]*)[\"'`]", text)
        if len(quoted) >= 2:
            return quoted
        m = re.search(r"from\s+([A-Za-z_][A-Za-z0-9_$]*)\s+to\s+([A-Za-z_][A-Za-z0-9_$]*)", text, re.I)
        if m:
            return [m.group(1), m.group(2)]
        return re.findall(r"\b([A-Za-z_][A-Za-z0-9_$]*)\b", text)

    @staticmethod
    def _drop_common_words(words):
        stop = {
            "what", "is", "the", "maximum", "logic", "depth", "from", "input", "to",
            "output", "find", "path", "that", "does", "not", "pass", "through", "node",
            "fanout", "of", "net", "instance", "write", "read", "design", "current",
        }
        return [w for w in words if w.lower() not in stop]
