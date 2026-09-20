from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class ToolRunResult:
    command: List[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class ExternalToolRunner:
    """Safe bounded wrapper around external EDA executables."""

    def run(self, command: List[str], timeout_sec: int = 30, cwd: Optional[str] = None) -> ToolRunResult:
        proc = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
        return ToolRunResult(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


class YosysBridge:
    def __init__(self, executable: str = "yosys", runner: Optional[ExternalToolRunner] = None) -> None:
        self.executable = executable
        self.runner = runner or ExternalToolRunner()

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def version(self) -> Optional[str]:
        if not self.available():
            return None
        result = self.runner.run([self.executable, "-V"], timeout_sec=10)
        return (result.stdout or result.stderr).strip() if result.ok else None

    def normalize_verilog(self, input_v: str, output_v: str, top: Optional[str] = None) -> ToolRunResult:
        """Normalize Verilog while preserving gate-level format."""
        script = [f"read_verilog {input_v}"]
        if top:
            script.append(f"hierarchy -check -top {top}")
        else:
            script.append("hierarchy -check")
        # Flatten and optimize while keeping gates
        script.extend([
            "proc",
            "opt",
            "flatten",
            "opt",
            # Don't use techmap, just output remaining gates
            f"write_verilog -noattr {output_v}"
        ])
        return self.runner.run([self.executable, "-p", "; ".join(script)], timeout_sec=60)

    def write_blif(self, input_v: str, output_blif: str, top: Optional[str] = None) -> ToolRunResult:
        script = [f"read_verilog {input_v}"]
        if top:
            script.append(f"hierarchy -check -top {top}")
        else:
            script.append("hierarchy -check")
        script.extend(["proc", "opt", f"write_blif {output_blif}"])
        return self.runner.run([self.executable, "-p", "; ".join(script)], timeout_sec=60)

    def write_json(self, input_v: str, output_json: str, top: Optional[str] = None) -> ToolRunResult:
        """Export Yosys's netlist JSON without optimization so frontend parsing preserves intent."""
        script = [f"read_verilog {input_v}"]
        if top:
            script.append(f"hierarchy -check -top {top}")
        else:
            script.append("hierarchy -check")
        script.extend(["proc", f"write_json {output_json}"])
        return self.runner.run([self.executable, "-p", "; ".join(script)], timeout_sec=60)


class ABCBridge:
    def __init__(self, executable: str = "abc", runner: Optional[ExternalToolRunner] = None) -> None:
        self.executable = executable
        self.runner = runner or ExternalToolRunner()

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def version(self) -> Optional[str]:
        if not self.available():
            return None
        result = self.runner.run([self.executable, "-h"], timeout_sec=10)
        text = (result.stdout or result.stderr).strip()
        return text.splitlines()[0] if text else None

    def run_script(self, script: str, timeout_sec: int = 60) -> ToolRunResult:
        return self.runner.run([self.executable, "-c", script], timeout_sec=timeout_sec)

    def simple_rewrite(self, input_blif: str, output_blif: str) -> ToolRunResult:
        script = f"read_blif {input_blif}; strash; rewrite; balance; write_blif {output_blif}"
        return self.run_script(script, timeout_sec=120)

    def optimize_blif(self, input_blif: str, output_blif: str, timeout_sec: int = 180) -> ToolRunResult:
        """Comprehensive ABC optimization: strash, rewrite, refactor, balance."""
        script = f"read_blif {input_blif}; strash; rewrite; refactor; balance; write_blif {output_blif}"
        return self.run_script(script, timeout_sec=timeout_sec)

    def check_equivalence_blif(self, original_blif: str, modified_blif: str) -> ToolRunResult:
        """Check equivalence between two BLIF files using ABC's miter."""
        script = f"read_blif {original_blif}; read_blif {modified_blif}; miter -c; prove"
        return self.run_script(script, timeout_sec=120)
