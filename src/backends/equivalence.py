from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from external_tools import ABCBridge, ToolRunResult


@dataclass
class EquivalenceOutcome:
    equivalent: Optional[bool]
    method: str
    summary: str
    details: Dict[str, Any]


class ABCEquivalenceBackend:
    """ABC miter/prove equivalence backend over BLIF inputs."""

    def __init__(self, bridge: Optional[ABCBridge] = None) -> None:
        self.bridge = bridge or ABCBridge()

    def available(self) -> bool:
        return self.bridge.available()

    def version(self) -> Optional[str]:
        return self.bridge.version()

    def check_blif(self, reference_blif: str, current_blif: str) -> EquivalenceOutcome:
        result: ToolRunResult = self.bridge.check_equivalence_blif(reference_blif, current_blif)
        if result.ok and "proved" in result.stdout.lower():
            return EquivalenceOutcome(
                equivalent=True,
                method="abc_miter_prove",
                summary="Equivalence check passed: designs are functionally equivalent.",
                details={"stdout": result.stdout, "stderr": result.stderr},
            )
        if result.ok:
            return EquivalenceOutcome(
                equivalent=None,
                method="abc_miter_inconclusive",
                summary="Equivalence check inconclusive. (ABC completed but could not prove equivalence)",
                details={"stdout": result.stdout, "stderr": result.stderr},
            )
        return EquivalenceOutcome(
            equivalent=False,
            method="abc_miter_error",
            summary=f"Equivalence check failed: {result.stderr}",
            details={"stdout": result.stdout, "stderr": result.stderr},
        )
