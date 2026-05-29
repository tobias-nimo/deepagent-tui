"""Unit tests for per-agent (graph) scoping of settings and thread history.

Settings live in config.toml with a default layer plus `[graph."<id>"]`
overrides; thread history is filtered by graph_id (always) and workspace (when
known). Both use tmp paths so the user's real state is never touched.
"""
from __future__ import annotations

import pytest

from deepagent_tui.storage import config_store, db
from deepagent_tui.storage.config_store import UserConfig


@pytest.fixture()
def cfg_paths(monkeypatch, tmp_path):
    cfg_dir = tmp_path / ".deepagent-tui"
    monkeypatch.setattr(config_store, "_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_store, "_CONFIG_FILE", cfg_dir / "config.toml")


def test_graph_override_does_not_leak_to_default(cfg_paths):
    config_store.save_config(UserConfig(hitl_enabled=False, theme="neon"), graph_id="alpha")
    # The default layer is untouched by a graph-scoped write.
    assert config_store.load_config().hitl_enabled is True
    assert config_store.load_config().theme == ""
    # The graph layer reflects the override.
    alpha = config_store.load_config("alpha")
    assert alpha.hitl_enabled is False
    assert alpha.theme == "neon"


def test_graphs_are_isolated_from_each_other(cfg_paths):
    config_store.save_config(UserConfig(theme="neon"), graph_id="alpha")
    config_store.save_config(UserConfig(theme="ocean"), graph_id="beta")
    assert config_store.load_config("alpha").theme == "neon"
    assert config_store.load_config("beta").theme == "ocean"
    # An unknown graph falls back to the default layer.
    assert config_store.load_config("gamma").theme == ""


def test_default_layer_supplies_unset_graph_keys(cfg_paths):
    # Default theme set globally; graph only overrides hitl. The empty theme in
    # the graph snapshot must not clobber the inherited default theme.
    config_store.save_config(UserConfig(theme="vintage"), graph_id=None)
    config_store.save_config(UserConfig(theme="", hitl_enabled=False), graph_id="alpha")
    alpha = config_store.load_config("alpha")
    assert alpha.hitl_enabled is False
    assert alpha.theme == "vintage"


def test_flat_legacy_file_reads_as_default(cfg_paths):
    # A pre-scoping flat file (no [graph.*] tables) becomes the default layer.
    config_store._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_store._CONFIG_FILE.write_text('hitl_enabled = false\ntheme = "ocean"\n')
    cfg = config_store.load_config("anything")
    assert cfg.hitl_enabled is False
    assert cfg.theme == "ocean"


@pytest.fixture()
def db_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "threads.db")


async def test_list_threads_scopes_by_graph(db_paths):
    await db.upsert_thread("t1", "alpha", message_count=1)
    await db.upsert_thread("t2", "beta", message_count=1)
    alpha = await db.list_threads(graph_id="alpha")
    assert [t["id"] for t in alpha] == ["t1"]
    # No filter → everything.
    assert {t["id"] for t in await db.list_threads()} == {"t1", "t2"}


async def test_list_threads_scopes_by_workspace_when_known(db_paths):
    await db.upsert_thread("t1", "alpha", workspace="/home/proj-a", message_count=1)
    await db.upsert_thread("t2", "alpha", workspace="/home/proj-b", message_count=1)
    scoped = await db.list_threads(graph_id="alpha", workspace="/home/proj-a")
    assert [t["id"] for t in scoped] == ["t1"]
    # Workspace unknown (None) → graph-only, so both rows show.
    both = await db.list_threads(graph_id="alpha", workspace=None)
    assert {t["id"] for t in both} == {"t1", "t2"}


async def test_workspace_backfills_without_clobber(db_paths):
    # First write has no workspace (server hasn't reported it yet)…
    await db.upsert_thread("t1", "alpha", message_count=1)
    assert (await db.get_thread("t1"))["workspace"] is None
    # …a later write backfills it…
    await db.upsert_thread("t1", "alpha", workspace="/home/proj-a", message_count=2)
    assert (await db.get_thread("t1"))["workspace"] == "/home/proj-a"
    # …and a subsequent write with no workspace must not wipe it.
    await db.upsert_thread("t1", "alpha", message_count=3)
    assert (await db.get_thread("t1"))["workspace"] == "/home/proj-a"
