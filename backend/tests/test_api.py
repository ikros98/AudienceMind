"""API smoke tests for PersonaGraph."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services import adapters
from app.services import glass_compat
from app.services import workflows


def build_test_client(tmp_path, *, raise_server_exceptions: bool = True):
    """Create a test client backed by a temporary SQLite database."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
        allowed_origins=["http://localhost:5173"],
        llm_provider="test",
        llm_base_url="http://127.0.0.1:9/v1",
        llm_api_key="test",
        llm_model="test-model",
        workflow_poll_interval_seconds=0.02,
    )
    app = create_app(settings)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def wait_for_status(client: TestClient, path: str, terminal_statuses: set[str], timeout_seconds: float = 5.0):
    """Poll a read endpoint until the workflow reaches one of the requested statuses."""
    deadline = time.time() + timeout_seconds
    last_payload = None
    while time.time() < deadline:
        response = client.get(path)
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        if payload["status"] in terminal_statuses:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {path}; last payload was {last_payload}")


def wait_for_glass_status(
    client: TestClient,
    method: str,
    path: str,
    *,
    json_payload: dict | None = None,
    terminal_statuses: set[str],
    timeout_seconds: float = 8.0,
):
    """Poll a legacy glass compatibility endpoint until it reaches a terminal status."""
    deadline = time.time() + timeout_seconds
    last_payload = None
    while time.time() < deadline:
        if method.upper() == "POST":
            response = client.post(path, json=json_payload or {})
        else:
            response = client.get(path)
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        data = payload["data"]
        last_payload = data
        current_status = data.get("status") or data.get("runner_status")
        if current_status in terminal_statuses:
            return data
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {path}; last payload was {last_payload}")


def build_realish_glass_graph_snapshot(**kwargs):
    """Return a deterministic non-placeholder graph payload for compat tests."""
    project = kwargs["project"]
    nodes = [
        {
            "uuid": "brand_ralph_lauren",
            "name": project.name,
            "label": "Brand",
            "summary": f"{project.name} is the focal brand in the source brief.",
        },
        {
            "uuid": "campaign_holiday_heritage",
            "name": "Holiday Heritage Campaign",
            "label": "Campaign",
            "summary": "Seasonal campaign centered on heritage storytelling and gifting.",
        },
        {
            "uuid": "audience_gen_z_buyers",
            "name": "Gen Z Buyers",
            "label": "Audience",
            "summary": "Younger shoppers tracking authenticity, price, and cultural relevance.",
        },
        {
            "uuid": "surface_x",
            "name": "X",
            "label": "Platform",
            "summary": "Fast-moving discussion surface for reactions and media pickup.",
        },
        {
            "uuid": "surface_reddit",
            "name": "Reddit",
            "label": "Platform",
            "summary": "Long-form discussion surface for community debate and scrutiny.",
        },
        {
            "uuid": "theme_sustainability",
            "name": "Sustainability Claims",
            "label": "Theme",
            "summary": "Discussion theme focused on credibility of environmental messaging.",
        },
        {
            "uuid": "partner_creators",
            "name": "Creator Partners",
            "label": "Creator Group",
            "summary": "External creators amplifying or questioning the campaign narrative.",
        },
        {
            "uuid": "retail_flagship_store",
            "name": "Flagship Retail Stores",
            "label": "Retail Channel",
            "summary": "Physical storefronts that translate campaign interest into conversion.",
        },
        {
            "uuid": "region_europe",
            "name": "Europe",
            "label": "Region",
            "summary": "Regional market where campaign sentiment and tourism influence demand.",
        },
        {
            "uuid": "team_sustainability_office",
            "name": "Sustainability Office",
            "label": "Internal Team",
            "summary": "Internal team responsible for claim substantiation and stakeholder responses.",
        },
    ]
    edges = [
        {
            "uuid": "edge_brand_campaign_launches",
            "source_uuid": "brand_ralph_lauren",
            "target_uuid": "campaign_holiday_heritage",
            "relation_type": "launches",
            "fact": "The brand launches the holiday heritage campaign.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_campaign_audience_targets",
            "source_uuid": "campaign_holiday_heritage",
            "target_uuid": "audience_gen_z_buyers",
            "relation_type": "targets",
            "fact": "The campaign explicitly targets younger buyers.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_campaign_theme_prompts",
            "source_uuid": "campaign_holiday_heritage",
            "target_uuid": "theme_sustainability",
            "relation_type": "prompts_discussion",
            "fact": "The campaign triggers sustainability credibility debate.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_theme_platform_x",
            "source_uuid": "theme_sustainability",
            "target_uuid": "surface_x",
            "relation_type": "spreads_on",
            "fact": "The sustainability theme spreads quickly on X.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_theme_platform_reddit",
            "source_uuid": "theme_sustainability",
            "target_uuid": "surface_reddit",
            "relation_type": "debated_on",
            "fact": "The sustainability theme is debated in depth on Reddit.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_creators_campaign_support",
            "source_uuid": "partner_creators",
            "target_uuid": "campaign_holiday_heritage",
            "relation_type": "amplifies",
            "fact": "Creator partners amplify the campaign narrative.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_creators_audience_shape",
            "source_uuid": "partner_creators",
            "target_uuid": "audience_gen_z_buyers",
            "relation_type": "influences",
            "fact": "Creator commentary shapes Gen Z buyer sentiment.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_campaign_retail_drives",
            "source_uuid": "campaign_holiday_heritage",
            "target_uuid": "retail_flagship_store",
            "relation_type": "drives_traffic",
            "fact": "Campaign visibility drives traffic to flagship stores.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_audience_retail_converts",
            "source_uuid": "audience_gen_z_buyers",
            "target_uuid": "retail_flagship_store",
            "relation_type": "shops_at",
            "fact": "Interested Gen Z buyers convert through flagship stores.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_region_campaign_prioritizes",
            "source_uuid": "campaign_holiday_heritage",
            "target_uuid": "region_europe",
            "relation_type": "prioritizes",
            "fact": "The campaign prioritizes European markets for holiday reach.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_team_theme_reviews",
            "source_uuid": "team_sustainability_office",
            "target_uuid": "theme_sustainability",
            "relation_type": "reviews",
            "fact": "The sustainability office reviews claim credibility and evidence.",
            "weight": 1.0,
        },
        {
            "uuid": "edge_team_brand_advises",
            "source_uuid": "team_sustainability_office",
            "target_uuid": "brand_ralph_lauren",
            "relation_type": "advises",
            "fact": "The sustainability office advises the brand on messaging risk.",
            "weight": 1.0,
        },
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "entity_types": sorted({node["label"] for node in nodes}),
            "edge_types": sorted({edge["relation_type"] for edge in edges}),
        },
    }


