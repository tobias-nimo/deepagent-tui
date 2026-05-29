from __future__ import annotations

import argparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    langgraph_url: str = "http://localhost:2024"
    graph_id: str | None = None
    thread_id: str | None = None
    langsmith_api_key: str | None = None


settings = Settings()


def add_connection_flags(parser: argparse.ArgumentParser, *, thread: bool = True) -> None:
    """Add the server-connection override flags shared by the TUI and the
    `deepagent` CLI. Each flag overrides the matching env var when supplied.

    `thread=False` omits `--thread` for subcommands that target a thread by
    other means (the CLI's `resume` takes a positional thread id).
    """
    parser.add_argument("--url", metavar="URL", help="override LANGGRAPH_URL")
    parser.add_argument("--graph", metavar="GRAPH_ID", help="override GRAPH_ID")
    if thread:
        parser.add_argument("--thread", metavar="THREAD_ID", help="override THREAD_ID")


def apply_connection_overrides(args: argparse.Namespace) -> None:
    """Apply parsed connection flags onto the `settings` singleton. Attributes
    absent from `args` (e.g. a subcommand without `--thread`) are ignored, so
    the same call works for every parser built with `add_connection_flags`.
    """
    if getattr(args, "url", None):
        settings.langgraph_url = args.url
    if getattr(args, "graph", None):
        settings.graph_id = args.graph
    if getattr(args, "thread", None):
        settings.thread_id = args.thread
