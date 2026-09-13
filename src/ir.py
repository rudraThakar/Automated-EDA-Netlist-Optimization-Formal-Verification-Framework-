from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class NetlistError(RuntimeError):
    """Raised for backend netlist issues."""


class NodeKind(str, Enum):
    PI = "pi"
    PO = "po"
    GATE = "gate"
    DFF = "dff"
    CONST = "const"


class GateType(str, Enum):
    AND = "and"
    OR = "or"
    NAND = "nand"
    NOR = "nor"
    NOT = "not"
    BUF = "buf"
    XOR = "xor"
    XNOR = "xnor"
    DFF = "dff"


COMB_GATES_2IN = {"and", "or", "nand", "nor", "xor", "xnor"}
COMB_GATES_1IN = {"buf", "not"}
SUPPORTED_GATES = {g.value for g in GateType}


@dataclass(slots=True)
class Net:
    name: str
    driver: Optional[str] = None
    sinks: List[str] = field(default_factory=list)
    is_input: bool = False
    is_output: bool = False
    is_const: bool = False


@dataclass(slots=True)
class Node:
    name: str
    kind: NodeKind
    gate_type: Optional[GateType] = None
    inputs: List[str] = field(default_factory=list)
    output: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)


class NetlistIR:
    """Deterministic internal graph representation for a flat gate-level netlist."""

    def __init__(self) -> None:
        self.module_name: Optional[str] = None
        self.inputs: List[str] = []
        self.outputs: List[str] = []
        self.nodes: Dict[str, Node] = {}
        self.nets: Dict[str, Net] = {}
        self.loaded_path: Optional[str] = None

    def clear(self) -> None:
        self.__init__()

    def ensure_net(self, name: str) -> Net:
        if name not in self.nets:
            self.nets[name] = Net(name=name)
        return self.nets[name]

    def add_input(self, name: str) -> None:
        net = self.ensure_net(name)
        net.is_input = True
        if name not in self.inputs:
            self.inputs.append(name)

    def add_output(self, name: str) -> None:
        net = self.ensure_net(name)
        net.is_output = True
        if name not in self.outputs:
            self.outputs.append(name)

    def add_gate(self, gate_type: str, inst_name: str, output_net: str, input_nets: Sequence[str]) -> None:
        gt = GateType(gate_type)
        if inst_name in self.nodes:
            raise NetlistError(f"Duplicate instance name: {inst_name}")
        node = Node(
            name=inst_name,
            kind=NodeKind.DFF if gt == GateType.DFF else NodeKind.GATE,
            gate_type=gt,
            inputs=list(input_nets),
            output=output_net,
        )
        self.nodes[inst_name] = node

        out = self.ensure_net(output_net)
        if out.driver is not None:
            raise NetlistError(f"Net '{output_net}' already has driver '{out.driver}'")
        out.driver = inst_name

        for net_name in input_nets:
            net = self.ensure_net(net_name)
            net.sinks.append(inst_name)

    def validate_basic(self) -> None:
        if self.module_name is None:
            raise NetlistError("No module loaded.")
        for name, node in self.nodes.items():
            if node.gate_type is None:
                raise NetlistError(f"Node '{name}' is missing gate_type.")
            if node.gate_type.value in COMB_GATES_2IN and len(node.inputs) != 2:
                raise NetlistError(f"Gate '{name}' must have exactly 2 inputs.")
            if node.gate_type.value in COMB_GATES_1IN and len(node.inputs) != 1:
                raise NetlistError(f"Gate '{name}' must have exactly 1 input.")
