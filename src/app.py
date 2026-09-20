from __future__ import annotations

import logging
import re
import sys
from typing import Any, Dict, Optional, Sequence

from config import load_config, make_planner_from_config, parse_args
from engine import DeterministicEDAEngine
from planners.base import BasePlanner
from planners.heuristic import HeuristicBootstrapPlanner
from protocol import CaseLogger, ProtocolError, ProtocolManager
from results_logger import ResultsLogger
from schema import STRICT_TOOL_SCHEMA, ToolCall, ToolCallValidator, ToolName, ValidationError
from utils import now_ts, stable_json_dumps


CASE_START_RE = re.compile(
    r"(?:beginning of (?:a new )?testcase(?:\s+|.*?case name is\s+)|case name is\s+)"
    r"[\"'`]?([A-Za-z0-9_\-]+)[\"'`]?(?:\.|\s|$)",
    re.IGNORECASE,
)


class TransactionLogger:
    """Structured append-only debug logger, separate from contest response log."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("iccad_phase2")
        self.logger.setLevel(logging.INFO)
        self.handler = None

    def initialize(self, case_name: str) -> None:
        if self.handler:
            self.logger.removeHandler(self.handler)
            self.handler.close()
        self.handler = logging.FileHandler(f"{case_name}.transactions.log", mode="w", encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(self.handler)

    def log_event(self, kind: str, payload: Dict[str, Any]) -> None:
        record = {"timestamp": now_ts(), "kind": kind, "payload": payload}
        self.logger.info(stable_json_dumps(record))


class ICCADApp:
    def __init__(
        self,
        planner: Optional[BasePlanner] = None,
        debug: bool = False,
        verification_policy: str = "permissive",
    ) -> None:
        self.case_logger = CaseLogger()
        self.protocol = ProtocolManager(self.case_logger)
        self.validator = ToolCallValidator(STRICT_TOOL_SCHEMA)
        self.engine = DeterministicEDAEngine(verification_policy=verification_policy)
        self.planner = planner if planner is not None else HeuristicBootstrapPlanner()
        self.txlog = TransactionLogger()
        self.case_name: Optional[str] = None
        self.debug = debug
        self.results = ResultsLogger(".")

    def debug_print(self, message: str) -> None:
        """Print diagnostics to stderr so stdout remains contest-protocol clean."""
        if self.debug:
            print(message, file=sys.stderr)

    def handle_line(self, line: str) -> None:
        user_request = line.rstrip("\n")
        if not user_request.strip():
            return

        self.results.save_user_request(user_request)

        case_match = CASE_START_RE.search(user_request)
        if case_match:
            case_name = case_match.group(1)
            self.case_name = case_name
            self.case_logger.initialize(case_name)
            self.txlog.initialize(case_name)
            self.txlog.log_event("user_request", {"text": user_request, "type": "case_start"})
            self.debug_print(f"\n[CASE START] {case_name}")

            ack_body = (
                f'Acknowledged. Initialized testcase "{case_name}". '
                f'All subsequent responses will be recorded to {case_name}.log.\n'
                f'Design state is empty and ready for commands.'
            )
            self.results.save_response(ack_body)
            self.protocol.emit_ack_case_start(case_name)
            return

        if self.case_name is None:
            raise ProtocolError("Received request before testcase initialization.")

        self.txlog.log_event("user_request", {"text": user_request})
        self.debug_print(f"\n[USER REQUEST] {user_request}")
        self.debug_print(f"[PLANNER CLASS] {self.planner.__class__.__name__}")

        try:
            planner_raw = self.planner.plan(user_request)
        except Exception as exc:
            err_msg = f"Planner failed safely: {type(exc).__name__}: {exc}"
            self.txlog.log_event("planner_failed", {"error": err_msg})
            self.debug_print(f"[PLANNER FAILURE] {err_msg}")
            self.results.save_execution_error(
                {
                    "stage": "planner",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            self.results.save_response(err_msg)
            self.protocol.emit_response(err_msg)
            return

        self.txlog.log_event("planner_output", {"raw": planner_raw})

        planner_used = getattr(self.planner, "last_used", self.planner.__class__.__name__)
        planner_error = getattr(self.planner, "last_error", None)

        self.results.save_planner_raw(planner_raw)
        self.results.save_planner_meta(
            {
                "planner_class": self.planner.__class__.__name__,
                "planner_used": planner_used,
                "planner_error": planner_error,
                "case_name": self.case_name,
            }
        )

        self.debug_print(f"[PLANNER USED] {planner_used}")
        if planner_error:
            self.debug_print(f"[PLANNER ERROR] {planner_error}")
        self.debug_print(f"[PLANNER RAW OUTPUT] {planner_raw}")

        validation = self.validator.parse_llm_json(planner_raw)
        if not validation.ok or validation.tool_call is None:
            self.txlog.log_event("validation_failed", {"error": validation.error, "clarification": validation.clarification})
            self.debug_print(f"[VALIDATION FAILED] {validation.error}")

            self.results.clear_execution_artifacts()
            self.results.save_validation_error(
                {
                    "error": validation.error,
                    "clarification": validation.clarification,
                    "planner_raw": planner_raw,
                }
            )
            self.results.save_response(validation.clarification or "Unable to process request safely.")

            self.protocol.emit_response(validation.clarification or "Unable to process request safely.")
            return

        call = validation.tool_call
        self.txlog.log_event("validated_tool_call", {"tool": call.tool.value, "arguments": call.arguments})
        self.results.save_validated_tool(
            {
                "tool": call.tool.value,
                "arguments": call.arguments,
            }
        )

        self.debug_print(f"[VALIDATED TOOL] {call.tool.value}")
        self.debug_print(f"[TOOL ARGUMENTS] {call.arguments}")

        try:
            result = self.execute_tool_call(call)
        except Exception as exc:
            err_msg = f"Execution failed safely: {type(exc).__name__}: {exc}"
            self.txlog.log_event("execution_failed", {"tool": call.tool.value, "error": err_msg})
            self.debug_print(f"[EXECUTION FAILED] {err_msg}")

            self.results.save_execution_error(
                {
                    "tool": call.tool.value,
                    "arguments": call.arguments,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            self.results.save_response(err_msg)

            self.protocol.emit_response(err_msg)
            return

        self.txlog.log_event("execution_succeeded", {"tool": call.tool.value, "data": result.data})

        self.results.clear_error_files()
        self.results.save_tool_output_summary(result.summary)
        self.results.save_tool_output_data(result.data)
        self.results.save_response(result.summary)

        self.debug_print("[TOOL OUTPUT SUMMARY]")
        self.debug_print(result.summary)
        self.debug_print(f"[TOOL OUTPUT DATA] {result.data}")

        self.protocol.emit_response(result.summary)

    def execute_tool_call(self, call: ToolCall):
        if call.tool == ToolName.READ_NETLIST:
            return self.engine.read_netlist(call.arguments["path"])
        if call.tool == ToolName.WRITE_NETLIST:
            return self.engine.write_netlist(call.arguments["path"])
        if call.tool == ToolName.GET_FANOUT:
            return self.engine.get_fanout(call.arguments["node_or_net"])
        if call.tool == ToolName.GET_MAX_DEPTH:
            return self.engine.get_max_depth(call.arguments["source"], call.arguments["sink"])
        if call.tool == ToolName.FIND_PATH:
            return self.engine.find_path(call.arguments["source"], call.arguments["sink"], call.arguments.get("avoid"))
        if call.tool == ToolName.REMOVE_DANGLING_LOGIC:
            return self.engine.remove_dangling_logic()
        if call.tool == ToolName.CHECK_EXTERNAL_TOOLS:
            return self.engine.check_external_tools()
        if call.tool == ToolName.NORMALIZE_DESIGN:
            return self.engine.normalize_design()
        if call.tool == ToolName.CHECK_EQUIVALENCE:
            return self.engine.check_equivalence()
        if call.tool == ToolName.CHECK_MAX_FANOUT:
            return self.engine.check_max_fanout(call.arguments["max_fanout"])
        if call.tool == ToolName.INSERT_AND_BEFORE_BUFFERS:
            return self.engine.insert_and_before_buffers(call.arguments["pattern"], call.arguments["control_signal"])
        if call.tool == ToolName.OPTIMIZE_CONE:
            return self.engine.optimize_cone(
                call.arguments["output_signal"],
                call.arguments.get("max_depth"),
                call.arguments.get("minimize_gates", False)
            )
        if call.tool == ToolName.REPLACE_GATES:
            return self.engine.replace_gates(
                call.arguments["from_gate"],
                call.arguments["to_gate"],
                call.arguments.get("pattern")
            )
        if call.tool == ToolName.CLEAN_DANGLING_AND_WRITE:
            return self.engine.clean_dangling_and_write(
                call.arguments["input_path"],
                call.arguments["output_path"],
            )
        raise ValidationError(f"Unsupported validated tool call: {call.tool.value}")

    def run_stdin_loop(self) -> None:
        for line in sys.stdin:
            self.handle_line(line)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    config = load_config(args.config)
    planner = make_planner_from_config(
        config,
        no_llm=args.no_llm,
        require_llm=args.require_llm,
    )
    verification_policy = args.verification_policy or str(config.get("verification_policy", "permissive"))
    app = ICCADApp(planner=planner, debug=args.debug, verification_policy=verification_policy)
    app.run_stdin_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
