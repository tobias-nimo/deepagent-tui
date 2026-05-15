from __future__ import annotations

import argparse
import asyncio
import json
import sys

import deepagent_repl.commands.builtins  # noqa: F401
import deepagent_repl.commands.export  # noqa: F401
import deepagent_repl.commands.image  # noqa: F401
import deepagent_repl.commands.new  # noqa: F401
import deepagent_repl.commands.fork  # noqa: F401
import deepagent_repl.commands.resume  # noqa: F401
import deepagent_repl.commands.skills  # noqa: F401
import deepagent_repl.commands.theme  # noqa: F401
import deepagent_repl.commands.threads  # noqa: F401
from deepagent_repl.client import AgentClient
from deepagent_repl.commands import clear_dynamic, is_command, register_skill
from deepagent_repl.commands import dispatch as dispatch_command
from deepagent_repl.config import settings
from deepagent_repl.handlers.interrupt import (
    InterruptInfo,
    build_resume_value,
    extract_interrupts,
    open_in_editor,
)
from deepagent_repl.handlers.stream import (
    StreamState,
    process_messages_event,
    process_updates_event,
)
from deepagent_repl.handlers.tools import format_tool_call, format_tool_result
from deepagent_repl.session import Session
from deepagent_repl.storage.db import upsert_thread
import deepagent_repl.ui.theme as _theme
from deepagent_repl.ui.prompt import create_prompt_session, read_input
from deepagent_repl.ui.renderer import (
    StreamingRenderer,
    console,
    render_assistant_text,
    render_error,
    render_header,
    render_info,
    render_interrupt,
    render_interrupt_panel,
    render_shortcut_hint,
    render_tool_call,
    render_tool_result,
    render_user_message,
)
from deepagent_repl.ui.toolbar import create_toolbar


async def connect(client: AgentClient, session: Session) -> bool:
    """Connect to the server, discover assistant, create thread. Returns True on success."""
    try:
        assistants = await client.discover_assistants()
    except Exception as e:
        render_error(f"Cannot connect to {settings.langgraph_url}: {e}")
        return False

    if not assistants:
        render_error("No assistants found on server.")
        return False

    if settings.graph_id:
        matches = [a for a in assistants if a["graph_id"] == settings.graph_id]
        if not matches:
            available = ", ".join(a["graph_id"] for a in assistants)
            render_error(f"Graph '{settings.graph_id}' not found. Available: {available}")
            return False
        assistant = matches[0]
    elif len(assistants) == 1:
        assistant = assistants[0]
    else:
        render_info("Multiple assistants found:")
        for i, a in enumerate(assistants, 1):
            render_info(f"  [{i}] {a['graph_id']} (id: {a['assistant_id'][:8]}...)")
        try:
            choice = int(input("Select assistant number: ")) - 1
            assistant = assistants[choice]
        except (ValueError, IndexError):
            render_error("Invalid selection.")
            return False

    session.assistant_id = assistant["assistant_id"]
    session.graph_id = assistant["graph_id"]

    if settings.thread_id:
        session.thread_id = settings.thread_id
    else:
        session.thread_id = await client.create_thread()

    # Record thread in local index
    await upsert_thread(session.thread_id, session.graph_id or "")

    return True


def _register_skill_command(name: str, desc: str, path: str) -> None:
    """Register a skill as a dynamic slash command.

    When invoked as /skill-name <question>, the agent is told to read the
    SKILL.md file and follow its instructions to answer the question.
    """

    def _make_handler(skill_name: str, skill_path: str):
        async def handler(c: AgentClient, s: Session, args: str) -> None:
            if skill_path:
                prompt = (
                    f"Read the skill instructions from `{skill_path}` "
                    f"and follow them"
                )
            else:
                prompt = f"Use the {skill_name} skill"
            if args:
                prompt += f" to: {args}"
            await handle_stream(c, s, prompt)

        return handler

    register_skill(name, desc, _make_handler(name, path))


async def discover_and_register_skills(client: AgentClient, session: Session) -> None:
    """Discover skills from the connected server and register as dynamic slash commands."""
    clear_dynamic()

    if not session.assistant_id:
        return

    try:
        skills = await client.discover_skills(session.assistant_id)
    except Exception:
        skills = []

    for skill in skills:
        name = skill.get("name", "")
        desc = skill.get("description", "")
        path = skill.get("path", "")
        if not name:
            continue
        _register_skill_command(name, desc, path)

    if skills:
        render_info(f"Discovered {len(skills)} skill(s) from server metadata. Type /skills to list.")


