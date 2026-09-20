from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class ResultsLogger:
    """
    Writes the most recent internal artifacts into results/ at project root.
    This is for debugging only and does not affect contest stdout protocol.
    """

    def __init__(self, root_dir: str = ".") -> None:
        self.root = Path(root_dir).resolve()
        self.results_dir = self.root / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def _write_text(self, filename: str, text: str) -> None:
        (self.results_dir / filename).write_text(text, encoding="utf-8")

    def _write_json(self, filename: str, payload: Dict[str, Any]) -> None:
        (self.results_dir / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def save_user_request(self, text: str) -> None:
        self._write_text("latest_user_request.txt", text)

    def save_planner_raw(self, text: str) -> None:
        self._write_text("latest_planner_raw.txt", text)

    def save_planner_meta(self, payload: Dict[str, Any]) -> None:
        self._write_json("latest_planner_meta.json", payload)

    def save_validated_tool(self, payload: Dict[str, Any]) -> None:
        self._write_json("latest_validated_tool.json", payload)

    def save_tool_output_summary(self, text: str) -> None:
        self._write_text("latest_tool_output_summary.txt", text)

    def save_tool_output_data(self, payload: Dict[str, Any]) -> None:
        self._write_json("latest_tool_output_data.json", payload)

    def save_validation_error(self, payload: Dict[str, Any]) -> None:
        self._write_json("latest_validation_error.json", payload)

    def save_execution_error(self, payload: Dict[str, Any]) -> None:
        self._write_json("latest_execution_error.json", payload)

    def save_response(self, text: str) -> None:
        self._write_text("latest_response.txt", text)

    def clear_error_files(self) -> None:
        for name in ["latest_validation_error.json", "latest_execution_error.json"]:
            path = self.results_dir / name
            if path.exists():
                path.unlink()

    def clear_execution_artifacts(self) -> None:
        for name in [
            "latest_validated_tool.json",
            "latest_tool_output_summary.txt",
            "latest_tool_output_data.json",
            "latest_execution_error.json",
        ]:
            path = self.results_dir / name
            if path.exists():
                path.unlink()
