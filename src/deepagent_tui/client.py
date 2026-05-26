from __future__ import annotations

from typing import Any

from langgraph_sdk import get_client


class AgentClient:
    """Thin wrapper around the LangGraph SDK async client."""

    def __init__(self, url: str, api_key: str | None = None):
        self._client = get_client(url=url, api_key=api_key)

    async def discover_assistants(self) -> list[dict]:
        """List all assistants available on the server."""
        return await self._client.assistants.search()

    async def create_thread(self) -> str:
        """Create a new thread and return its ID."""
        thread = await self._client.threads.create()
        return thread["thread_id"]

    async def get_thread_state(self, thread_id: str) -> dict:
        """Get the current state of a thread."""
        return await self._client.threads.get_state(thread_id)

    async def stream_message(
        self, thread_id: str, assistant_id: str, content: str | list,
    ):
        """Stream a run, yielding (event_type, data) tuples.

        content can be a plain string or a multimodal content list (for images).

        Uses stream_mode=["updates", "messages"] so we get both node-level updates
        (for tool call visibility) and token-level message chunks (for streaming text).
        """
        input_data = {"messages": [{"role": "user", "content": content}]}
        async for chunk in self._client.runs.stream(
            thread_id=thread_id,
            assistant_id=assistant_id,
            input=input_data,
            stream_mode=["updates", "messages"],
            stream_subgraphs=True,
        ):
            yield chunk

    async def get_graph(self, graph_id: str) -> dict:
        """Fetch graph metadata (nodes, edges, config schema, etc.)."""
        return await self._client.assistants.get_graph(
            assistant_id=graph_id,
        )

    async def discover_skills(self, assistant_id: str) -> list[dict]:
        """Discover available skills from a Deep Agent server.

        Checks assistant metadata for skills/tools lists.
        Returns a list of dicts with 'name' and 'description' keys.
        """
        skills: list[dict] = []

        try:
            assistants = await self._client.assistants.search()
            for a in assistants:
                if a.get("assistant_id") == assistant_id:
                    meta = a.get("metadata", {}) or {}
                    for key in ("skills", "tools"):
                        for s in meta.get(key, []):
                            if isinstance(s, dict) and s.get("name"):
                                skills.append({
                                    "name": s["name"],
                                    "description": s.get("description", ""),
                                })
                            elif isinstance(s, str):
                                skills.append({"name": s, "description": ""})
                    break
        except Exception:
            pass

        return skills

    async def get_skills_from_state(self, thread_id: str) -> list[dict]:
        """Extract skills_metadata from thread state.

        Deep Agents' SkillsMiddleware stores loaded skill metadata in the
        graph state after the first agent turn. This reads it from the
        thread checkpoint.

        Returns a list of dicts with 'name', 'description', and 'path' keys.
        """
        try:
            state = await self.get_thread_state(thread_id)
            values = state.get("values", {})
            skills_metadata = values.get("skills_metadata", [])
            if isinstance(skills_metadata, list):
                return [
                    s for s in skills_metadata
                    if isinstance(s, dict) and s.get("name")
                ]
        except Exception:
            pass
        return []

    async def send_message(self, thread_id: str, assistant_id: str, content: str) -> dict:
        """Send a message and wait for the full response (non-streaming).

        Returns the final thread state values.
        """
        input_data = {"messages": [{"role": "user", "content": content}]}
        await self._client.runs.wait(
            thread_id=thread_id,
            assistant_id=assistant_id,
            input=input_data,
        )
        state = await self.get_thread_state(thread_id)
        return state.get("values", {})

    async def copy_thread_with_messages(
        self, messages: list[dict], graph_id: str | None = None,
    ) -> str:
        """Create a new thread pre-loaded with the given messages.

        graph_id must be set so update_state can merge against the right graph;
        otherwise the server rejects the patch with "no assigned graph ID".
        """
        thread = await self._client.threads.create(graph_id=graph_id or None)
        thread_id = thread["thread_id"]
        await self._client.threads.update_state(
            thread_id=thread_id,
            values={"messages": messages},
        )
        return thread_id

    async def get_thread_history(self, thread_id: str, limit: int = 50) -> list[dict]:
        """Fetch the checkpoint history for a thread.

        Returns a list of state snapshots, most recent first.
        Each entry has 'checkpoint', 'values', 'next', 'metadata', etc.
        """
        return await self._client.threads.get_history(thread_id, limit=limit)

    async def fork_thread(self, thread_id: str, checkpoint: dict) -> str:
        """Fork a thread from a specific checkpoint.

        Creates a new thread and copies the state at the given checkpoint.
        """
        messages = checkpoint.get("values", {}).get("messages", [])
        new_thread_id = await self.copy_thread_with_messages(messages)
        return new_thread_id

    async def list_threads(self) -> list[dict]:
        """List threads on the server, most recent first."""
        return await self._client.threads.search(limit=100)

    async def get_thread(self, thread_id: str) -> dict:
        """Get a thread by ID from the server."""
        return await self._client.threads.get(thread_id)

    async def delete_thread(self, thread_id: str) -> None:
        """Delete a thread on the server."""
        await self._client.threads.delete(thread_id)

    async def compact_thread(self, thread_id: str, assistant_id: str):
        """Ask the agent to invoke its `compact_conversation` tool.

        We send a focused user prompt rather than injecting a synthetic
        AIMessage via `update_state`. Reason: the eligibility gate at
        `SummarizationToolMiddleware._is_eligible_for_compaction` reads
        `usage_metadata.total_tokens` from the most recent AIMessage, and
        langchain's dict-to-message coercion (`_create_message_from_message_
        type`) hoists `response_metadata` to the top level but lumps
        `usage_metadata` into `additional_kwargs` — there is no wire format
        that preserves it. So an injected message always reports 0 tokens
        and the gate always denies. Routing through a user prompt lets the
        model produce the tool call itself, with its real `usage_metadata`
        attached, and the gate sees the conversation's true token count.

        Yields the same event types as `stream_message`. Requires
        `SummarizationToolMiddleware` to be registered on the server.
        """
        prompt = (
            "Invoke the compact_conversation tool now to summarise older "
            "messages. Call it directly with no arguments — do not respond "
            "with text first."
        )
        async for chunk in self._client.runs.stream(
            thread_id=thread_id,
            assistant_id=assistant_id,
            input={"messages": [{"role": "user", "content": prompt}]},
            stream_mode=["updates", "messages"],
            stream_subgraphs=True,
        ):
            yield chunk

    async def resume(self, thread_id: str, assistant_id: str, resume_value: Any):
        """Resume an interrupted run with a Command(resume=value).

        Streams the continuation, yielding the same event types as stream_message.
        """
        async for chunk in self._client.runs.stream(
            thread_id=thread_id,
            assistant_id=assistant_id,
            input=None,
            command={"resume": resume_value},
            stream_mode=["updates", "messages"],
            stream_subgraphs=True,
        ):
            yield chunk