def _flush_usage(state: StreamState, session: Session) -> None:
    """Transfer accumulated token usage from a stream state into the session."""
    if state.total_input_tokens or state.total_output_tokens:
        session.add_usage(state.total_input_tokens, state.total_output_tokens)
    if state.model and not session.model:
        session.model = state.model

    # Collect tool names observed during this stream
    _internal = {
        "__interrupt", "human", "todo_list", "TodoList",
        "manage_todos", "ask_human", "ask_user",
    }
    for tc in state.tool_calls:
        name = tc.get("name", "")
        if name and not name.startswith("_") and name not in _internal:
            if name not in session.discovered_tools:
                session.discovered_tools[name] = ""


async def _consume_stream(stream, state: StreamState, renderer: StreamingRenderer) -> None:
    """Consume a stream of events, updating the renderer and state."""
    async for chunk in stream:
        event_type = chunk.event
        data = chunk.data

        if event_type == "messages/partial":
            text_fragment = process_messages_event(data, state)
            if text_fragment:
                renderer.update(text_fragment)

        elif event_type == "updates" and isinstance(data, dict):
            # Finish live display (transient — vanishes on stop)
            accumulated = renderer.finish()
            if accumulated.strip():
                render_assistant_text(accumulated)
                state.text_buffer = ""

            messages = process_updates_event(data, state)
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_type = msg.get("type")

                if msg_type == "ai":
                    # Render text content if it wasn't already shown via streaming
                    from deepagent_repl.handlers.stream import extract_text_content

                    ai_text = extract_text_content(msg.get("content", ""))
                    if ai_text.strip() and ai_text.strip() != accumulated.strip():
                        render_assistant_text(ai_text)

                    for tc in msg.get("tool_calls", []):
                        render_tool_call(format_tool_call(tc))

                elif msg_type == "tool":
                    render_tool_result(format_tool_result(msg))

            # Restart live display for continued streaming
            renderer.start()


async def _select_option_interactive(options: list[str]) -> str | None:
    """Interrupt-aware wrapper: colours approve/reject options appropriately."""
    from prompt_toolkit import Application
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.key_binding import KeyBindings

    selected = [0]
    kb = KeyBindings()

    @kb.add("up")
    @kb.add("c-p")
    def _up(event):
        selected[0] = (selected[0] - 1) % len(options)
        event.app.invalidate()

    @kb.add("down")
    @kb.add("c-n")
    def _down(event):
        selected[0] = (selected[0] + 1) % len(options)
        event.app.invalidate()

    @kb.add("enter")
    def _enter(event):
        event.app.exit()

    @kb.add("c-c")
    def _cancel(event):
        selected[0] = -1
        event.app.exit()

    def get_tokens():
        tokens = []
        for i, opt in enumerate(options):
            if i == selected[0]:
                if opt in ("approve", "accept", "yes"):
                    style = "bold fg:ansigreen"
                elif opt in ("reject", "deny", "no"):
                    style = "bold fg:ansired"
                else:
                    style = f"bold {_theme.accent_ptk()}"
                tokens.append((style, f"  ❯ {opt}"))
            else:
                tokens.append(("fg:ansibrightblack", f"    {opt}"))
            tokens.append(("", "\n"))
        return tokens

    app = Application(
        layout=Layout(Window(FormattedTextControl(get_tokens))),
        key_bindings=kb,
        full_screen=False,
        mouse_support=False,
    )
    await app.run_async()

    if selected[0] == -1:
        return None
    return options[selected[0]]


async def _prompt_interrupt(
    interrupt: InterruptInfo, prompt_session,
) -> tuple[str, str | None]:
    """Display an interrupt and get the user's choice.

    Returns (chosen_option, edited_content_or_None).
    Uses an arrow-key selector in interactive TTY sessions,
    or falls back to number/name text input otherwise.
    """
    is_interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if is_interactive:
        render_interrupt_panel(interrupt)
        while True:
            chosen = await _select_option_interactive(interrupt.options)
            if chosen is None:
                return "reject", None

            edited_content = None
            if chosen.lower() in ("edit", "modify"):
                content = interrupt.detail or ""
                edited_content = open_in_editor(content)
                if edited_content is None:
                    render_info("Edit cancelled.")
                    continue

            return chosen, edited_content

    # Non-interactive fallback: static options + text input
    render_interrupt(interrupt)

    while True:
        try:
            raw = await read_input(prompt_session, prompt_text="❯")
        except KeyboardInterrupt:
            return "reject", None

        if raw is None:
            return "reject", None

        raw = raw.strip()
        if not raw:
            continue

        try:
            idx = int(raw) - 1
            if 0 <= idx < len(interrupt.options):
                chosen = interrupt.options[idx]
            else:
                render_error(f"Choose 1-{len(interrupt.options)}")
                continue
        except ValueError:
            lower = raw.lower()
            matched = [o for o in interrupt.options if o.lower().startswith(lower)]
            if len(matched) == 1:
                chosen = matched[0]
            else:
                render_error(f"Choose 1-{len(interrupt.options)} or type option name")
                continue

        edited_content = None
        if chosen.lower() in ("edit", "modify"):
            content = interrupt.detail or ""
            edited_content = open_in_editor(content)
            if edited_content is None:
                render_info("Edit cancelled.")
                continue

        return chosen, edited_content


