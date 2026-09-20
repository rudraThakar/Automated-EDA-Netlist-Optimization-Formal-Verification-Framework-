from __future__ import annotations

from pathlib import Path
from typing import Optional

from external_tools import ToolRunResult, YosysBridge


class YosysBackend:
    """Backend facade for Yosys operations used by the orchestration engine."""

    def __init__(self, bridge: Optional[YosysBridge] = None) -> None:
        self.bridge = bridge or YosysBridge()

    def available(self) -> bool:
        return self.bridge.available()

    def version(self) -> Optional[str]:
        return self.bridge.version()

    def frontend_json(self, input_v: str, output_json: str, top: Optional[str] = None) -> ToolRunResult:
        return self.bridge.write_json(input_v, output_json, top=top)

    def normalize(self, input_v: str, output_v: str, top: Optional[str] = None) -> ToolRunResult:
        return self.bridge.normalize_verilog(input_v, output_v, top=top)

    def clean_unused_logic(self, input_v: str, output_v: str, top: Optional[str] = None) -> ToolRunResult:
        script = [f"read_verilog {input_v}"]
        if top:
            script.append(f"hierarchy -check -top {top}")
        else:
            script.append("hierarchy -check")
        script.extend(["proc", "opt_clean", "clean", f"write_verilog -noattr {output_v}"])
        return self.bridge.runner.run([self.bridge.executable, "-p", "; ".join(script)], timeout_sec=60)

    def write_blif(self, input_v: str, output_blif: str, top: Optional[str] = None) -> ToolRunResult:
        return self.bridge.write_blif(input_v, output_blif, top=top)
