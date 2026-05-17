from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InterruptInfo:
    """Parsed interrupt from thread state."""

    interrupt_id: str
    value: Any
    task_id: str | None = None
    options: list[str] = field(default_factory=list)
    description: str = ""
    detail: str = ""

    @property
    def has_options(self) -> bool:
        return len(self.options) > 0


def extract_interrupts(thread_state: dict) -> list[InterruptInfo]:
    """Extract pending interrupts from a thread state response.

    The thread state may expose interrupts at:
    - state["interrupts"] — top-level list
    - state["tasks"][*]["interrupts"] — per-task interrupts
    """
    interrupts: list[InterruptInfo] = []

    # Per-task interrupts (more common in Deep Agents)
    for task in thread_state.get("tasks", []):
        task_id = task.get("id")
        for raw in task.get("interrupts", []):
            interrupts.append(_parse_interrupt(raw, task_id))

    # Top-level interrupts fallback
    if not interrupts:
        for raw in thread_state.get("interrupts", []):
            interrupts.append(_parse_interrupt(raw, None))

    return interrupts


def _parse_interrupt(raw: dict, task_id: str | None) -> InterruptInfo:
    """Parse a single interrupt dict into an InterruptInfo."""
    interrupt_id = raw.get("id", "")
    value = raw.get("value", {})

    description = ""
    detail = ""
    options: list[str] = []

    if isinstance(value, dict):
        if _is_hitl_middleware_interrupt(value):
            # HumanInTheLoopMiddleware format:
            # {"action_requests": [{"name": "edit_file", "args": {...}}],
            #  "review_configs": [{"action_name": "edit_file", "allowed_decisions": [...]}]}
            import json

            action_requests = value.get("action_requests", [])
            review_configs = value.get("review_configs", [])
            names = [ar.get("name", "") for ar in action_requests]
            description = ", ".join(names) if names else "Action required"

            # Build detail from args of each action request
            detail_parts = []
            for ar in action_requests:
                args = ar.get("args", {})
                if args:
                    detail_parts.append(
                        f"{ar.get('name', '')}: {json.dumps(args, indent=2, ensure_ascii=False)}"
                    )
                ar_desc = ar.get("description")
                if ar_desc:
                    detail_parts.append(ar_desc)
            detail = "\n\n".join(detail_parts)

            # Extract allowed decisions from review configs
            if review_configs:
                allowed = review_configs[0].get("allowed_decisions", [])
                options = [str(d) for d in allowed] if allowed else []
        else:
            # Generic interrupt shapes:
            # {"question": "...", "options": [...]}
            # {"type": "approve", "tool_name": "...", "args": {...}}
            description = (
                value.get("question")
                or value.get("description")
                or value.get("message")
                or value.get("action")
                or value.get("type")
                or ""
            )
            detail = (
                value.get("diff")
                or value.get("detail")
                or value.get("content")
                or value.get("path")
                or ""
            )
            if isinstance(detail, dict):
                import json

                detail = json.dumps(detail, indent=2, ensure_ascii=False)

            raw_options = value.get("options", [])
            if isinstance(raw_options, list):
                options = [str(o) for o in raw_options]
    elif isinstance(value, str):
        description = value
    else:
        description = str(value)

    # Default options if none provided
    if not options:
        options = ["approve", "reject"]

    return InterruptInfo(
        interrupt_id=interrupt_id,
        value=value,
        task_id=task_id,
        options=options,
        description=description,
        detail=detail,
    )


def _is_hitl_middleware_interrupt(value: Any) -> bool:
    """Check if interrupt value originates from HumanInTheLoopMiddleware.

    HITLRequest has "action_requests" (list of ActionRequest) and
    "review_configs" (list of ReviewConfig).
    """
    if not isinstance(value, dict):
        return False
    return "action_requests" in value and "review_configs" in value


def build_resume_value(interrupt: InterruptInfo, choice: str, edited_content: str | None = None):
    """Build the resume value to send back to the server.

    The resume value format depends on the interrupt's original value structure.
    For HumanInTheLoopMiddleware interrupts, the resume must use the structured
    HITLResponse format: {"decisions": [{"type": "approve|reject|edit", ...}]}
    with one decision per action_request.
    """
    if _is_hitl_middleware_interrupt(interrupt.value):
        action_requests = interrupt.value.get("action_requests", [])
        num_actions = max(len(action_requests), 1)

        if edited_content is not None and choice == "edit":
            # For edit, rebuild each action with edited args
            decisions: list[dict[str, Any]] = []
            for ar in action_requests:
                decisions.append({
                    "type": "edit",
                    "edited_action": {
                        "name": ar.get("name", ""),
                        "args": {**ar.get("args", {}), "content": edited_content},
                    },
                })
            if not decisions:
                decisions = [{"type": "edit"}]
        elif choice in ("reject", "deny", "no"):
            decision: dict[str, Any] = {"type": "reject"}
            if edited_content:
                decision["message"] = edited_content
            decisions = [decision] * num_actions
        else:
            # approve / accept / yes
            decisions = [{"type": "approve"}] * num_actions

        return {"decisions": decisions}

    # Non-HITL-middleware interrupts: preserve legacy behavior
    if edited_content is not None:
        if isinstance(interrupt.value, dict):
            return {**interrupt.value, "action": choice, "content": edited_content}
        return edited_content

    return choice


def open_in_editor(content: str, suffix: str = ".txt") -> str | None:
    """Open content in the user's $EDITOR for editing.

    Returns the edited content, or None if the user cancelled (empty file).
    """
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(content)
        tmp_path = f.name

    try:
        result = subprocess.run([editor, tmp_path], check=False)
        if result.returncode != 0:
            return None
        with open(tmp_path) as f:
            edited = f.read()
        return edited if edited.strip() else None
    finally:
        os.unlink(tmp_path)
