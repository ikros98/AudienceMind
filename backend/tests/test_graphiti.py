"""Focused tests for Graphiti transport helpers."""

from __future__ import annotations

import importlib
import sys
import time
import types
import httpx
import pytest

from app.config import Settings
from app.graphiti_service.models import EpisodeInput
from app.models import Project, SourceDocument
from app.services.adapters import GraphitiGraphBackend
from app.services.graphiti import GraphitiClient, normalize_graphiti_payload
from app.services.generation import GraphArtifacts


def test_graphiti_service_fastapi_title_is_audiencemind(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public Graphiti compatibility service title should use the AudienceMind brand."""
    llm_module = types.ModuleType("app.graphiti_service.llm")
    llm_module.create_graphiti = lambda settings: None
    service_module = types.ModuleType("app.graphiti_service.service")
    service_module.GraphitiCompatibilityService = object
    monkeypatch.setitem(sys.modules, "app.graphiti_service.llm", llm_module)
    monkeypatch.setitem(sys.modules, "app.graphiti_service.service", service_module)
    main_module = importlib.import_module("app.graphiti_service.main")

    assert main_module.app.title == "AudienceMind Graphiti Compatibility Service"


def test_episode_input_defaults_to_audiencemind_document_chunk() -> None:
    """Episode input defaults should not leak the retired product name."""
    assert EpisodeInput(name="brief-1", episode_body="hello").source_description == "AudienceMind document chunk"


def test_ingest_episodes_splits_large_episode_after_timeout(tmp_path) -> None:
    """A slow Graphiti episode request should retry as smaller sub-chunks instead of failing immediately."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        graphiti_base_url="http://127.0.0.1:8182",
        graphiti_timeout_seconds=1.0,
    )
    client = GraphitiClient(settings)
    calls: list[int] = []

    def fake_request(method: str, path: str, **kwargs):
        assert method == "POST"
        assert path == "/graphs/test-graph/episodes"
        episodes = kwargs["json"]["episodes"]
        calls.append(len(str(episodes[0]["episode_body"])))
        if len(calls) == 1:
            raise httpx.ReadTimeout("timed out")
        return {"ingested_count": len(episodes)}

    client._request = fake_request  # type: ignore[method-assign]
    try:
        client.ingest_episodes(
            "test-graph",
            [
                {
                    "name": "brief-1",
                    "episode_body": "A" * 1400,
                    "source_description": "Ralph Lauren brief",
                }
            ],
        )
    finally:
        client.close()

    assert len(calls) >= 2
    assert calls[0] == 1400
    assert max(calls[1:]) < calls[0]


def test_ingest_episodes_splits_large_episode_after_service_timeout(tmp_path) -> None:
    """Timeout-like service errors should also trigger the smaller-chunk retry path."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        graphiti_base_url="http://127.0.0.1:8182",
        graphiti_timeout_seconds=1.0,
    )
    client = GraphitiClient(settings)
    calls: list[int] = []

    def fake_request(method: str, path: str, **kwargs):
        assert method == "POST"
        assert path == "/graphs/test-graph/episodes"
        episodes = kwargs["json"]["episodes"]
        calls.append(len(str(episodes[0]["episode_body"])))
        if len(calls) == 1:
            raise RuntimeError("Graphiti request failed: timed out")
        return {"ingested_count": len(episodes)}

    client._request = fake_request  # type: ignore[method-assign]
    try:
        client.ingest_episodes(
            "test-graph",
            [
                {
                    "name": "brief-1",
                    "episode_body": "B" * 1400,
                    "source_description": "Ralph Lauren brief",
                }
            ],
        )
    finally:
        client.close()

    assert len(calls) >= 2
    assert calls[0] == 1400
    assert max(calls[1:]) < calls[0]


def test_request_retries_connect_error_before_succeeding(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Transient Graphiti connect failures should be retried before surfacing to callers."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        graphiti_base_url="http://127.0.0.1:8182",
    )
    client = GraphitiClient(settings)
    calls = 0

    class FakeClient:
        def request(self, method: str, path: str, **kwargs):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise httpx.ConnectError("Connection refused")
            request = httpx.Request(method, f"http://127.0.0.1:8182{path}")
            return httpx.Response(200, json={"ok": True}, request=request)

        def close(self) -> None:
            return None

    monkeypatch.setattr(client, "_client", FakeClient())
    try:
        payload = client._request("GET", "/health")
    finally:
        client.close()

    assert calls == 3
    assert payload == {"ok": True}


def test_ingest_episodes_emits_heartbeat_while_batch_request_is_running(tmp_path) -> None:
    """Slow Graphiti batch requests should keep task progress alive instead of looking frozen."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        graphiti_base_url="http://127.0.0.1:8182",
        graphiti_timeout_seconds=5.0,
    )
    client = GraphitiClient(settings)
    client._batch_heartbeat_seconds = 0.01
    progress_messages: list[str] = []

    def fake_request(method: str, path: str, **kwargs):
        assert method == "POST"
        assert path == "/graphs/test-graph/episodes"
        time.sleep(0.03)
        return {"ingested_count": len(kwargs["json"]["episodes"])}

    client._request = fake_request  # type: ignore[method-assign]
    try:
        client.ingest_episodes(
            "test-graph",
            [{"name": "brief-1", "episode_body": "heartbeat test", "source_description": "brief"}],
            progress_callback=lambda message, _: progress_messages.append(message),
        )
    finally:
        client.close()

    assert any("still processing" in message for message in progress_messages)