async def handle_stream(
    client: AgentClient, session: Session, user_input: str | list,
) -> None:
    """Send a message and process the streamed response, handling HITL interrupts.

    user_input can be a plain string or a multimodal content list (for images).
    """
    # Echo user message with distinct styling
    if isinstance(user_input, str):
        render_user_message(user_input)
    else:
        # Multimodal — extract text parts for echo
        text_parts = [c.get("text", "") for c in user_input if isinstance(c, dict) and c.get("type") == "text"]
        if text_parts:
            render_user_message("\n".join(text_parts))

    session.status = "streaming"
    session.messages.append({"role": "user", "content": user_input})
    state = StreamState()
    renderer = StreamingRenderer()
    renderer.start()
    prompt_session = session.prompt_session

    try:
        # Initial message
        stream = client.stream_message(session.thread_id, session.assistant_id, user_input)
        await _consume_stream(stream, state, renderer)
        _flush_usage(state, session)

        # Finalize buffered text
        final_text = renderer.finish()
        if final_text.strip():
            render_assistant_text(final_text)

        # Check for interrupts and handle resume loop
        while True:
            try:
                thread_state = await client.get_thread_state(session.thread_id)
            except Exception:
                break

            interrupts = extract_interrupts(thread_state)
            if not interrupts:
                break

            # Handle each interrupt (typically just one)
            rejected = False
            for interrupt in interrupts:
                session.status = "interrupted"

                chosen, edited = await _prompt_interrupt(interrupt, prompt_session)

                if chosen.lower() in ("reject", "deny", "no"):
                    rejected = True

                resume_value = build_resume_value(interrupt, chosen, edited)
                render_info(f"Resuming with: {chosen}")

                # Resume and stream continuation
                session.status = "streaming"
                state = StreamState()
                renderer = StreamingRenderer()
                renderer.start()

                resume_stream = client.resume(
                    session.thread_id, session.assistant_id, resume_value
                )
                await _consume_stream(resume_stream, state, renderer)
                _flush_usage(state, session)

                final_text = renderer.finish()
                if final_text.strip():
                    render_assistant_text(final_text)

                if rejected:
                    render_info("Interrupted · What should the agent do instead?")
                    break

            if rejected:
                break

    except Exception as e:
        renderer.finish()
        render_error(f"Stream error: {e}")
    finally:
        session.status = "idle"
        # Add visual separation before the next prompt
        console.print()

        # Discover skills from thread state (Deep Agents SkillsMiddleware
        # stores skills_metadata in state after the first agent turn)
        if not session.discovered_skills_from_state:
            try:
                skills_from_state = await client.get_skills_from_state(session.thread_id)
                if skills_from_state:
                    session.discovered_skills_from_state = True
                    for skill in skills_from_state:
                        name = skill.get("name", "")
                        desc = skill.get("description", "")
                        path = skill.get("path", "")
                        if name:
                            session.discovered_tools[name] = desc
                            _register_skill_command(name, desc, path)
                            # Derive workspace root from first skill path:
                            # path looks like <root>/.claude/skills/<name>/SKILL.md
                            if not session.workspace_root and path:
                                from pathlib import Path as _Path
                                try:
                                    session.workspace_root = str(_Path(path).parents[3])
                                except IndexError:
                                    pass
            except Exception:
                pass

        # Update thread metadata in local index
        try:
            if isinstance(user_input, str):
                preview = user_input[:100]
            else:
                # Multimodal content — extract text part for preview
                text_parts = [
                    c.get("text", "") for c in user_input
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                preview = (" ".join(text_parts))[:100] if text_parts else "[image]"
            await upsert_thread(
                session.thread_id,
                session.graph_id or "",
                last_message=preview,
                message_count=len(session.messages) + 1,
            )
        except Exception:
            pass


async def run() -> None:
    """Main async entry point."""
    client = AgentClient(url=settings.langgraph_url, api_key=settings.langsmith_api_key)
    session = Session()
    toolbar = create_toolbar(session)
    prompt_session = create_prompt_session(bottom_toolbar=toolbar)
    session.prompt_session = prompt_session

    render_info(f"Connecting to {settings.langgraph_url}...")

    if not await connect(client, session):
        sys.exit(1)

    # Discover skills from the server (non-blocking, best-effort)
    await discover_and_register_skills(client, session)

    render_header(
        graph_id=session.graph_id,
        server_url=settings.langgraph_url,
        thread_id=session.thread_id,
        num_skills=len(session.discovered_tools),
    )
    console.print()
    render_shortcut_hint()
    console.print()

    while True:
        try:
            user_input = await read_input(prompt_session)
        except KeyboardInterrupt:
            continue

        if user_input is None:
            render_info("\nGoodbye!")
            break

        text = user_input.strip()
        if not text:
            continue

        # Dispatch slash commands before sending to server
        if is_command(text):
            handled = await dispatch_command(client, session, text)
            if handled:
                continue
            # Check if the skill/command exists
            from deepagent_repl.commands import dynamic_commands
            parts = text[1:].split(None, 1)
            skill_name = parts[0] if parts else text[1:]
            skill_args = parts[1] if len(parts) > 1 else ""

            available_skills = dynamic_commands()
            if skill_name not in available_skills:
                render_info(f"Unknown skill or invalid command: /{skill_name}")
                continue

            # Unknown slash command — forward to agent as a skill invocation
            prompt = f"Use the {skill_name} skill"
            if skill_args:
                prompt += f": {skill_args}"
            render_info(f"Invoking skill: {skill_name}")
            await handle_stream(client, session, prompt)
            continue

        # Auto-detect image paths in text and convert to multimodal
        from deepagent_repl.utils.images import build_multimodal_content, detect_image_paths

        image_paths = detect_image_paths(text)
        if image_paths:
            content = build_multimodal_content(text, image_paths)
            render_info(f"Detected {len(image_paths)} image(s), sending as multimodal.")
            await handle_stream(client, session, content)
        else:
            await handle_stream(client, session, text)


async def run_oneshot(message: str, *, output_json: bool = False, no_stream: bool = False) -> int:
    """One-shot mode: send a single message, print response, exit.

    Returns exit code: 0 success, 1 error, 2 interrupt.
    """
    client = AgentClient(url=settings.langgraph_url, api_key=settings.langsmith_api_key)
    session = Session()

    if not await connect(client, session):
        return 1

    if output_json:
        # Non-streaming: send and collect full response
        try:
            result = await client.send_message(
                session.thread_id, session.assistant_id, message
            )
            messages = result.get("messages", [])
            # Find the last AI message
            for msg in reversed(messages):
                if msg.get("type") == "ai" or msg.get("role") == "assistant":
                    print(json.dumps(msg, ensure_ascii=False, indent=2))
                    return 0
            print(json.dumps({"error": "No response"}, indent=2))
            return 1
        except Exception as e:
            print(json.dumps({"error": str(e)}, indent=2))
            return 1

    if no_stream:
        # Non-streaming plain text output
        try:
            result = await client.send_message(
                session.thread_id, session.assistant_id, message
            )
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if msg.get("type") == "ai" or msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            c.get("text", "") for c in content if isinstance(c, dict)
                        )
                    print(content)
                    return 0
            return 1
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Streaming mode (default for one-shot)
    try:
        await handle_stream(client, session, message)
        return 0
    except KeyboardInterrupt:
        return 2
    except Exception as e:
        render_error(str(e))
        return 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="deepagent-repl",
        description="Terminal REPL for any LangChain Deep Agent server",
    )
    parser.add_argument("message", nargs="?", default=None, help="One-shot message to send")
    parser.add_argument("--json", action="store_true", dest="output_json", help="Output raw JSON")
    parser.add_argument(
        "--no-stream", action="store_true", help="Disable streaming (clean output)"
    )
    parser.add_argument(
        "--tui", action="store_true", help="Launch the Textual TUI front-end (experimental)"
    )
    return parser.parse_args()


def main() -> None:
    """Synchronous entry point for the CLI."""
    args = _parse_args()

    # Check for piped stdin
    message = args.message
    if message is None and not sys.stdin.isatty():
        message = sys.stdin.read().strip()

    try:
        if message:
            code = asyncio.run(
                run_oneshot(message, output_json=args.output_json, no_stream=args.no_stream)
            )
            sys.exit(code)
        elif args.tui:
            from deepagent_repl.tui import run_tui

            run_tui()
        else:
            asyncio.run(run())
    except KeyboardInterrupt:
        pass
