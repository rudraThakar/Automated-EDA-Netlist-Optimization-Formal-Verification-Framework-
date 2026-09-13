from __future__ import annotations


class BasePlanner:
    """Planner interface. Implementations must return a JSON tool call string."""

    def plan(self, user_request: str) -> str:
        raise NotImplementedError