def test_normalize_graphiti_payload_recovers_location_label_from_generic_entity() -> None:
    """Obvious geography nodes should not leak through to the UI as generic or broad fallback labels."""
    payload = normalize_graphiti_payload(
        {
            "nodes": [
                {
                    "uuid": "node_1",
                    "name": "Tokyo",
                    "labels": ["Entity"],
                    "summary": "",
                    "attributes": {},
                },
                {
                    "uuid": "node_2",
                    "name": "London",
                    "labels": ["Organization"],
                    "summary": "Key city market for the campaign.",
                    "attributes": {},
                },
                {
                    "uuid": "node_3",
                    "name": "Ralph Lauren Corporation",
                    "labels": ["Luxury_Brand"],
                    "summary": "",
                    "attributes": {},
                },
            ],
            "edges": [],
        },
        "graph_1",
    )

    node_by_name = {item["name"]: item for item in payload["nodes"]}
    assert node_by_name["Tokyo"]["label"] == "Location"
    assert node_by_name["Tokyo"]["labels"] == ["Location"]
    assert node_by_name["London"]["label"] == "Location"
    assert node_by_name["London"]["labels"] == ["Location"]
    assert node_by_name["Ralph Lauren Corporation"]["label"] == "Luxury Brand"


def test_normalize_graphiti_payload_keeps_market_actors_out_of_location_bucket() -> None:
    """Actor-like organizations should not be downgraded into locations just because their summaries mention a market."""
    payload = normalize_graphiti_payload(
        {
            "nodes": [
                {
                    "uuid": "node_1",
                    "name": "WeChat",
                    "labels": ["Entity"],
                    "summary": "Social commerce platform used to reach the China market.",
                    "attributes": {},
                },
                {
                    "uuid": "node_2",
                    "name": "Haworth Lifestyle Design",
                    "labels": ["Organization"],
                    "summary": "Design partner helping Ralph Lauren expand in the home market.",
                    "attributes": {},
                },
            ],
            "edges": [],
        },
        "graph_2",
    )

    node_by_name = {item["name"]: item for item in payload["nodes"]}
    assert node_by_name["WeChat"]["label"] == "Organization"
    assert node_by_name["Haworth Lifestyle Design"]["label"] == "Organization"


def test_wait_for_graph_settle_raises_when_graphiti_returns_empty_graph(tmp_path) -> None:
    """A fully empty Graphiti payload should fail the build instead of being accepted as success."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        graphiti_base_url="http://127.0.0.1:8182",
        graphiti_timeout_seconds=1.0,
    )
    client = GraphitiClient(settings)

    def fake_request(method: str, path: str, **kwargs):
        assert method == "GET"
        assert path == "/graphs/test-graph"
        return {"node_count": 0, "edge_count": 0}

    client._request = fake_request  # type: ignore[method-assign]
    client.get_graph_payload = lambda graph_id: {  # type: ignore[method-assign]
        "graph_id": graph_id,
        "nodes": [],
        "edges": [],
        "metadata": {
            "graph_id": graph_id,
            "node_count": 0,
            "edge_count": 0,
            "entity_types": [],
            "edge_types": [],
        },
    }
    try:
        with pytest.raises(RuntimeError, match="empty graph"):
            client.wait_for_graph_settle(
                "test-graph",
                timeout_seconds=0.01,
                poll_interval_seconds=0.01,
                min_wait_seconds=0.0,
                stable_polls_required=0,
            )
    finally:
        client.close()


def test_graphiti_backend_builds_legacy_reference_like_episode_batches(tmp_path) -> None:
    """The clean-room graph ingester should stay in the same chunk-count band as the legacy reference."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        graphiti_base_url="http://127.0.0.1:8182",
        graph_batch_size=3,
    )
    backend = GraphitiGraphBackend(
        settings=settings,
        name="graphiti",
        label="Graphiti graph materialization",
    )
    project = Project(name="Prompt 4", scenario_brief="China market expansion")
    document = SourceDocument(
        project_id=project.id,
        filename="brief.md",
        extracted_text=("Ralph Lauren expands in China with WeChat commerce. " * 150).strip(),
    )

    episodes = backend._build_episodes(project, [document])

    assert 2 <= len(episodes) <= 5