def build_synthetic_glass_graph_snapshot(**kwargs):
    """Return the legacy placeholder scaffold so compat guards can still be tested."""
    del kwargs
    nodes = [
        {"uuid": "type_brand", "name": "Brand", "label": "Brand", "summary": "Schema anchor for Brand."},
        {"uuid": "type_person", "name": "Person", "label": "Person", "summary": "Schema anchor for Person."},
        {"uuid": "platform_twitter", "name": "Twitter", "label": "Platform", "summary": "Primary surface for the project."},
        {"uuid": "platform_reddit", "name": "Reddit", "label": "Platform", "summary": "Primary surface for the project."},
        {"uuid": "topic_authenticity", "name": "Authenticity", "label": "Topic", "summary": "Recurring discussion theme around authenticity."},
        {"uuid": "audience_core_advocates", "name": "Core Advocates", "label": "Audience Segment", "summary": "Audience segment tracking core advocates reactions."},
    ]
    edges = [
        {
            "uuid": "edge_brand_topic",
            "source_uuid": "type_brand",
            "target_uuid": "topic_authenticity",
            "relation_type": "discusses",
            "fact": "The brand is discussed in relation to authenticity.",
            "weight": 1.0,
        }
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "entity_types": sorted({node["label"] for node in nodes}),
            "edge_types": sorted({edge["relation_type"] for edge in edges}),
        },
    }


def test_health_returns_runtime_metadata(tmp_path):
    """Health endpoint exposes service metadata."""
    with build_test_client(tmp_path) as client:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["service"] == "AudienceMind API"
        assert payload["llm_provider"] == "test"
        assert payload["workflow_runner_mode"] == "embedded"
        assert payload["simulation_backend"] == "native"
        assert payload["report_backend"] == "native"
        assert payload["queue_depth"] == 0
        assert payload["running_count"] == 0


