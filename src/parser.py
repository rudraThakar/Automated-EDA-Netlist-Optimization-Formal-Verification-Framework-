from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from ir import NetlistError, NetlistIR


class GateLevelVerilogParser:
    """Restricted parser for the contest-aligned Day 1 gate-level subset."""

    MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\s*\((.*?)\)\s*;", re.S)
    DECL_RE = re.compile(r"\b(input|output|wire)\b\s*(?:\[[^\]]+\]\s*)?([^;]+);", re.I)
    INST_RE = re.compile(
        r"\b(and|or|nand|nor|not|buf|xor|xnor|dff)\b\s+([A-Za-z_][A-Za-z0-9_$]*)\s*\((.*?)\)\s*;",
        re.I | re.S,
    )
    # Continuous assignment pattern: assign lhs = expression;
    ASSIGN_RE = re.compile(
        r"\bassign\s+([A-Za-z_][A-Za-z0-9_$]*)\s*=\s*(.+?)\s*;",
        re.I | re.S
    )

    @staticmethod
    def _split_csv(raw: str) -> List[str]:
        return [part.strip() for part in raw.split(",") if part.strip()]

    def parse_file(self, path: str) -> NetlistIR:
        text = Path(path).read_text(encoding="utf-8")
        return self.parse_text(text, loaded_path=path)

    def parse_text(self, text: str, loaded_path: Optional[str] = None) -> NetlistIR:
        ir = NetlistIR()
        ir.loaded_path = loaded_path

        text_wo_comments = re.sub(r"//.*?$", "", text, flags=re.M)
        module_match = self.MODULE_RE.search(text_wo_comments)
        if not module_match:
            raise NetlistError("Could not parse module header.")
        ir.module_name = module_match.group(1)
        
        # Extract the port list from module header (group 2)
        ports_str = module_match.group(2).strip()
        
        # Extract the content AFTER the module header (after the closing paren and semicolon)
        module_start = module_match.end()
        module_body = text_wo_comments[module_start:]

        # IMPORTANT: Parse declarations in module body FIRST to get authoritative types
        # This handles both Yosys output (which has separate declarations) and standard Verilog
        for decl_kind, names_blob in self.DECL_RE.findall(module_body):
            names = self._split_csv(names_blob)
            for name in names:
                token = name.split()[-1]
                if decl_kind.lower() == "input":
                    ir.add_input(token)
                elif decl_kind.lower() == "output":
                    ir.add_output(token)
                else:
                    ir.ensure_net(token)

        # Now parse ports from module header (but don't override body declarations)
        # This handles inline port declarations like: module foo(input a, b, output y)
        if ports_str and re.search(r'\b(input|output|inout|wire)\b', ports_str):
            # Inline declarations: parse them (but they should match body declarations)
            for decl_kind, names_blob in self.DECL_RE.findall(ports_str + ";"):
                names = self._split_csv(names_blob)
                for name in names:
                    token = name.split()[-1]
                    if decl_kind.lower() == "input" and token not in ir.inputs:
                        ir.add_input(token)
                    elif decl_kind.lower() == "output" and token not in ir.outputs:
                        ir.add_output(token)
                    elif decl_kind.lower() == "inout" and token not in ir.inputs:
                        ir.add_input(token)  # Treat inout as input
                    elif token not in ir.inputs and token not in ir.outputs and token not in [n.name for n in ir.nets.values()]:
                        ir.ensure_net(token)
        elif ports_str:
            # Port names without inline types - ensure they exist as nets (will be typed by body declarations)
            port_names = self._split_csv(ports_str)
            for port_name in port_names:
                token = port_name.split()[-1]
                if token not in ir.inputs and token not in ir.outputs:
                    ir.ensure_net(token)

        for gate_type, inst_name, pins_blob in self.INST_RE.findall(module_body):
            pins = self._split_csv(pins_blob)
            g = gate_type.lower()
            if g in {"and", "or", "nand", "nor", "xor", "xnor"}:
                if len(pins) != 3:
                    raise NetlistError(f"Gate instance '{inst_name}' of type '{gate_type}' must have 3 positional pins.")
                output_net, in1, in2 = pins
                ir.add_gate(g, inst_name, output_net, [in1, in2])
            elif g in {"buf", "not"}:
                if len(pins) != 2:
                    raise NetlistError(f"Gate instance '{inst_name}' of type '{gate_type}' must have 2 positional pins.")
                output_net, in1 = pins
                ir.add_gate(g, inst_name, output_net, [in1])
            elif g == "dff":
                if len(pins) < 2:
                    raise NetlistError(f"DFF instance '{inst_name}' has insufficient pins.")
                output_net = pins[0]
                d_input = pins[1]
                extras = pins[2:]
                ir.add_gate("dff", inst_name, output_net, [d_input] + extras)
            else:
                raise NetlistError(f"Unsupported primitive: {gate_type}")

        # Parse continuous assignments and convert to gate operations
        assign_counter = 0
        for lhs, rhs in self.ASSIGN_RE.findall(module_body):
            lhs = lhs.strip()
            rhs = rhs.strip()
            # Convert logical expressions to gate instantiations
            self._parse_assign_expression(ir, lhs, rhs, assign_counter)
            assign_counter += 1

        ir.validate_basic()
        return ir

    def _parse_assign_expression(self, ir: NetlistIR, output_net: str, expr: str, counter: int) -> None:
        """Convert a logical expression into gate operations."""
        expr = expr.strip()
        
        # Ensure output net exists
        ir.ensure_net(output_net)
        
        # Simple cases: direct assignment or single gate
        # assign y = a;  (direct assignment, or use buf)
        if self._is_single_identifier(expr):
            inst_name = f"buf_assign_{counter}"
            ir.add_gate("buf", inst_name, output_net, [expr])
            return
        
        # assign y = ~a;  (NOT gate)
        if self._matches_not(expr):
            inner = self._extract_not_operand(expr)
            inst_name = f"not_assign_{counter}"
            ir.add_gate("not", inst_name, output_net, [inner])
            return
        
        # Recursively handle binary operations: AND, OR, XOR, NAND, NOR, XNOR
        self._parse_binary_expr(ir, output_net, expr, counter)

    def _is_single_identifier(self, expr: str) -> bool:
        """Check if expression is a single identifier."""
        return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", expr))

    def _matches_not(self, expr: str) -> bool:
        """Check if expression is a NOT operation."""
        return bool(re.match(r"^\s*~\s*[A-Za-z_][A-Za-z0-9_$]*\s*$", expr))

    def _extract_not_operand(self, expr: str) -> str:
        """Extract operand from NOT expression."""
        return re.sub(r"^\s*~\s*|\s*$", "", expr)

    def _parse_binary_expr(self, ir: NetlistIR, output_net: str, expr: str, counter: int) -> None:
        """Parse binary operations and create gates."""
        # Try to identify the operator and split operands
        # Patterns: a & b, a | b, a ^ b, ~(a & b), ~(a | b), ~(a ^ b)
        
        # Handle negated operations: ~(...)
        negated = False
        inner_expr = expr
        if expr.startswith("~"):
            negated = True
            inner_expr = expr[1:].strip()
            if inner_expr.startswith("(") and inner_expr.endswith(")"):
                inner_expr = inner_expr[1:-1].strip()
        
        # Try AND operator
        if " & " in inner_expr or "& " in inner_expr or " &" in inner_expr:
            parts = re.split(r"\s*&\s*", inner_expr, maxsplit=1)
            if len(parts) == 2:
                in1, in2 = parts[0].strip(), parts[1].strip()
                if negated:
                    gate_type = "nand"
                else:
                    gate_type = "and"
                ir.ensure_net(in1)
                ir.ensure_net(in2)
                inst_name = f"{gate_type}_assign_{counter}"
                ir.add_gate(gate_type, inst_name, output_net, [in1, in2])
                return
        
        # Try OR operator
        if " | " in inner_expr or "| " in inner_expr or " |" in inner_expr:
            parts = re.split(r"\s*\|\s*", inner_expr, maxsplit=1)
            if len(parts) == 2:
                in1, in2 = parts[0].strip(), parts[1].strip()
                if negated:
                    gate_type = "nor"
                else:
                    gate_type = "or"
                ir.ensure_net(in1)
                ir.ensure_net(in2)
                inst_name = f"{gate_type}_assign_{counter}"
                ir.add_gate(gate_type, inst_name, output_net, [in1, in2])
                return
        
        # Try XOR operator
        if " ^ " in inner_expr or "^ " in inner_expr or " ^" in inner_expr:
            parts = re.split(r"\s*\^\s*", inner_expr, maxsplit=1)
            if len(parts) == 2:
                in1, in2 = parts[0].strip(), parts[1].strip()
                if negated:
                    gate_type = "xnor"
                else:
                    gate_type = "xor"
                ir.ensure_net(in1)
                ir.ensure_net(in2)
                inst_name = f"{gate_type}_assign_{counter}"
                ir.add_gate(gate_type, inst_name, output_net, [in1, in2])
                return
        
        # If we reach here, the expression is complex or unsupported
        # For now, create a wire assignment (best effort)
        if self._is_single_identifier(inner_expr):
            inst_name = f"buf_assign_{counter}"
            ir.add_gate("buf", inst_name, output_net, [inner_expr])



class GateLevelVerilogWriter:
    def write_file(self, ir: NetlistIR, path: str) -> None:
        Path(path).write_text(self.render(ir), encoding="utf-8")

    def render(self, ir: NetlistIR) -> str:
        if ir.module_name is None:
            raise NetlistError("Cannot render empty design.")

        port_list = ir.inputs + ir.outputs
        lines = [f"module {ir.module_name}({', '.join(port_list)});"]
        if ir.inputs:
            lines.append(f"  input {', '.join(ir.inputs)};")
        if ir.outputs:
            lines.append(f"  output {', '.join(ir.outputs)};")

        internal_wires = [
            net.name
            for net in ir.nets.values()
            if not net.is_input and not net.is_output and not net.is_const
        ]
        if internal_wires:
            lines.append(f"  wire {', '.join(sorted(internal_wires))};")

        for node_name in sorted(ir.nodes.keys()):
            node = ir.nodes[node_name]
            if node.gate_type is None or node.output is None:
                continue
            pins = [node.output] + node.inputs
            lines.append(f"  {node.gate_type.value} {node.name}({', '.join(pins)});")

        lines.append("endmodule")
        return "\n".join(lines) + "\n"