def test_graphiti_backend_uses_single_episode_batches_like_legacy_reference(tmp_path) -> None:
    """Graphiti ingest should stay on single-episode requests, matching the stable legacy reference path."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        graphiti_base_url="http://127.0.0.1:8182",
        graph_batch_size=3,
    )
    backend = GraphitiGraphBackend(
        settings=settings,
        name="graphiti",
        label="Graphiti graph materialization",
    )

    assert backend._resolve_ingest_batch_size() == 1


def test_graphiti_backend_keeps_openrouter_free_qwen_chunks_small_on_first_pass(tmp_path) -> None:
    """The hosted OpenRouter free Qwen path should start with genuinely smaller Graphiti episodes."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        graphiti_base_url="http://127.0.0.1:8182",
        llm_base_url="https://openrouter.ai/api/v1",
        llm_model="qwen/qwen3.6-plus-preview:free",
        graph_chunk_size=1000,
        graph_chunk_overlap=100,
    )
    backend = GraphitiGraphBackend(
        settings=settings,
        name="graphiti",
        label="Graphiti graph materialization",
    )
    project = Project(name="Prompt 1", scenario_brief="Ralph Lauren Gen Z loyalty")
    document = SourceDocument(
        project_id=project.id,
        filename="brief.md",
        extracted_text=("Ralph Lauren expands into Gen Z fashion discourse. " * 220).strip(),
    )

    episodes = backend._build_episodes(project, [document])

    assert episodes
    assert max(len(item["episode_body"]) for item in episodes) <= 700


def test_graphiti_backend_episode_fallback_source_description_uses_audiencemind(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no project label can be inferred, episode source descriptions should use the AudienceMind fallback."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        graphiti_base_url="http://127.0.0.1:8182",
    )
    backend = GraphitiGraphBackend(
        settings=settings,
        name="graphiti",
        label="Graphiti graph materialization",
    )
    project = Project(name="Prompt 6", scenario_brief="Brand repositioning")
    document = SourceDocument(
        project_id=project.id,
        filename="brief.md",
        extracted_text="Audience research findings for the next launch.",
    )

    monkeypatch.setattr("app.services.adapters.infer_project_name", lambda *args, **kwargs: "")

    episodes = backend._build_episodes(project, [document])

    assert episodes
    assert all(item["source_description"] == "AudienceMind document chunk" for item in episodes)


def test_graphiti_backend_build_artifacts_falls_back_to_audiencemind_branding(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Graph creation should use AudienceMind-branded fallback names when no project label or objective exists."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        graphiti_base_url="http://127.0.0.1:8182",
    )
    backend = GraphitiGraphBackend(
        settings=settings,
        name="graphiti",
        label="Graphiti graph materialization",
    )
    project = Project(name="", description="", scenario_brief="")
    document = SourceDocument(
        project_id=project.id,
        filename="brief.md",
        extracted_text="Graph materialization source text.",
    )
    recorded: dict[str, str] = {}

    class FakeGraphitiClient:
        def __init__(self, _settings: Settings) -> None:
            pass

        def delete_graph(self, graph_id: str, ignore_missing: bool = False) -> None:
            return None

        def create_graph(self, graph_id: str, name: str, description: str) -> None:
            recorded["graph_id"] = graph_id
            recorded["name"] = name
            recorded["description"] = description

        def set_ontology(self, graph_id: str, ontology: dict) -> None:
            return None

        def ingest_episodes(self, graph_id: str, episodes: list[dict], **kwargs) -> None:
            return None

        def wait_for_graph_settle(self, graph_id: str, **kwargs) -> dict:
            return {
                "nodes": [{"uuid": "node-1"}],
                "edges": [{"uuid": "edge-1"}],
                "metadata": {
                    "node_count": 1,
                    "edge_count": 1,
                    "entity_types": ["Organization"],
                },
            }

        def close(self) -> None:
            return None

    monkeypatch.setattr("app.services.adapters.infer_project_name", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        "app.services.adapters.build_graph_artifacts",
        lambda *args, **kwargs: GraphArtifacts(
            summary="base",
            source_digest="digest",
            schema_markdown="schema",
            evidence_markdown="evidence",
            node_count=0,
            edge_count=0,
        ),
    )
    monkeypatch.setattr(backend, "_build_ontology", lambda **kwargs: {"entity_types": [], "edge_types": []})
    monkeypatch.setattr("app.services.adapters.GraphitiClient", FakeGraphitiClient)

    artifacts = backend.build_artifacts(
        llm=None,
        project=project,
        documents=[document],
        objective="",
    )

    assert artifacts.graph_id == project.id
    assert recorded["name"] == "AudienceMind Graph"
    assert recorded["description"] == "AudienceMind graph materialization"