def test_health_external_worker_mode_reports_queue_depth(tmp_path):
    """Health should expose when the API is running without an embedded worker."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-external.db'}",
        data_dir=str(tmp_path / "data"),
        allowed_origins=["http://localhost:5173"],
        llm_provider="test",
        llm_base_url="http://127.0.0.1:9/v1",
        llm_api_key="test",
        llm_model="test-model",
        embed_workflow_runner=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        project = client.post(
            "/projects",
            json={
                "name": "Queued only",
                "description": "No embedded runner",
                "scenario_brief": "Leave the graph job queued for an external worker.",
            },
        ).json()
        client.post(
            f"/projects/{project['id']}/source-notes",
            json={"title": "Queued note", "content": "Persist this for the queue depth test."},
        )
        graph_job = client.post(
            f"/projects/{project['id']}/graph-jobs",
            json={"graph_backend": "graphiti", "objective": "Queue a graph build"},
        ).json()
        assert graph_job["status"] == "queued"

        health_response = client.get("/health")
        assert health_response.status_code == 200
        payload = health_response.json()
        assert payload["workflow_runner_mode"] == "external"
        assert payload["queue_depth"] >= 1


def test_project_to_report_flow(tmp_path):
    """Project upload, graph, simulation, report, and analysis chat all work."""
    with build_test_client(tmp_path) as client:
        project_response = client.post(
            "/projects",
            json={
                "name": "Energy market stress test",
                "description": "Scenario planning workspace",
                "scenario_brief": "Model public and analyst reactions to an overnight energy price shock.",
            },
        )
        assert project_response.status_code == 201
        project = project_response.json()

        upload_response = client.post(
            f"/projects/{project['id']}/sources",
            files=[
                (
                    "files",
                    (
                        "brief.txt",
                        b"Wholesale power prices spiked overnight while regulators signaled a review of reserve capacity.",
                        "text/plain",
                    ),
                )
            ],
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.json()["items"]
        assert uploaded[0]["filename"] == "brief.txt"

        note_response = client.post(
            f"/projects/{project['id']}/source-notes",
            json={
                "title": "Analyst assumptions",
                "content": "Regulators are likely to emphasize reassurance before structural reform.",
            },
        )
        assert note_response.status_code == 201
        note = note_response.json()
        assert note["filename"] == "analyst-assumptions.md"

        graph_job_response = client.post(
            f"/projects/{project['id']}/graph-jobs",
            json={"graph_backend": "graphiti", "objective": "Build initial evidence graph"},
        )
        assert graph_job_response.status_code == 201
        graph_job = graph_job_response.json()
        assert graph_job["status"] == "queued"
        assert graph_job["progress_percent"] == 0
        assert graph_job["status_message"] == "Queued graph artifact build."
        graph_job = wait_for_status(client, f"/graph-jobs/{graph_job['id']}", {"completed"})
        assert graph_job["node_count"] > 0
        assert graph_job["progress_percent"] == 100
        assert graph_job["status_message"] == "Graph artifact ready for downstream simulation."
        assert graph_job["started_at"] is not None
        assert graph_job["completed_at"] is not None
        assert (tmp_path / "data" / "artifacts" / "graph-jobs" / graph_job["id"] / "schema.md").exists()

        graph_updates_response = client.get(f"/graph-jobs/{graph_job['id']}/updates")
        assert graph_updates_response.status_code == 200
        graph_updates = graph_updates_response.json()["items"]
        assert graph_updates[0]["message"] == "Queued graph artifact build."
        assert graph_updates[-1]["progress_percent"] == 100
        assert any(item["status"] == "running" for item in graph_updates)

        project_graph_jobs_response = client.get(f"/projects/{project['id']}/graph-jobs")
        assert project_graph_jobs_response.status_code == 200
        assert project_graph_jobs_response.json()["items"][0]["id"] == graph_job["id"]

        project_after_graph = client.get(f"/projects/{project['id']}")
        assert project_after_graph.status_code == 200
        assert project_after_graph.json()["status"] == "running"

        simulation_response = client.post(
            "/simulations",
            json={
                "project_id": project["id"],
                "graph_job_id": graph_job["id"],
                "mode": "analysis",
                "cohort_size": 150,
            },
        )
        assert simulation_response.status_code == 201
        simulation = simulation_response.json()
        assert simulation["status"] == "queued"
        assert simulation["progress_percent"] == 0
        assert simulation["status_message"] == "Queued simulation run."
        simulation = wait_for_status(client, f"/simulations/{simulation['id']}", {"completed"})
        assert simulation["event_count"] > 0
        assert simulation["timeline_markdown"]
        assert simulation["progress_percent"] == 100
        assert simulation["status_message"] == "Simulation artifacts ready for report generation."
        assert simulation["started_at"] is not None
        assert simulation["completed_at"] is not None
        assert (tmp_path / "data" / "artifacts" / "simulations" / simulation["id"] / "timeline.md").exists()

        event_response = client.get(f"/simulations/{simulation['id']}/events")
        assert event_response.status_code == 200
        event_items = event_response.json()["items"]
        assert len(event_items) == simulation["event_count"]
        assert event_items[0]["title"]

        simulation_updates_response = client.get(f"/simulations/{simulation['id']}/updates")
        assert simulation_updates_response.status_code == 200
        simulation_updates = simulation_updates_response.json()["items"]
        assert simulation_updates[0]["message"] == "Queued simulation run."
        assert simulation_updates[-1]["progress_percent"] == 100
        assert any(item["status"] == "running" for item in simulation_updates)

        report_response = client.post(
            "/reports",
            json={
                "simulation_id": simulation["id"],
                "focus": "Decision risks and communications strategy",
            },
        )
        assert report_response.status_code == 201
        report = report_response.json()
        assert report["status"] in {"queued", "running"}
        assert report["status_message"] in {
            "Queued report generation.",
            "Queued report generation.",
            "Planning report outline from simulation evidence.",
            "Loading simulation evidence for report drafting.",
        }
        report = wait_for_status(client, f"/reports/{report['id']}", {"completed"})

        assert report["simulation_id"] == simulation["id"]
        assert report["markdown_body"]
        assert report["progress_percent"] == 100
        assert report["status_message"] == "Report ready in the analysis workspace."
        assert report["started_at"] is not None
        assert report["completed_at"] is not None
        assert (tmp_path / "data" / "artifacts" / "reports" / report["id"] / "report.md").exists()

        report_updates_response = client.get(f"/reports/{report['id']}/updates")
        assert report_updates_response.status_code == 200
        report_updates = report_updates_response.json()["items"]
        assert report_updates[0]["message"] in {
            "Queued report generation.",
            "Loading simulation evidence for report drafting.",
        }
        assert report_updates[-1]["progress_percent"] == 100
        assert any(item["status"] == "running" for item in report_updates)

        project_after_report = client.get(f"/projects/{project['id']}")
        assert project_after_report.status_code == 200
        assert project_after_report.json()["status"] == "completed"

        chat_response = client.post(
            "/analysis/chat",
            json={
                "simulation_id": simulation["id"],
                "report_id": report["id"],
                "message": "What should the analyst team monitor first?",
            },
        )
        assert chat_response.status_code == 200
        chat = chat_response.json()
        assert chat["used_simulation_id"] == simulation["id"]
        assert chat["answer"]


def test_cross_object_validation_rejects_mismatched_references(tmp_path):
    """Simulation and analysis routes reject mismatched object references."""
    with build_test_client(tmp_path) as client:
        first_project = client.post(
            "/projects",
            json={
                "name": "Grid shock",
                "description": "First project",
                "scenario_brief": "A sudden power market shock changes public expectations.",
            },
        ).json()
        second_project = client.post(
            "/projects",
            json={
                "name": "Telecom disruption",
                "description": "Second project",
                "scenario_brief": "A regional outage drives a competing narrative cycle.",
            },
        ).json()

        graph_job = client.post(
            f"/graph-jobs/projects/{first_project['id']}",
            json={"graph_backend": "graphiti", "objective": "Map actor pressure points"},
        ).json()
        graph_job = wait_for_status(client, f"/graph-jobs/{graph_job['id']}", {"completed"})

        bad_simulation_response = client.post(
            "/simulations",
            json={
                "project_id": second_project["id"],
                "graph_job_id": graph_job["id"],
                "mode": "analysis",
                "cohort_size": 100,
            },
        )
        assert bad_simulation_response.status_code == 400

        simulation = client.post(
            "/simulations",
            json={
                "project_id": first_project["id"],
                "graph_job_id": graph_job["id"],
                "mode": "analysis",
                "cohort_size": 100,
            },
        ).json()
        simulation = wait_for_status(client, f"/simulations/{simulation['id']}", {"completed"})
        report = client.post(
            "/reports",
            json={
                "simulation_id": simulation["id"],
                "focus": "Decision support",
            },
        ).json()
        report = wait_for_status(client, f"/reports/{report['id']}", {"completed"})

        second_simulation = client.post(
            "/simulations",
            json={
                "project_id": second_project["id"],
                "mode": "analysis",
                "cohort_size": 100,
            },
        ).json()
        second_simulation = wait_for_status(client, f"/simulations/{second_simulation['id']}", {"completed"})

        bad_chat_response = client.post(
            "/analysis/chat",
            json={
                "simulation_id": second_simulation["id"],
                "report_id": report["id"],
                "message": "What matters first?",
            },
        )
        assert bad_chat_response.status_code == 400


def test_failed_graph_generation_persists_failed_job_state(tmp_path, monkeypatch):
    """Graph job failures should persist a failed record for later inspection."""

    def explode_graph_artifacts(*args, **kwargs):
        raise RuntimeError("synthetic graph failure")

    monkeypatch.setattr(adapters, "build_graph_artifacts", explode_graph_artifacts)

    with build_test_client(tmp_path, raise_server_exceptions=False) as client:
        project = client.post(
            "/projects",
            json={
                "name": "Failure case",
                "description": "Graph failure path",
                "scenario_brief": "Force the graph generator to fail after the job is queued.",
            },
        ).json()

        note_response = client.post(
            f"/projects/{project['id']}/source-notes",
            json={
                "title": "Failure note",
                "content": "This project exists only to test failed graph persistence.",
            },
        )
        assert note_response.status_code == 201

        graph_response = client.post(
            f"/projects/{project['id']}/graph-jobs",
            json={"graph_backend": "graphiti", "objective": "Trigger a controlled failure"},
        )
        assert graph_response.status_code == 201
        queued_job = graph_response.json()
        assert queued_job["status"] in {"queued", "running"}
        failed_job = wait_for_status(client, f"/graph-jobs/{queued_job['id']}", {"failed"})
        assert failed_job["status"] == "failed"
        assert "Graph generation failed" in failed_job["summary"]
        assert "synthetic graph failure" in failed_job["error_message"]
        assert failed_job["status_message"] == failed_job["summary"]

        failed_updates_response = client.get(f"/graph-jobs/{queued_job['id']}/updates")
        assert failed_updates_response.status_code == 200
        failed_updates = failed_updates_response.json()["items"]
        assert failed_updates[-1]["status"] == "failed"
        assert failed_updates[-1]["level"] == "error"


def test_glass_compat_graph_build_rejects_synthetic_snapshot(tmp_path):
    """The glass compat graph path should fail instead of returning a placeholder scaffold."""
    from app.services import glass_compat as compat_module

    original_builder = compat_module.build_glass_graph_snapshot
    compat_module.build_glass_graph_snapshot = build_synthetic_glass_graph_snapshot
    with build_test_client(tmp_path) as client:
        try:
            ontology_response = client.post(
                "/api/graph/ontology/generate",
                data={
                    "simulation_requirement": "Test how a sustainability claim changes audience trust over a week.",
                    "project_name": "Sustainability Pressure Test",
                },
                files=[
                    (
                        "files",
                        (
                            "brief.txt",
                            b"Creators and policy watchers are debating whether the new sustainability claim is credible.",
                            "text/plain",
                        ),
                    ),
                ],
            )
            assert ontology_response.status_code == 200
            ontology_payload = ontology_response.json()["data"]

            build_response = client.post(
                "/api/graph/build",
                json={"project_id": ontology_payload["project_id"]},
            )
            assert build_response.status_code == 200
            task_id = build_response.json()["data"]["task_id"]
            task = wait_for_glass_status(client, "GET", f"/api/graph/task/{task_id}", terminal_statuses={"failed"})
            assert task["status"] == "failed"
            assert "Synthetic placeholder graph generation is disabled" in task["error"]

            project_response = client.get(f"/api/graph/project/{ontology_payload['project_id']}")
            assert project_response.status_code == 200
            project_payload = project_response.json()["data"]
            assert project_payload["status"] == "failed"
            assert "Synthetic placeholder graph generation is disabled" in project_payload["error"]

            graph_response = client.get(f"/api/graph/data/{task_id}")
            assert graph_response.status_code == 200
            graph_payload = graph_response.json()
            assert graph_payload["success"] is False
            assert "Synthetic placeholder graph generation is disabled" in graph_payload["error"]
        finally:
            compat_module.build_glass_graph_snapshot = original_builder


def test_glass_compat_does_not_complete_graph_while_build_thread_is_active(tmp_path, monkeypatch):
    """Compat routes should not promote a running graph job just because partial graph data exists."""
    with build_test_client(tmp_path) as client:
        runtime = client.app.state.glass_runtime
        monkeypatch.setattr(runtime, "start_graph_build", lambda graph_job_id: None)
        monkeypatch.setattr(runtime, "graph_build_is_active", lambda graph_job_id: True)

        ontology_response = client.post(
            "/api/graph/ontology/generate",
            data={
                "simulation_requirement": "Test how a sustainability claim changes audience trust over a week.",
                "project_name": "In-Flight Graph Build",
            },
            files=[
                (
                    "files",
                    (
                        "brief.txt",
                        b"Creators and policy watchers are debating whether the new sustainability claim is credible.",
                        "text/plain",
                    ),
                ),
            ],
        )
        assert ontology_response.status_code == 200
        project_id = ontology_response.json()["data"]["project_id"]

        build_response = client.post("/api/graph/build", json={"project_id": project_id})
        assert build_response.status_code == 200
        task_id = build_response.json()["data"]["task_id"]

        glass_compat.save_graph_payload(
            client.app.state.settings,
            task_id,
            {
                "nodes": [
                    {
                        "uuid": "brand_ralph_lauren",
                        "name": "Ralph Lauren",
                        "label": "Brand",
                        "labels": ["Entity", "Brand"],
                        "summary": "Partial graph data exists, but the build is still active.",
                    }
                ],
                "edges": [],
                "metadata": {
                    "graph_id": task_id,
                    "node_count": 1,
                    "edge_count": 0,
                    "entity_types": ["Brand"],
                    "edge_types": [],
                },
            },
        )

        task_response = client.get(f"/api/graph/task/{task_id}")
        assert task_response.status_code == 200
        task_payload = task_response.json()["data"]
        assert task_payload["status"] == "processing"

        project_response = client.get(f"/api/graph/project/{project_id}")
        assert project_response.status_code == 200
        project_payload = project_response.json()["data"]
        assert project_payload["status"] == "graph_building"

        graph_response = client.get(f"/api/graph/data/{task_id}")
        assert graph_response.status_code == 404


def test_glass_ontology_generation_uses_domain_specific_types(tmp_path):
    """Ontology generation should avoid the old analyst placeholder schema."""
    with build_test_client(tmp_path) as client:
        response = client.post(
            "/api/graph/ontology/generate",
            data={
                "simulation_requirement": (
                    "Simulate how Gen Z consumers react to Ralph Lauren's cultural relevance push, including "
                    "fashion influencers, competitor brands, pricing pressure, sustainability criticism, and "
                    "social-media amplification on Twitter and Reddit."
                ),
                "project_name": "Ralph Lauren Depth Test",
                "additional_context": "Focus on fashion media, competitor contrast, and brand loyalty outcomes.",
            },
            files=[
                (
                    "files",
                    (
                        "brief.md",
                        (
                            b"Ralph Lauren is trying to translate a viral aesthetic moment into sustained brand affinity. "
                            b"Consumers are comparing the brand with Burberry and Tommy Hilfiger while debating pricing, "
                            b"authenticity, and sustainability on Twitter and Reddit."
                        ),
                        "text/markdown",
                    ),
                ),
            ],
        )
        assert response.status_code == 200
        payload = response.json()["data"]
        entity_names = [item["name"] for item in payload["ontology"]["entity_types"]]
        edge_names = [item["name"] for item in payload["ontology"]["edge_types"]]

        assert "Stakeholder" not in entity_names
        assert "Narrative" not in entity_names
        assert "Signal" not in entity_names
        assert any(name in entity_names for name in {"Brand", "Competitor Brand", "Product Line", "Person", "Media Outlet", "Theme"})
        assert any(name in edge_names for name in {"competes_with", "covers", "reacts_to", "amplifies_on"})


def test_glass_compat_flow_runs_end_to_end(tmp_path):
    """The legacy glass compatibility surface should support a full run, interviews, and report generation."""
    with build_test_client(tmp_path) as client:
        ontology_response = client.post(
            "/api/graph/ontology/generate",
            data={
                "simulation_requirement": "Test how a sustainability claim changes audience trust over a week.",
                "project_name": "Sustainability Pressure Test",
                "additional_context": "Focus on reputation, creators, and community response.",
            },
            files=[
                (
                    "files",
                    (
                        "brief.txt",
                        b"Creators and policy watchers are debating whether the new sustainability claim is credible.",
                        "text/plain",
                    ),
                ),
            ],
        )
        assert ontology_response.status_code == 200
        ontology_payload = ontology_response.json()["data"]
        assert ontology_payload["project_id"].startswith("proj_")
        assert len(ontology_payload["ontology"]["entity_types"]) >= 6
        assert "Stakeholder" not in {item["name"] for item in ontology_payload["ontology"]["entity_types"]}

        build_response = client.post(
            "/api/graph/build",
            json={"project_id": ontology_payload["project_id"]},
        )
        assert build_response.status_code == 200
        task_id = build_response.json()["data"]["task_id"]
        task = wait_for_glass_status(client, "GET", f"/api/graph/task/{task_id}", terminal_statuses={"completed"})
        assert task["result"]["graph_id"] == task_id

        project_response = client.get(f"/api/graph/project/{ontology_payload['project_id']}")
        assert project_response.status_code == 200
        project_payload = project_response.json()["data"]
        assert project_payload["status"] == "graph_completed"
        assert project_payload["graph_id"] == task_id
        assert "Thinking Process" not in project_payload["analysis_summary"]

        project_list_response = client.get("/api/graph/project/list")
        assert project_list_response.status_code == 200
        project_list_payload = project_list_response.json()
        assert project_list_payload["success"] is True
        assert any(item["project_id"] == ontology_payload["project_id"] for item in project_list_payload["data"])

        tasks_response = client.get("/api/graph/tasks")
        assert tasks_response.status_code == 200
        assert any(item["task_id"] == task_id for item in tasks_response.json()["data"])

        reset_response = client.post(f"/api/graph/project/{ontology_payload['project_id']}/reset")
        assert reset_response.status_code == 200
        reset_payload = reset_response.json()
        assert reset_payload["success"] is True
        assert reset_payload["data"]["graph_id"] is None
        assert reset_payload["data"]["status"] == "ontology_generated"

        rebuild_response = client.post(
            "/api/graph/build",
            json={"project_id": ontology_payload["project_id"]},
        )
        assert rebuild_response.status_code == 200
        task_id = rebuild_response.json()["data"]["task_id"]
        task = wait_for_glass_status(client, "GET", f"/api/graph/task/{task_id}", terminal_statuses={"completed"})
        assert task["result"]["graph_id"] == task_id

        graph_response = client.get(f"/api/graph/data/{task_id}")
        assert graph_response.status_code == 200
        graph_payload = graph_response.json()["data"]
        assert graph_payload["metadata"]["node_count"] >= 8
        assert graph_payload["metadata"]["edge_count"] >= 9

        entities_response = client.get(f"/api/simulation/entities/{task_id}")
        assert entities_response.status_code == 200
        entities_payload = entities_response.json()["data"]
        assert entities_payload["filtered_count"] > 0
        first_entity = entities_payload["entities"][0]

        entity_detail_response = client.get(f"/api/simulation/entities/{task_id}/{first_entity['uuid']}")
        assert entity_detail_response.status_code == 200
        assert entity_detail_response.json()["data"]["uuid"] == first_entity["uuid"]

        entity_type = first_entity["labels"][0]
        entities_by_type_response = client.get(f"/api/simulation/entities/{task_id}/by-type/{entity_type}")
        assert entities_by_type_response.status_code == 200
        assert entities_by_type_response.json()["data"]["filtered_count"] >= 1

        simulation_response = client.post(
            "/api/simulation/create",
            json={"project_id": ontology_payload["project_id"], "graph_id": task_id},
        )
        assert simulation_response.status_code == 200
        simulation_payload = simulation_response.json()["data"]
        simulation_id = simulation_payload["simulation_id"]

        prepare_response = client.post(
            "/api/simulation/prepare",
            json={"simulation_id": simulation_id},
        )
        assert prepare_response.status_code == 200
        prepare_status = wait_for_glass_status(
            client,
            "POST",
            "/api/simulation/prepare/status",
            json_payload={"simulation_id": simulation_id},
            terminal_statuses={"ready"},
        )
        assert prepare_status["progress"] == 100
        sim_root = tmp_path / "data" / "glass" / "simulations" / simulation_id
        assert (sim_root / "prepared_entities.json").exists()
        assert (sim_root / "preparation_manifest.json").exists()

        profiles_response = client.get(f"/api/simulation/{simulation_id}/profiles", params={"platform": "reddit"})
        assert profiles_response.status_code == 200
        profiles = profiles_response.json()["data"]["profiles"]
        assert len(profiles) == entities_payload["filtered_count"]
        entity_uuids = {item["uuid"] for item in entities_payload["entities"]}
        profile_entity_uuids = {item["source_entity_uuid"] for item in profiles}
        assert profile_entity_uuids
        assert profile_entity_uuids.issubset(entity_uuids)

        config_response = client.get(f"/api/simulation/{simulation_id}/config")
        assert config_response.status_code == 200
        config_payload = config_response.json()["data"]
        assert config_payload["time_config"]["total_simulation_hours"] == 168
        assert config_payload["time_config"]["minutes_per_round"] == 60
        assert len(config_payload["agent_configs"]) == len(profiles)
        assert config_payload["event_config"]["initial_posts"]
        assert config_payload["event_config"]["scheduled_events"]

        config_download_response = client.get(f"/api/simulation/{simulation_id}/config/download")
        assert config_download_response.status_code == 200
        assert '"agent_configs"' in config_download_response.text

        generate_profiles_response = client.post(
            "/api/simulation/generate-profiles",
            json={"graph_id": task_id, "platform": "reddit", "use_llm": False},
        )
        assert generate_profiles_response.status_code == 200
        assert generate_profiles_response.json()["data"]["count"] == len(profiles)

        script_download_response = client.get("/api/simulation/script/run_parallel_simulation.py/download")
        assert script_download_response.status_code == 200
        assert "oasis_worker" in script_download_response.text

        start_response = client.post(
            "/api/simulation/start",
            json={"simulation_id": simulation_id, "max_rounds": 8, "force": True},
        )
        assert start_response.status_code == 200
        assert start_response.json()["data"]["max_rounds_applied"] == 8

        run_status = wait_for_glass_status(
            client,
            "GET",
            f"/api/simulation/{simulation_id}/run-status",
            terminal_statuses={"completed"},
            timeout_seconds=10.0,
        )
        assert run_status["current_round"] == 8
        assert run_status["total_actions_count"] > 0
        assert run_status["minutes_per_round"] == 60
        assert run_status["twitter_completed"] is True
        assert run_status["reddit_completed"] is True

        actions_response = client.get(f"/api/simulation/{simulation_id}/actions")
        assert actions_response.status_code == 200
        assert actions_response.json()["data"]["total"] > 0

        single_interview_response = client.post(
            "/api/simulation/interview",
            json={
                "simulation_id": simulation_id,
                "agent_id": profiles[0]["agent_id"],
                "prompt": "What are you noticing right now?",
            },
        )
        assert single_interview_response.status_code == 200
        single_result = single_interview_response.json()["data"]["result"]
        assert "platforms" in single_result

        batch_interviews = [
            {"agent_id": profile["agent_id"], "prompt": prompt}
            for profile, prompt in zip(
                profiles[: max(1, min(len(profiles), 2))],
                [
                    "What matters most in this scenario now?",
                    "What would increase trust fastest?",
                ],
                strict=False,
            )
        ]
        interviews_response = client.post(
            "/api/simulation/interview/batch",
            json={
                "simulation_id": simulation_id,
                "interviews": batch_interviews,
            },
        )
        assert interviews_response.status_code == 200
        interview_results = interviews_response.json()["data"]["interview_results"]
        assert len(interview_results) == len(batch_interviews) * 2
        assert all(item["response"] for item in interview_results)
        assert {item["platform"] for item in interview_results} == {"twitter", "reddit"}

        interview_all_response = client.post(
            "/api/simulation/interview/all",
            json={
                "simulation_id": simulation_id,
                "prompt": "What should analysts monitor next?",
                "platform": "reddit",
            },
        )
        assert interview_all_response.status_code == 200
        assert interview_all_response.json()["data"]["interviews_count"] == len(profiles)

        interview_history_response = client.post(
            "/api/simulation/interview/history",
            json={"simulation_id": simulation_id, "limit": 20},
        )
        assert interview_history_response.status_code == 200
        assert interview_history_response.json()["data"]["count"] >= (1 + len(interview_results) + len(profiles))

        report_response = client.post(
            "/api/report/generate",
            json={"simulation_id": simulation_id},
        )
        assert report_response.status_code == 200
        report_id = report_response.json()["data"]["report_id"]

        report_status = wait_for_glass_status(
            client,
            "POST",
            "/api/report/generate/status",
            json_payload={"simulation_id": simulation_id},
            terminal_statuses={"completed"},
            timeout_seconds=10.0,
        )
        assert report_status["report_id"] == report_id
        assert report_status["outline_ready"] is True
        assert len(report_status["completed_sections"]) >= 4
        assert report_status["completed_sections"] == list(range(1, len(report_status["completed_sections"]) + 1))
        assert "evidence_summary" in report_status

        report_check_response = client.get(f"/api/report/check/{simulation_id}")
        assert report_check_response.status_code == 200
        assert report_check_response.json()["data"]["interview_unlocked"] is True

        report_by_sim_response = client.get(f"/api/report/by-simulation/{simulation_id}")
        assert report_by_sim_response.status_code == 200
        assert report_by_sim_response.json()["has_report"] is True

        report_list_response = client.get("/api/report/list", params={"simulation_id": simulation_id})
        assert report_list_response.status_code == 200
        assert report_list_response.json()["count"] >= 1

        report_response = client.get(f"/api/report/{report_id}")
        assert report_response.status_code == 200
        report_payload = report_response.json()["data"]
        assert "evidence_summary" in report_payload
        assert report_payload["evidence_summary"]["runtime"]["actions"] > 0

        report_progress_response = client.get(f"/api/report/{report_id}/progress")
        assert report_progress_response.status_code == 200
        assert report_progress_response.json()["data"]["status"] == "completed"

        report_download_response = client.get(f"/api/report/{report_id}/download")
        assert report_download_response.status_code == 200
        assert "Platform Split" in report_download_response.text

        sections_response = client.get(f"/api/report/{report_id}/sections")
        assert sections_response.status_code == 200
        sections = sections_response.json()["data"]["sections"]
        assert len(sections) >= 4
        assert any("Persona Interviews" in item["content"] for item in sections)
        assert any(
            title in item["content"]
            for item in sections
            for title in (
                "Initial Adoption and Narrative Velocity",
                "The Viral Aesthetic Surge: December 2025 Holiday Campaign",
            )
        )
        assert any("Platform emphasis" in item["content"] for item in sections)

        agent_log_stream_response = client.get(f"/api/report/{report_id}/agent-log/stream")
        assert agent_log_stream_response.status_code == 200
        agent_log_stream = agent_log_stream_response.json()["data"]["logs"]
        assert any(item["action"] == "planning_complete" for item in agent_log_stream)
        assert any(item["action"] == "report_complete" for item in agent_log_stream)

        console_log_stream_response = client.get(f"/api/report/{report_id}/console-log/stream")
        assert console_log_stream_response.status_code == 200
        assert console_log_stream_response.json()["data"]["count"] >= 1

        tool_search_response = client.post(
            "/api/report/tools/search",
            json={"graph_id": task_id, "query": "trust"},
        )
        assert tool_search_response.status_code == 200
        assert "total_count" in tool_search_response.json()["data"]

        tool_stats_response = client.post(
            "/api/report/tools/statistics",
            json={"graph_id": task_id},
        )
        assert tool_stats_response.status_code == 200
        assert tool_stats_response.json()["data"]["node_count"] >= 18

        chat_response = client.post(
            "/api/report/chat",
            json={
                "simulation_id": simulation_id,
                "message": "What should the analyst team monitor first?",
                "chat_history": [{"role": "user", "content": "Summarize the main risk."}],
            },
        )
        assert chat_response.status_code == 200
        assert chat_response.json()["data"]["response"]
        assert chat_response.json()["data"]["sources"]
        tool_call_names = {item["name"] for item in chat_response.json()["data"]["tool_calls"]}
        assert "report_context" in tool_call_names
        assert "report_evidence" in tool_call_names
        assert "graph_statistics" in tool_call_names

        delete_report_response = client.delete(f"/api/report/{report_id}")
        assert delete_report_response.status_code == 200
        assert delete_report_response.json()["success"] is True
        deleted_report_response = client.get(f"/api/report/{report_id}")
        assert deleted_report_response.status_code == 200
        assert deleted_report_response.json()["success"] is False

        delete_graph_response = client.delete(f"/api/graph/delete/{task_id}")
        assert delete_graph_response.status_code == 200
        assert delete_graph_response.json()["success"] is True

        delete_project_response = client.delete(f"/api/graph/project/{ontology_payload['project_id']}")
        assert delete_project_response.status_code == 200
        assert delete_project_response.json()["success"] is True
        deleted_project_response = client.get(f"/api/graph/project/{ontology_payload['project_id']}")
        assert deleted_project_response.status_code == 200
        assert deleted_project_response.json()["success"] is False
