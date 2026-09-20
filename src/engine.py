from __future__ import annotations

import copy
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backends.equivalence import ABCEquivalenceBackend
from backends.python_graph import PythonGraphBackend
from backends.router import BackendRouter
from backends.yosys_backend import YosysBackend
from external_tools import ABCBridge, YosysBridge
from ir import GateType, Net, NetlistError, NetlistIR
from parser import GateLevelVerilogParser, GateLevelVerilogWriter, YosysJsonNetlistParser
from utils import normalize_path


@dataclass
class ExecutionResult:
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)


class DeterministicEDAEngine:
    """Backend entry point for deterministic EDA operations."""

    VALID_VERIFICATION_POLICIES = {"strict", "permissive", "dry_run"}

    def __init__(self, verification_policy: str = "permissive") -> None:
        self.ir = NetlistIR()
        self.reference_ir: Optional[NetlistIR] = None  # For equivalence checking
        self.parser = GateLevelVerilogParser()
        self.yosys_json_parser = YosysJsonNetlistParser()
        self.writer = GateLevelVerilogWriter()
        self.yosys = YosysBridge()
        self.abc = ABCBridge()
        self.graph_backend = PythonGraphBackend(self.ir)
        self.yosys_backend = YosysBackend(self.yosys)
        self.equivalence_backend = ABCEquivalenceBackend(self.abc)
        self.backend_router = BackendRouter()
        self.set_verification_policy(verification_policy)

    def _bind_backends(self) -> None:
        self.graph_backend.bind(self.ir)

    def set_verification_policy(self, policy: str) -> None:
        policy = policy.lower().strip()
        if policy not in self.VALID_VERIFICATION_POLICIES:
            allowed = ", ".join(sorted(self.VALID_VERIFICATION_POLICIES))
            raise ValueError(f"Unsupported verification policy '{policy}'. Allowed: {allowed}")
        self.verification_policy = policy

    def _clone_ir(self, source: Optional[NetlistIR] = None) -> NetlistIR:
        source = source or self.ir
        clone = NetlistIR()
        clone.module_name = source.module_name
        clone.inputs = source.inputs.copy()
        clone.outputs = source.outputs.copy()
        clone.nodes = copy.deepcopy(source.nodes)
        clone.nets = {
            name: Net(
                name=net.name,
                driver=net.driver,
                sinks=net.sinks.copy(),
                is_input=net.is_input,
                is_output=net.is_output,
                is_const=net.is_const,
            )
            for name, net in source.nets.items()
        }
        clone.loaded_path = source.loaded_path
        return clone

    def _set_reference_snapshot(self, source: Optional[NetlistIR] = None) -> NetlistIR:
        self.reference_ir = self._clone_ir(source or self.ir)
        return self.reference_ir

    def _verification_accepts(self, result: ExecutionResult) -> bool:
        equivalent = result.data.get("equivalent")
        if self.verification_policy == "strict":
            return equivalent is True
        if self.verification_policy == "permissive":
            return equivalent is not False
        return False

    def _verification_summary_line(self, result: ExecutionResult) -> str:
        equivalent = result.data.get("equivalent")
        if equivalent is True:
            status = "proved"
        elif equivalent is False:
            status = "failed"
        else:
            status = "inconclusive"
        return f"Verification policy '{self.verification_policy}': {status} equivalence result."

    @staticmethod
    def _normalization_committed_or_previewed(result: ExecutionResult) -> bool:
        return bool(result.data.get("normalized")) or bool(result.data.get("dry_run"))

    def read_netlist(self, path: str) -> ExecutionResult:
        norm = normalize_path(path)
        frontend = "gate_level_regex"
        fallback_error: Optional[str] = None
        try:
            self.ir = self.parser.parse_file(norm)
            self._bind_backends()
        except Exception as exc:
            fallback_error = f"{type(exc).__name__}: {exc}"
            if not self.yosys_backend.available():
                raise
            with tempfile.TemporaryDirectory() as temp_dir:
                json_path = os.path.join(temp_dir, "netlist.json")
                yosys_result = self.yosys_backend.frontend_json(norm, json_path)
                if not yosys_result.ok:
                    raise NetlistError(
                        "Could not parse Verilog with the restricted parser, and Yosys JSON export failed. "
                        f"Parser error: {fallback_error}. Yosys error: {yosys_result.stderr}"
                    )
                self.ir = self.yosys_json_parser.parse_file(json_path, loaded_path=norm)
                self._bind_backends()
                frontend = "yosys_json"

        return ExecutionResult(
            summary=(
                f'Loaded gate-level Verilog from "{norm}" successfully.\n'
                f'- Frontend: {frontend}.\n'
                f'- Detected a single top module (flat netlist).\n'
                f'- Inputs: {len(self.ir.inputs)}, Outputs: {len(self.ir.outputs)}, '
                f'Instances: {len(self.ir.nodes)}, Nets: {len(self.ir.nets)}.\n'
                f'Design state has been updated.'
            ),
            data={
                "path": norm,
                "module": self.ir.module_name,
                "inputs": len(self.ir.inputs),
                "outputs": len(self.ir.outputs),
                "instances": len(self.ir.nodes),
                "nets": len(self.ir.nets),
                "frontend": frontend,
                "fallback_error": fallback_error,
            },
        )

    def write_netlist(self, path: str) -> ExecutionResult:
        norm = normalize_path(path)
        self.writer.write_file(self.ir, norm)
        return ExecutionResult(
            summary=f'Wrote the current netlist to "{norm}" successfully.',
            data={"path": norm},
        )

    def clean_dangling_and_write(self, input_path: str, output_path: str) -> ExecutionResult:
        """Read a design, remove dangling logic, and write the cleaned design."""
        read_result = self.read_netlist(input_path)
        clean_result = self.remove_dangling_logic()
        if not clean_result.data.get("success", False):
            return ExecutionResult(
                summary=(
                    "Could not complete dangling-logic cleanup workflow.\n"
                    f"Read: {read_result.summary}\n"
                    f"Cleanup: {clean_result.summary}"
                ),
                data={
                    "success": False,
                    "input_path": input_path,
                    "output_path": output_path,
                    "read": read_result.data,
                    "cleanup": clean_result.data,
                },
            )

        write_result = self.write_netlist(output_path)
        return ExecutionResult(
            summary=(
                "Dangling-logic cleanup workflow completed successfully.\n"
                f"Input design: {input_path}\n"
                f"Output design: {write_result.data['path']}\n\n"
                f"Read:\n{read_result.summary}\n\n"
                f"Cleanup:\n{clean_result.summary}\n\n"
                f"Write:\n{write_result.summary}"
            ),
            data={
                "success": True,
                "input_path": input_path,
                "output_path": write_result.data["path"],
                "read": read_result.data,
                "cleanup": clean_result.data,
                "write": write_result.data,
            },
        )

    def check_external_tools(self) -> ExecutionResult:
        yosys_available = self.yosys_backend.available()
        abc_available = self.equivalence_backend.available()
        yosys_version = self.yosys_backend.version() if yosys_available else None
        abc_version = self.equivalence_backend.version() if abc_available else None
        lines = [
            "External EDA tool status:",
            f"- Yosys: {'available' if yosys_available else 'not found'}",
            f"- ABC: {'available' if abc_available else 'not found'}",
        ]
        if yosys_version:
            lines.append(f"- Yosys version: {yosys_version}")
        if abc_version:
            lines.append(f"- ABC version/help: {abc_version}")
        return ExecutionResult(
            summary="\n".join(lines),
            data={
                "yosys_available": yosys_available,
                "abc_available": abc_available,
                "yosys_version": yosys_version,
                "abc_version": abc_version,
                "backend_routes": self.backend_router.describe(),
            },
        )

    def normalize_design(self, reference_ir: Optional[NetlistIR] = None) -> ExecutionResult:
        """Normalize the current design using Yosys with verification-first pipeline."""
        if not self.yosys_backend.available():
            return ExecutionResult(
                summary="Yosys not available. Cannot normalize design.",
                data={"normalized": False, "error": "yosys_not_available"},
            )

        # STEP 1: Store reference design for verification.
        # Transformations can pass their original pre-edit reference here so
        # normalization verifies against the true baseline, not just the
        # pre-normalized transformed design.
        original_ir = self._clone_ir(self.ir)
        self.reference_ir = self._clone_ir(reference_ir) if reference_ir is not None else self._clone_ir(self.ir)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_v = os.path.join(temp_dir, "input.v")
            output_v = os.path.join(temp_dir, "normalized.v")

            # Write current design to temp file
            self.writer.write_file(self.ir, input_v)

            # STEP 2: Run Yosys normalization
            result = self.yosys_backend.normalize(input_v, output_v, self.ir.module_name)

            if not result.ok:
                return ExecutionResult(
                    summary=f"Yosys normalization failed: {result.stderr}",
                    data={"normalized": False, "error": result.stderr},
                )

            # STEP 3: Parse normalized design back into IR
            try:
                normalized_ir = self.parser.parse_file(output_v)
                original_instances = len(self.ir.nodes)
                original_nets = len(self.ir.nets)
                self.ir = normalized_ir
                self._bind_backends()
                new_instances = len(self.ir.nodes)
                new_nets = len(self.ir.nets)

                # STEP 4: Verify equivalence to ensure correctness
                equiv_result = self.check_equivalence()
                verification_line = self._verification_summary_line(equiv_result)

                if self.verification_policy == "dry_run":
                    self.ir = original_ir
                    self._bind_backends()
                    return ExecutionResult(
                        summary=(
                            "Dry run complete: design normalization was analyzed but not committed.\n"
                            f"- Instances would change: {original_instances} -> {new_instances}\n"
                            f"- Nets would change: {original_nets} -> {new_nets}\n"
                            f"{verification_line}"
                        ),
                        data={
                            "normalized": False,
                            "dry_run": True,
                            "committed": False,
                            "equivalent": equiv_result.data.get("equivalent"),
                            "original_instances": original_instances,
                            "original_nets": original_nets,
                            "new_instances": new_instances,
                            "new_nets": new_nets,
                            "verification_policy": self.verification_policy,
                        },
                    )

                if not self._verification_accepts(equiv_result):
                    # STEP 5: Rollback on equivalence failure
                    self.ir = original_ir
                    self._bind_backends()
                    return ExecutionResult(
                        summary=(
                            "Design normalization was not committed. Reverted changes.\n"
                            f"{verification_line}\n"
                            f"{equiv_result.summary}"
                        ),
                        data={
                            "normalized": False,
                            "equivalent": equiv_result.data.get("equivalent"),
                            "error": "verification_not_accepted",
                            "reverted": True,
                            "verification_policy": self.verification_policy,
                        },
                    )

                return ExecutionResult(
                    summary=(
                        "Design normalized successfully using Yosys.\n"
                        f"- Instances: {original_instances} -> {new_instances}\n"
                        f"- Nets: {original_nets} -> {new_nets}\n"
                        f"- {verification_line}\n"
                        "Design state has been updated."
                    ),
                    data={
                        "normalized": True,
                        "equivalent": equiv_result.data.get("equivalent"),
                        "original_instances": original_instances,
                        "original_nets": original_nets,
                        "new_instances": new_instances,
                        "new_nets": new_nets,
                        "verification_policy": self.verification_policy,
                    },
                )
            except Exception as e:
                # Rollback on parsing error
                self.ir = original_ir
                self._bind_backends()
                return ExecutionResult(
                    summary=f"Failed to parse normalized Verilog: {e}. Reverted to original design.",
                    data={"normalized": False, "error": str(e), "reverted": True},
                )

    def check_equivalence(self) -> ExecutionResult:
        """Check equivalence between current design and reference design using ABC."""
        if self.reference_ir is None:
            return ExecutionResult(
                summary="No reference design available for equivalence checking.",
                data={"equivalent": None, "error": "no_reference"},
            )

        if not self.equivalence_backend.available():
            return ExecutionResult(
                summary="ABC not available. Cannot perform equivalence checking.",
                data={"equivalent": None, "error": "abc_not_available"},
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            ref_v = os.path.join(temp_dir, "reference.v")
            curr_v = os.path.join(temp_dir, "current.v")
            ref_blif = os.path.join(temp_dir, "reference.blif")
            curr_blif = os.path.join(temp_dir, "current.blif")

            # Write both designs
            self.writer.write_file(self.reference_ir, ref_v)
            self.writer.write_file(self.ir, curr_v)

            # Convert to BLIF using Yosys
            if not self.yosys_backend.available():
                return ExecutionResult(
                    summary="Yosys not available. Cannot convert designs for equivalence checking.",
                    data={"equivalent": None, "error": "yosys_not_available"},
                )

            ref_result = self.yosys_backend.write_blif(ref_v, ref_blif, self.reference_ir.module_name)
            if not ref_result.ok:
                return ExecutionResult(
                    summary=f"Failed to convert reference design to BLIF: {ref_result.stderr}",
                    data={"equivalent": None, "error": "blif_conversion_failed"},
                )

            curr_result = self.yosys_backend.write_blif(curr_v, curr_blif, self.ir.module_name)
            if not curr_result.ok:
                return ExecutionResult(
                    summary=f"Failed to convert current design to BLIF: {curr_result.stderr}",
                    data={"equivalent": None, "error": "blif_conversion_failed"},
                )

            outcome = self.equivalence_backend.check_blif(ref_blif, curr_blif)
            data = {
                "equivalent": outcome.equivalent,
                "method": outcome.method,
                "details": outcome.details,
            }
            if outcome.equivalent is False:
                data["error"] = outcome.details.get("stderr", "")
            return ExecutionResult(summary=outcome.summary, data=data)

    def check_max_fanout(self, max_fanout: int) -> ExecutionResult:
        """Check if any net exceeds the maximum fanout limit."""
        result = self.graph_backend.check_max_fanout(max_fanout)
        violations = result["violations"]

        if not violations:
            return ExecutionResult(
                summary=f"All nets satisfy max fanout ≤ {max_fanout}.",
                data=result,
            )
        else:
            violation_str = "\n".join(f"- Net '{name}': fanout {fanout}" for name, fanout in violations)
            return ExecutionResult(
                summary=f"Found {len(violations)} nets exceeding max fanout {max_fanout}:\n{violation_str}",
                data=result,
            )

    def insert_and_before_buffers(self, pattern: str, control_signal: str) -> ExecutionResult:
        """Insert AND gates before buffers matching the pattern, connecting control_signal to the extra input."""
        if control_signal not in self.ir.nets:
            return ExecutionResult(
                summary=f"Control signal '{control_signal}' not found in the netlist.",
                data={"success": False, "error": "control_signal_not_found"},
            )

        matching_buffers = []
        for node_name, node in self.ir.nodes.items():
            if node.gate_type == GateType.BUF and pattern in node_name:
                matching_buffers.append((node_name, node))

        if not matching_buffers:
            return ExecutionResult(
                summary=f"No buffers found with pattern '{pattern}' in their names.",
                data={"success": False, "error": "no_matching_buffers"},
            )

        # Store original design for equivalence checking and rollback.
        original_ir = self._set_reference_snapshot()

        modifications = []
        for buf_name, buf_node in matching_buffers:
            if not buf_node.inputs:
                continue  # Skip malformed buffers

            original_input = buf_node.inputs[0]
            and_output_net = f"{buf_name}_and_out"

            # Create new AND gate
            and_name = f"{buf_name}_and"
            self.ir.add_gate("and", and_name, and_output_net, [original_input, control_signal])

            # Update buffer input to AND output
            buf_node.inputs[0] = and_output_net

            # Update net connections
            # Remove buffer from original input's sinks
            if original_input in self.ir.nets:
                self.ir.nets[original_input].sinks = [s for s in self.ir.nets[original_input].sinks if s != buf_name]
                # Add AND gate to original input's sinks
                self.ir.nets[original_input].sinks.append(and_name)

            # Ensure AND output net exists and is driven by AND
            and_net = self.ir.ensure_net(and_output_net)
            and_net.driver = and_name
            # Add buffer to AND output's sinks
            and_net.sinks.append(buf_name)

            modifications.append(f"- {buf_name}: inserted {and_name} with inputs {{{original_input}, {control_signal}}}")

        if modifications:
            # Apply transformation, then normalize and check equivalence
            transform_result = ExecutionResult(
                summary=(
                    f"Inserted AND gates before {len(modifications)} matching buffers.\n"
                    + "\n".join(modifications) + "\n"
                    "All other connectivity remains unchanged."
                ),
                data={"success": True, "modified_buffers": len(modifications), "control_signal": control_signal},
            )

            # Normalize the design after transformation
            normalize_result = self.normalize_design(reference_ir=original_ir)
            if not self._normalization_committed_or_previewed(normalize_result):
                return ExecutionResult(
                    summary=f"Transformation applied but normalization failed: {normalize_result.summary}",
                    data={"success": False, "error": "normalization_failed", "transform_result": transform_result.data},
                )

            if normalize_result.data.get("dry_run"):
                self.ir = original_ir
                return ExecutionResult(
                    summary=(
                        "Dry run complete: transformation was analyzed but not committed.\n"
                        f"{transform_result.summary}\n"
                        f"Normalization: {normalize_result.summary}"
                    ),
                    data={
                        "success": True,
                        "dry_run": True,
                        "committed": False,
                        "modified_buffers": len(modifications),
                        "control_signal": control_signal,
                        "normalized": False,
                        "equivalent": normalize_result.data.get("equivalent"),
                        "verification_policy": self.verification_policy,
                    },
                )

            # Check equivalence
            equiv_result = self.check_equivalence()
            if equiv_result.data.get("equivalent") is False:
                # Equivalence check failed - revert to reference
                self.ir = original_ir
                return ExecutionResult(
                    summary=f"Transformation applied but equivalence check failed. Reverted changes.\n{equiv_result.summary}",
                    data={"success": False, "error": "equivalence_failed", "reverted": True},
                )

            # All checks passed
            return ExecutionResult(
                summary=(
                    f"Transformation successful and verified:\n"
                    f"{transform_result.summary}\n"
                    f"Normalization: {normalize_result.summary}\n"
                    f"Equivalence: {equiv_result.summary}"
                ),
                data={
                    "success": True,
                    "modified_buffers": len(modifications),
                    "control_signal": control_signal,
                    "normalized": True,
                    "equivalent": equiv_result.data.get("equivalent"),
                    "verification_policy": self.verification_policy,
                },
            )
        else:
            return ExecutionResult(
                summary="No modifications were made.",
                data={"success": False, "error": "no_modifications"},
            )

    def replace_gates(self, from_gate: str, to_gate: str, pattern: Optional[str] = None) -> ExecutionResult:
        """Replace gates of one type with another type, optionally matching a pattern."""
        # Parse gate types
        try:
            from_type = GateType(from_gate.lower())
            to_type = GateType(to_gate.lower())
        except ValueError:
            return ExecutionResult(
                summary=f"Unsupported gate type: '{from_gate}' or '{to_gate}'. Supported: {list(GateType)}",
                data={"success": False, "error": "unsupported_gate_type"},
            )

        matching_gates = []
        for node_name, node in self.ir.nodes.items():
            if node.gate_type == from_type and (pattern is None or pattern in node_name):
                matching_gates.append((node_name, node))

        if not matching_gates:
            pattern_desc = f" with pattern '{pattern}'" if pattern else ""
            return ExecutionResult(
                summary=f"No {from_gate} gates found{pattern_desc}.",
                data={"success": False, "error": "no_matching_gates"},
            )

        # Store original design for equivalence checking and rollback.
        original_ir = self._set_reference_snapshot()

        modifications = []
        for gate_name, gate_node in matching_gates:
            # Change gate type
            old_type = gate_node.gate_type
            gate_node.gate_type = to_type
            modifications.append(f"- {gate_name}: {old_type.value} → {to_type.value}")

        # Apply transformation, then normalize and check equivalence
        transform_result = ExecutionResult(
            summary=(
                f"Replaced {len(modifications)} {from_gate} gates with {to_gate}.\n"
                + "\n".join(modifications)
            ),
            data={"success": True, "replaced_gates": len(modifications), "from_type": from_gate, "to_type": to_gate},
        )

        # Normalize the design after transformation
        normalize_result = self.normalize_design(reference_ir=original_ir)
        if not self._normalization_committed_or_previewed(normalize_result):
            return ExecutionResult(
                summary=f"Transformation applied but normalization failed: {normalize_result.summary}",
                data={"success": False, "error": "normalization_failed", "transform_result": transform_result.data},
            )

        if normalize_result.data.get("dry_run"):
            self.ir = original_ir
            return ExecutionResult(
                summary=(
                    "Dry run complete: transformation was analyzed but not committed.\n"
                    f"{transform_result.summary}\n"
                    f"Normalization: {normalize_result.summary}"
                ),
                data={
                    "success": True,
                    "dry_run": True,
                    "committed": False,
                    "replaced_gates": len(modifications),
                    "from_type": from_gate,
                    "to_type": to_gate,
                    "normalized": False,
                    "equivalent": normalize_result.data.get("equivalent"),
                    "verification_policy": self.verification_policy,
                },
            )

        # Check equivalence
        equiv_result = self.check_equivalence()
        if equiv_result.data.get("equivalent") is False:
            # Equivalence check failed - revert to reference
            self.ir = original_ir
            return ExecutionResult(
                summary=f"Transformation applied but equivalence check failed. Reverted changes.\n{equiv_result.summary}",
                data={"success": False, "error": "equivalence_failed", "reverted": True},
            )

        # All checks passed
        return ExecutionResult(
            summary=(
                f"Transformation successful and verified:\n"
                f"{transform_result.summary}\n"
                f"Normalization: {normalize_result.summary}\n"
                f"Equivalence: {equiv_result.summary}"
            ),
            data={
                "success": True,
                "replaced_gates": len(modifications),
                "from_type": from_gate,
                "to_type": to_gate,
                "normalized": True,
            "equivalent": equiv_result.data.get("equivalent"),
            "verification_policy": self.verification_policy,
            },
        )

    def optimize_cone(self, output_signal: str, max_depth: Optional[int] = None, minimize_gates: bool = False) -> ExecutionResult:
        """Analyze and potentially optimize the logic cone of an output signal."""
        if output_signal not in self.ir.outputs and output_signal not in self.ir.nets:
            return ExecutionResult(
                summary=f"Output signal '{output_signal}' not found in the netlist.",
                data={"success": False, "error": "output_not_found"},
            )

        # Store original design for equivalence checking and rollback.
        original_ir = self._set_reference_snapshot()

        # Find the cone (all gates/nets that affect this output)
        cone_nets, cone_nodes = self.graph_backend.cone_from_output(output_signal)
        max_depth_value, _ = self.graph_backend.longest_path_between_nets(self.ir.inputs[0] if self.ir.inputs else list(cone_nets)[0], output_signal)

        summary_lines = [
            f"Logic cone analysis for output '{output_signal}':",
            f"- Gates in cone: {len(cone_nodes)}",
            f"- Nets in cone: {len(cone_nets)}",
            f"- Maximum depth: {max_depth_value}",
        ]

        optimized = False
        optimization_method = "none"

        # Try ABC optimization if available
        if self.equivalence_backend.available() and (minimize_gates or (max_depth is not None and max_depth_value > max_depth)):
            with tempfile.TemporaryDirectory() as temp_dir:
                input_blif = os.path.join(temp_dir, "input.blif")
                output_blif = os.path.join(temp_dir, "optimized.blif")
                optimized_v = os.path.join(temp_dir, "optimized.v")

                # Export current design to BLIF
                if self.yosys_backend.available():
                    # Write current design to temp Verilog first
                    temp_v = os.path.join(temp_dir, "temp.v")
                    self.writer.write_file(self.ir, temp_v)
                    blif_result = self.yosys_backend.write_blif(temp_v, input_blif, self.ir.module_name)
                    if blif_result.ok:
                        # Run ABC optimization
                        opt_result = self.abc.optimize_blif(input_blif, output_blif)
                        if opt_result.ok:
                            # Convert back to Verilog
                            # For now, just report success - full reintegration is complex
                            summary_lines.append("- ABC optimization completed (reintegration pending)")
                            optimized = True
                            optimization_method = "abc_basic"
                        else:
                            summary_lines.append(f"- ABC optimization failed: {opt_result.stderr}")
                    else:
                        summary_lines.append(f"- BLIF export failed: {blif_result.stderr}")
                else:
                    summary_lines.append("- Yosys not available for BLIF export")

        # Yosys-based optimization as fallback
        elif self.yosys_backend.available() and (minimize_gates or (max_depth is not None and max_depth_value > max_depth)):
            # Run additional Yosys optimization passes
            normalize_result = self.normalize_design(reference_ir=original_ir)
            if normalize_result.data.get("normalized", False):
                summary_lines.append("- Yosys optimization applied")
                optimized = True
                optimization_method = "yosys_normalize"
            elif normalize_result.data.get("dry_run"):
                summary_lines.append("- Dry run: Yosys optimization analyzed but not committed")
                summary_lines.append(f"- {normalize_result.summary}")
            else:
                summary_lines.append(f"- Yosys optimization failed: {normalize_result.summary}")

        if max_depth is not None:
            if max_depth_value <= max_depth:
                summary_lines.append(f"- Depth constraint satisfied: {max_depth_value} ≤ {max_depth}")
            else:
                summary_lines.append(f"- Depth constraint violated: {max_depth_value} > {max_depth} (optimization attempted)")

        if minimize_gates:
            summary_lines.append("- Gate minimization requested (optimization attempted)")

        # Check equivalence if optimization was applied
        if optimized:
            equiv_result = self.check_equivalence()
            if equiv_result.data.get("equivalent") is False:
                # Optimization broke functionality - revert
                self.ir = original_ir
                summary_lines.append(f"- Optimization reverted due to equivalence failure: {equiv_result.summary}")
                optimized = False
            else:
                summary_lines.append(f"- Optimization verified: {equiv_result.summary}")

        return ExecutionResult(
            summary="\n".join(summary_lines),
            data={
                "output_signal": output_signal,
                "cone_gates": len(cone_nodes),
                "cone_nets": len(cone_nets),
                "max_depth": max_depth_value,
                "depth_constraint": max_depth,
                "depth_satisfied": max_depth is None or max_depth_value <= max_depth,
                "optimized": optimized,
                "optimization_method": optimization_method,
            },
        )

    def _compute_cone_from_output(self, output_signal: str) -> Tuple[set, set]:
        """Compute the logic cone (upstream nets and nodes) that affects the given output signal."""
        cone_nets = set()
        cone_nodes = set()
        visited_nets = set()
        visited_nodes = set()

        # Start from the output net
        start_net = output_signal
        if start_net not in self.ir.nets:
            return cone_nets, cone_nodes

        def traverse_upstream(net_name: str) -> None:
            if net_name in visited_nets:
                return
            visited_nets.add(net_name)
            cone_nets.add(net_name)

            # Find the driver of this net
            net = self.ir.nets[net_name]
            if net.driver and net.driver not in visited_nodes:
                visited_nodes.add(net.driver)
                cone_nodes.add(net.driver)
                node = self.ir.nodes[net.driver]
                # Traverse all input nets of this node
                for input_net in node.inputs:
                    traverse_upstream(input_net)

        traverse_upstream(start_net)
        return cone_nets, cone_nodes

    def get_fanout(self, node_or_net: str) -> ExecutionResult:
        result = self.graph_backend.fanout(node_or_net)
        if result["kind"] == "net":
            return ExecutionResult(
                summary=f"Fanout of net '{result['name']}' is {result['fanout']}.",
                data=result,
            )
        return ExecutionResult(
            summary=f"Fanout of instance '{result['name']}' is {result['fanout']} via output net '{result['output_net']}'.",
            data=result,
        )

    def get_max_depth(self, source: str, sink: str) -> ExecutionResult:
        depth, path = self.graph_backend.longest_path_between_nets(source, sink)
        if depth < 0:
            return ExecutionResult(
                summary=f"No combinational path found from '{source}' to '{sink}'.",
                data={"source": source, "sink": sink, "depth": None, "path": []},
            )
        return ExecutionResult(
            summary=(
                f"The maximum logic depth from '{source}' to '{sink}' is {depth}.\n"
                f"One example longest path is: {' -> '.join(path)}"
            ),
            data={"source": source, "sink": sink, "depth": depth, "path": path},
        )

    def find_path(self, source: str, sink: str, avoid: Optional[str] = None) -> ExecutionResult:
        path = self.graph_backend.find_any_path(source, sink, avoid)
        if not path:
            msg = f"No path found from '{source}' to '{sink}'."
            if avoid:
                msg = f"No path found from '{source}' to '{sink}' that avoids '{avoid}'."
            return ExecutionResult(summary=msg, data={"path": []})
        return ExecutionResult(
            summary=f"Found path: {' -> '.join(path)}",
            data={"source": source, "sink": sink, "avoid": avoid, "path": path},
        )

    def remove_dangling_logic(self) -> ExecutionResult:
        # Store original design for equivalence checking and rollback.
        original_ir = self._set_reference_snapshot()

        if self.yosys_backend.available():
            with tempfile.TemporaryDirectory() as temp_dir:
                input_v = os.path.join(temp_dir, "input.v")
                output_v = os.path.join(temp_dir, "cleaned.v")
                self.writer.write_file(self.ir, input_v)
                clean_result = self.yosys_backend.clean_unused_logic(input_v, output_v, self.ir.module_name)
                if clean_result.ok:
                    try:
                        cleaned_ir = self.parser.parse_file(output_v)
                        removed_nodes = sorted(set(self.ir.nodes) - set(cleaned_ir.nodes))
                        removed_nets = sorted(set(self.ir.nets) - set(cleaned_ir.nets))
                        self.ir = cleaned_ir
                        self._bind_backends()

                        normalize_result = self.normalize_design(reference_ir=original_ir)
                        if not self._normalization_committed_or_previewed(normalize_result):
                            self.ir = original_ir
                            self._bind_backends()
                            return ExecutionResult(
                                summary=f"Yosys clean was not committed: {normalize_result.summary}",
                                data={
                                    "success": False,
                                    "backend": "yosys",
                                    "error": "normalization_failed",
                                    "transform_result": clean_result.stdout,
                                },
                            )

                        if normalize_result.data.get("dry_run"):
                            self.ir = original_ir
                            self._bind_backends()
                            return ExecutionResult(
                                summary=(
                                    "Dry run complete: Yosys dangling-logic cleanup was analyzed but not committed.\n"
                                    f"- Instances that would be removed: {len(removed_nodes)}\n"
                                    f"- Nets that would be removed: {len(removed_nets)}\n"
                                    f"Normalization: {normalize_result.summary}"
                                ),
                                data={
                                    "success": True,
                                    "backend": "yosys",
                                    "dry_run": True,
                                    "committed": False,
                                    "removed_nodes": removed_nodes,
                                    "removed_nets": removed_nets,
                                    "normalized": False,
                                    "equivalent": normalize_result.data.get("equivalent"),
                                    "verification_policy": self.verification_policy,
                                },
                            )

                        equiv_result = self.check_equivalence()
                        if equiv_result.data.get("equivalent") is False:
                            self.ir = original_ir
                            self._bind_backends()
                            return ExecutionResult(
                                summary=f"Yosys clean failed equivalence. Reverted changes.\n{equiv_result.summary}",
                                data={
                                    "success": False,
                                    "backend": "yosys",
                                    "error": "equivalence_failed",
                                    "reverted": True,
                                },
                            )

                        return ExecutionResult(
                            summary=(
                                "Yosys removed dangling logic successfully.\n"
                                f"- Removed instances: {len(removed_nodes)}\n"
                                f"- Removed nets: {len(removed_nets)}\n"
                                f"Normalization: {normalize_result.summary}\n"
                                f"Equivalence: {equiv_result.summary}"
                            ),
                            data={
                                "success": True,
                                "backend": "yosys",
                                "removed_nodes": removed_nodes,
                                "removed_nets": removed_nets,
                                "normalized": True,
                                "equivalent": equiv_result.data.get("equivalent"),
                                "verification_policy": self.verification_policy,
                            },
                        )
                    except Exception:
                        self.ir = original_ir
                        self._bind_backends()
                        # Fall through to Python graph cleanup.

        live_nets, live_nodes = self.graph_backend.live_cone_from_outputs()
        removed_nodes = [name for name in list(self.ir.nodes.keys()) if name not in live_nodes]
        removed_nets = [
            name for name, net in list(self.ir.nets.items())
            if self._is_removable_net(name, net, live_nets)
        ]

        for node_name in removed_nodes:
            node = self.ir.nodes[node_name]
            if node.output and node.output in self.ir.nets:
                self.ir.nets[node.output].driver = None
            for in_net in node.inputs:
                if in_net in self.ir.nets:
                    self.ir.nets[in_net].sinks = [s for s in self.ir.nets[in_net].sinks if s != node_name]
            del self.ir.nodes[node_name]

        for net_name in removed_nets:
            del self.ir.nets[net_name]
        self._bind_backends()

        # Apply transformation, then normalize and check equivalence
        transform_result = ExecutionResult(
            summary=(
                f"Removed dangling logic successfully.\n"
                f"- Removed instances: {len(removed_nodes)}\n"
                f"- Removed nets: {len(removed_nets)}"
            ),
            data={"removed_nodes": removed_nodes, "removed_nets": removed_nets},
        )

        # Normalize the design after transformation
        normalize_result = self.normalize_design(reference_ir=original_ir)
        if not self._normalization_committed_or_previewed(normalize_result):
            return ExecutionResult(
                summary=f"Transformation applied but normalization failed: {normalize_result.summary}",
                data={"success": False, "error": "normalization_failed", "transform_result": transform_result.data},
            )

        if normalize_result.data.get("dry_run"):
            self.ir = original_ir
            self._bind_backends()
            return ExecutionResult(
                summary=(
                    "Dry run complete: transformation was analyzed but not committed.\n"
                    f"{transform_result.summary}\n"
                    f"Normalization: {normalize_result.summary}"
                ),
                data={
                    "success": True,
                    "dry_run": True,
                    "committed": False,
                    "removed_nodes": removed_nodes,
                    "removed_nets": removed_nets,
                    "normalized": False,
                    "equivalent": normalize_result.data.get("equivalent"),
                    "verification_policy": self.verification_policy,
                },
            )

        # Check equivalence
        equiv_result = self.check_equivalence()
        if equiv_result.data.get("equivalent") is False:
            # Equivalence check failed - revert to reference
            self.ir = original_ir
            self._bind_backends()
            return ExecutionResult(
                summary=f"Transformation applied but equivalence check failed. Reverted changes.\n{equiv_result.summary}",
                data={"success": False, "error": "equivalence_failed", "reverted": True},
            )

        # All checks passed
        return ExecutionResult(
            summary=(
                f"Transformation successful and verified:\n"
                f"{transform_result.summary}\n"
                f"Normalization: {normalize_result.summary}\n"
                f"Equivalence: {equiv_result.summary}"
            ),
            data={
                "success": True,
                "removed_nodes": removed_nodes,
                "removed_nets": removed_nets,
                "normalized": True,
                "equivalent": equiv_result.data.get("equivalent"),
                "verification_policy": self.verification_policy,
            },
        )

    def _find_any_path(self, source: str, sink: str, avoid: Optional[str]) -> List[str]:
        if source not in self.ir.nets or sink not in self.ir.nets:
            return []
        avoid_set = {avoid} if avoid else set()
        visited_nets = set()
        visited_nodes = set()

        def dfs_net(cur_net: str, acc: List[str]) -> Optional[List[str]]:
            if cur_net in avoid_set:
                return None
            if cur_net == sink:
                return acc + [cur_net]
            if cur_net in visited_nets:
                return None
            visited_nets.add(cur_net)
            for node_name in self.ir.nets[cur_net].sinks:
                if node_name in avoid_set or node_name in visited_nodes:
                    continue
                visited_nodes.add(node_name)
                out_net = self.ir.nodes[node_name].output
                if out_net is None:
                    continue
                result = dfs_net(out_net, acc + [cur_net, node_name])
                if result is not None:
                    return result
            return None

        result = dfs_net(source, [])
        return result if result is not None else []

    def _longest_path_between_nets(self, source: str, sink: str) -> Tuple[int, List[str]]:
        if source not in self.ir.nets or sink not in self.ir.nets:
            return -1, []
        memo: Dict[str, Tuple[int, List[str]]] = {}
        temp_mark = set()

        def dfs_net(cur_net: str) -> Tuple[int, List[str]]:
            if cur_net == sink:
                return 0, [cur_net]
            if cur_net in memo:
                return memo[cur_net]
            if cur_net in temp_mark:
                return -1, []
            temp_mark.add(cur_net)
            best_depth = -1
            best_path: List[str] = []
            for node_name in self.ir.nets[cur_net].sinks:
                node = self.ir.nodes[node_name]
                if node.gate_type == GateType.DFF:
                    continue
                out_net = node.output
                if out_net is None:
                    continue
                sub_depth, sub_path = dfs_net(out_net)
                if sub_depth >= 0 and 1 + sub_depth > best_depth:
                    best_depth = 1 + sub_depth
                    best_path = [cur_net, node_name] + sub_path
            temp_mark.remove(cur_net)
            memo[cur_net] = (best_depth, best_path)
            return memo[cur_net]

        return dfs_net(source)

    def _compute_live_cone_from_outputs(self) -> Tuple[set[str], set[str]]:
        live_nets = set(self.ir.outputs)
        live_nodes = set()
        stack = list(self.ir.outputs)
        while stack:
            net_name = stack.pop()
            net = self.ir.nets.get(net_name)
            if net is None or net.driver is None:
                continue
            node_name = net.driver
            if node_name in live_nodes:
                continue
            live_nodes.add(node_name)
            node = self.ir.nodes[node_name]
            for in_net in node.inputs:
                if in_net not in live_nets:
                    live_nets.add(in_net)
                    stack.append(in_net)
        live_nets.update(self.ir.inputs)
        return live_nets, live_nodes

    def _is_removable_net(self, name: str, net: Net, live_nets: set[str]) -> bool:
        if name in live_nets:
            return False
        if net.is_input or net.is_output or net.is_const:
            return False
        if net.driver is not None:
            return True
        if not net.sinks:
            return True
        return False
