"""Compatibility handling for execution approvals in Codex Full access mode."""
from __future__ import annotations

from .base import RunRequest


def can_auto_approve(method: str, params: dict, request: RunRequest) -> bool:
    if not request.codex_auto_approve or method not in (
        "item/commandExecution/requestApproval", "item/fileChange/requestApproval"
    ):
        return False
    decisions = params.get("availableDecisions")
    return decisions is None or "accept" in decisions
