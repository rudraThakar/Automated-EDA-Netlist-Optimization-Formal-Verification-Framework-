from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, TextIO


class ProtocolError(RuntimeError):
    """Raised when protocol invariants are violated."""


class CaseLogger:
    """Writes all protocol responses to <case_name>.log."""

    def __init__(self) -> None:
        self.case_name: Optional[str] = None
        self.log_path: Optional[Path] = None

    def initialize(self, case_name: str) -> None:
        self.case_name = case_name
        self.log_path = Path(f"{case_name}.log")
        self.log_path.write_text("", encoding="utf-8")

    def write_block(self, response_id: int, body: str) -> None:
        if self.log_path is None:
            raise ProtocolError("Attempted to log before testcase initialization.")
        block = f"#RESPONSE {response_id}\n{body}\n#END {response_id}\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(block)


class ProtocolManager:
    """Only gateway for emitting contest responses to stdout."""

    def __init__(self, case_logger: CaseLogger, stdout: Optional[TextIO] = None) -> None:
        self._next_response_id = 1
        self.case_logger = case_logger
        self.stdout = stdout if stdout is not None else sys.stdout

    @property
    def next_response_id(self) -> int:
        return self._next_response_id

    def emit_response(self, body: str) -> int:
        response_id = self._next_response_id
        framed = f"#RESPONSE {response_id}\n{body}\n#END {response_id}\n"
        self.stdout.write(framed)
        self.stdout.flush()
        self.case_logger.write_block(response_id, body)
        self._next_response_id += 1
        return response_id

    def emit_ack_case_start(self, case_name: str) -> int:
        body = (
            f'Acknowledged. Initialized testcase "{case_name}". '
            f'All subsequent responses will be recorded to {case_name}.log.\n'
            f'Design state is empty and ready for commands.'
        )
        return self.emit_response(body)
