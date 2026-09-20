from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class OperationRoute:
    backend: str
    description: str


class BackendRouter:
    """Declarative map from high-level operations to backend responsibility."""

    def __init__(self) -> None:
        self.routes: Dict[str, OperationRoute] = {
            "read_netlist": OperationRoute("python_parser+yosys_json", "Parse Verilog into NetlistIR"),
            "write_netlist": OperationRoute("python_writer", "Render current NetlistIR to Verilog"),
            "get_fanout": OperationRoute("python_graph", "Inspect sinks in NetlistIR"),
            "get_max_depth": OperationRoute("python_graph", "Compute longest combinational path"),
            "find_path": OperationRoute("python_graph", "Find a reachable signal path"),
            "check_max_fanout": OperationRoute("python_graph", "Scan fanout constraints"),
            "remove_dangling_logic": OperationRoute("yosys_clean+python_fallback", "Clean unused logic with Yosys, fallback to graph sweep"),
            "normalize_design": OperationRoute("yosys", "Normalize and rewrite Verilog"),
            "check_equivalence": OperationRoute("yosys+abc", "Export BLIF with Yosys and prove miter with ABC"),
            "optimize_cone": OperationRoute("abc/yosys", "Attempt optimization through backend EDA tools"),
            "insert_and_before_buffers": OperationRoute("python_edit+yosys+abc", "Apply structural edit then verify"),
            "replace_gates": OperationRoute("python_edit+yosys+abc", "Apply structural edit then verify"),
            "clean_dangling_and_write": OperationRoute("workflow", "Read design, clean dangling logic, and write output"),
        }

    def describe(self) -> Dict[str, Dict[str, str]]:
        return {
            name: {"backend": route.backend, "description": route.description}
            for name, route in sorted(self.routes.items())
        }
