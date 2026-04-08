"""Compatibility helpers for the React glass frontend."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Event, Lock, Thread
import time
from typing import Any
from uuid import uuid4

from sqlmodel import Session, select

from ..config import Settings
from ..models import GraphJob, Project, Report, Simulation, SourceDocument, WorkflowStatus
from .generation import (
    build_glass_action_plan,
    build_glass_graph_snapshot,
    build_glass_interview_response,
    build_glass_ontology,
    build_glass_profiles,
    build_glass_report_package,
    build_glass_simulation_config,
    detect_social_brand_simulation_submode,
    infer_project_name,
    ontology_is_generic,
    runtime_action_line,
    top_terms,
)
from .graphiti import GraphitiClient, infer_generic_graph_label
from .oasis_runtime import send_ipc_command, write_oasis_profile_artifacts
from .runtime import ensure_data_dir, list_source_documents, sanitize_runtime_payload, sanitize_runtime_text, utc_now


def envelope_ok(data: Any) -> dict[str, Any]:
    """Return a success envelope compatible with the glass client."""
    return {"success": True, "data": data}


def envelope_error(message: str, *, data: Any | None = None) -> dict[str, Any]:
    """Return an error envelope compatible with the glass client."""
    payload = {"success": False, "error": message}
    if data is not None:
        payload["data"] = data
    return payload


SYNTHETIC_GRAPH_ERROR_MESSAGE = (
    "Real entity extraction is not available for this project. Synthetic placeholder graph generation is disabled."
)
_SYNTHETIC_GRAPH_UUID_PREFIXES = (
    "type_",
    "platform_",
    "topic_",
    "narrative_",
    "stakeholder_",
    "audience_",
)
_SYNTHETIC_GRAPH_SUMMARY_PREFIXES = (
    "Schema anchor for",
    "Primary surface for",
    "Recurring discussion theme around",
    "Narrative cluster in the",
    "Visible stakeholder in the",
    "Audience segment tracking",
)
_DISPLAY_EDGE_FAMILY_ALIASES = {
    "operates_pop_up_in": "expands_in",
    "uses_platform": "expands_in",
    "listed_on": "expands_in",
    "headquartered_in": "expands_in",
    "launched_stores_with": "expands_in",
    "partnered_with": "expands_in",
    "works_for": "represents",
    "holds_position": "represents",
    "previously_worked_at": "represents",
    "founded": "represents",
}
_DISPLAY_EDGE_FAMILY_LIMITS = {
    "competes_with": 12,
    "expands_in": 12,
    "represents": 8,
    "questions": 8,
    "comments_on": 8,
    "covers": 8,
}
_DISPLAY_GENERIC_NODE_LABELS = {"Entity", "Node", "Location"}
_DISPLAY_SYMMETRIC_FAMILIES = {"competes_with"}
_DISPLAY_NODE_LABEL_PRIORITIES = {
    "Fashion Brand": 6,
    "Competitor Brand": 6,
    "Luxury Brand": 6,
    "Consumer Cohort": 5,
    "Luxury Consumer": 5,
    "Market Analyst": 5,
    "Sustainability Activist": 5,
    "Fashion Influencer": 5,
    "Fashion Media Outlet": 5,
    "Retail Industry Analyst": 5,
    "Person": 4,
    "Organization": 3,
    "Location": 1,
}


class SyntheticGraphError(RuntimeError):
    """Raised when a graph payload is only the placeholder scaffold."""


def graph_payload_is_synthetic(payload: dict[str, Any]) -> bool:
    """Detect the legacy placeholder scaffold so it cannot pass as a real graph."""
    nodes = payload.get("nodes", [])
    if not isinstance(nodes, list) or not nodes:
        return False

    synthetic_markers = 0
    inspected_nodes = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        inspected_nodes += 1
        node_uuid = str(node.get("uuid") or "")
        summary = str(node.get("summary") or "")
        if node_uuid.startswith(_SYNTHETIC_GRAPH_UUID_PREFIXES) or summary.startswith(
            _SYNTHETIC_GRAPH_SUMMARY_PREFIXES
        ):
            synthetic_markers += 1

    if inspected_nodes == 0:
        return False
    return synthetic_markers >= max(6, inspected_nodes // 2)


def ensure_real_graph_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Reject placeholder graph scaffolds so the UI can surface a real failure."""
    if graph_payload_is_synthetic(payload):
        raise SyntheticGraphError(SYNTHETIC_GRAPH_ERROR_MESSAGE)
    return payload


def persist_graph_job_failure(
    session: Session,
    *,
    graph_job: GraphJob,
    project: Project | None,
    message: str,
) -> None:
    """Persist a terminal graph-build failure in the compat workflow."""
    graph_job.status = WorkflowStatus.failed
    graph_job.progress_percent = 0
    graph_job.status_message = message
    graph_job.summary = message
    graph_job.error_message = message
    graph_job.node_count = 0
    graph_job.edge_count = 0
    graph_job.completed_at = None
    graph_job.updated_at = utc_now()
    session.add(graph_job)
    if project is not None:
        project.status = WorkflowStatus.failed
        project.updated_at = utc_now()
        session.add(project)
    session.commit()


def glass_root(settings: Settings) -> Path:
    """Return the compatibility artifact root."""
    directory = ensure_data_dir(settings) / "glass"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _subdir(settings: Settings, *parts: str) -> Path:
    directory = glass_root(settings).joinpath(*parts)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def project_dir(settings: Settings, project_id: str) -> Path:
    return _subdir(settings, "projects", project_id)


def graph_dir(settings: Settings) -> Path:
    return _subdir(settings, "graphs")


def simulation_dir(settings: Settings, simulation_id: str) -> Path:
    return _subdir(settings, "simulations", simulation_id)


def report_dir(settings: Settings, report_id: str) -> Path:
    return _subdir(settings, "reports", report_id)


def report_evidence_path(settings: Settings, report_id: str) -> Path:
    return report_dir(settings, report_id) / "evidence.json"


def load_report_evidence(settings: Settings, report_id: str) -> dict[str, Any]:
    payload = _read_json(report_evidence_path(settings, report_id), {})
    return payload if isinstance(payload, dict) else {}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(sanitize_runtime_text(content), encoding="utf-8")
    temp_path.replace(path)


def _write_json(path: Path, payload: Any) -> None:
    sanitized_payload = sanitize_runtime_payload(payload)
    _write_text(path, json.dumps(sanitized_payload, indent=2, ensure_ascii=False))


def _append_text(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(sanitize_runtime_text(line))


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    sanitized_payload = sanitize_runtime_payload(payload)
    _append_text(path, json.dumps(sanitized_payload, ensure_ascii=False) + "\n")


def project_metadata_path(settings: Settings, project_id: str) -> Path:
    return project_dir(settings, project_id) / "metadata.json"


def load_project_metadata(settings: Settings, project_id: str) -> dict[str, Any]:
    return _read_json(project_metadata_path(settings, project_id), {})


def save_project_metadata(settings: Settings, project_id: str, payload: dict[str, Any]) -> None:
    _write_json(project_metadata_path(settings, project_id), payload)


def graph_live_path(settings: Settings, graph_id: str) -> Path:
    return graph_dir(settings) / f"{graph_id}.json"


def graph_base_path(settings: Settings, graph_id: str) -> Path:
    return graph_dir(settings) / f"{graph_id}.base.json"


def load_graph_payload(settings: Settings, graph_id: str) -> dict[str, Any]:
    path = graph_live_path(settings, graph_id)
    payload = _read_json(path, {"nodes": [], "edges": [], "metadata": {}})
    normalized_payload, changed = _normalize_cached_graph_payload(payload)
    if changed:
        _write_json(path, normalized_payload)
    return normalized_payload


def load_graph_base_payload(settings: Settings, graph_id: str) -> dict[str, Any]:
    path = graph_base_path(settings, graph_id)
    payload = _read_json(path, {"nodes": [], "edges": [], "metadata": {}})
    payload, changed = _normalize_cached_graph_payload(payload)
    if changed:
        _write_json(path, payload)
    if payload.get("nodes"):
        return payload
    return load_graph_payload(settings, graph_id)


def save_graph_payload(settings: Settings, graph_id: str, payload: dict[str, Any]) -> None:
    _write_json(graph_live_path(settings, graph_id), payload)


def save_graph_base_payload(settings: Settings, graph_id: str, payload: dict[str, Any]) -> None:
    _write_json(graph_base_path(settings, graph_id), payload)


def _normalize_cached_graph_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Refresh cached graph payloads so older saved graphs inherit the latest generic-node normalization."""
    if not isinstance(payload, dict):
        return {"nodes": [], "edges": [], "metadata": {}}, True
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return payload, False

    changed = False
    normalized_nodes: list[dict[str, Any]] = []
    for item in nodes:
        if not isinstance(item, dict):
            normalized_nodes.append(item)
            continue
        labels = [str(label).strip() for label in (item.get("labels") or []) if str(label).strip()]
        current_label = str(item.get("label") or (labels[0] if labels else "Entity")).strip() or "Entity"
        inferred_label = None
        if current_label in {"Entity", "Node"} or set(labels or [current_label]).issubset({"Entity", "Node"}):
            inferred_label = infer_generic_graph_label(
                current_label=current_label,
                name=str(item.get("name") or ""),
                summary=str(item.get("summary") or ""),
                attributes=item.get("attributes") or {},
            )
        if inferred_label and (current_label != inferred_label or labels != [inferred_label]):
            item = {**item, "label": inferred_label, "labels": [inferred_label]}
            changed = True
        normalized_nodes.append(item)

    normalized_payload = dict(payload)
    normalized_payload["nodes"] = normalized_nodes
    metadata = dict(normalized_payload.get("metadata") or {})
    entity_types = sorted(
        {
            str(item.get("label") or "").strip()
            for item in normalized_nodes
            if isinstance(item, dict) and str(item.get("label") or "").strip() not in {"", "Entity", "Node"}
        }
    )
    if metadata.get("entity_types") != entity_types:
        metadata["entity_types"] = entity_types
        changed = True
    normalized_payload["metadata"] = metadata
    return normalized_payload, changed


def _display_relation_family(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    if not normalized:
        return "related_to"
    return _DISPLAY_EDGE_FAMILY_ALIASES.get(normalized, normalized)


def compact_graph_payload_for_display(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a thinner canvas-oriented graph view without mutating the raw stored graph."""
    if not isinstance(payload, dict):
        return {"nodes": [], "edges": [], "metadata": {}}

    nodes = [item for item in (payload.get("nodes") or []) if isinstance(item, dict)]
    raw_edges = [item for item in (payload.get("edges") or []) if isinstance(item, dict)]
    if not nodes or not raw_edges:
        return payload
    if len(nodes) <= 80 and len(raw_edges) <= 45 and (len(raw_edges) / max(len(nodes), 1)) <= 0.7:
        metadata = dict(payload.get("metadata") or {})
        metadata["raw_node_count"] = int(metadata.get("node_count") or len(nodes))
        metadata["raw_edge_count"] = int(metadata.get("edge_count") or len(raw_edges))
        metadata["display_node_count"] = len(nodes)
        metadata["display_edge_count"] = len(raw_edges)
        metadata["node_count"] = len(nodes)
        metadata["edge_count"] = len(raw_edges)
        return {
            **payload,
            "metadata": metadata,
        }

    node_lookup = {str(item.get("uuid") or ""): item for item in nodes if item.get("uuid")}
    ranked_edges: list[tuple[int, int, str, str, dict[str, Any]]] = []
    node_degree: Counter[str] = Counter()
    for index, edge in enumerate(raw_edges):
        source_uuid = str(edge.get("source_uuid") or "")
        target_uuid = str(edge.get("target_uuid") or "")
        if source_uuid:
            node_degree[source_uuid] += 1
        if target_uuid:
            node_degree[target_uuid] += 1
        relation_family = _display_relation_family(str(edge.get("relation_type") or edge.get("name") or ""))
        source_label = str(node_lookup.get(source_uuid, {}).get("label") or "Entity")
        target_label = str(node_lookup.get(target_uuid, {}).get("label") or "Entity")
        score = 0
        if source_label not in _DISPLAY_GENERIC_NODE_LABELS:
            score += 5
        if target_label not in _DISPLAY_GENERIC_NODE_LABELS:
            score += 5
        if relation_family in _DISPLAY_EDGE_FAMILY_LIMITS:
            score += 5
        if edge.get("fact"):
            score += 2
        if source_label == "Fashion Brand" or target_label == "Fashion Brand":
            score += 3
        if relation_family == "competes_with" and source_label == "Fashion Brand" and target_label == "Fashion Brand":
            score += 4
        ranked_edges.append((score, index, relation_family, source_uuid, edge))

    ranked_edges.sort(key=lambda item: (-item[0], item[1]))
    family_counts: Counter[str] = Counter()
    seen_keys: set[tuple[str, ...]] = set()
    display_edges: list[dict[str, Any]] = []

    for _score, _index, relation_family, source_uuid, edge in ranked_edges:
        target_uuid = str(edge.get("target_uuid") or "")
        if relation_family in _DISPLAY_SYMMETRIC_FAMILIES:
            dedupe_key = tuple(sorted((source_uuid, target_uuid))) + (relation_family,)
        else:
            dedupe_key = (source_uuid, target_uuid, relation_family)
        if dedupe_key in seen_keys:
            continue
        family_limit = _DISPLAY_EDGE_FAMILY_LIMITS.get(relation_family, 4)
        if family_counts[relation_family] >= family_limit:
            continue
        seen_keys.add(dedupe_key)
        family_counts[relation_family] += 1
        display_edges.append(
            {
                **edge,
                "name": relation_family,
                "relation_type": relation_family,
            }
        )

    global_cap = max(20, min(len(raw_edges), int(len(nodes) * 0.45)))
    display_edges = display_edges[:global_cap]
    referenced_node_uuids = {
        str(item.get("source_uuid") or "")
        for item in display_edges
        if str(item.get("source_uuid") or "")
    } | {
        str(item.get("target_uuid") or "")
        for item in display_edges
        if str(item.get("target_uuid") or "")
    }
    def node_priority(item: dict[str, Any]) -> tuple[int, int, str]:
        label = str(item.get("label") or "Entity")
        uuid = str(item.get("uuid") or "")
        score = _DISPLAY_NODE_LABEL_PRIORITIES.get(label, 0)
        return (node_degree.get(uuid, 0) * 3 + score, node_degree.get(uuid, 0), str(item.get("name") or ""))

    ordered_nodes = sorted(nodes, key=node_priority, reverse=True)
    if referenced_node_uuids:
        display_nodes = [
            item
            for item in ordered_nodes
            if str(item.get("uuid") or "") in referenced_node_uuids
        ]
    else:
        display_node_cap = max(20, min(len(nodes), int(len(nodes) * 0.6)))
        display_nodes = ordered_nodes[:display_node_cap]

    metadata = dict(payload.get("metadata") or {})
    metadata["raw_node_count"] = int(metadata.get("node_count") or len(nodes))
    metadata["raw_edge_count"] = int(metadata.get("edge_count") or len(raw_edges))
    metadata["display_node_count"] = len(display_nodes)
    metadata["display_edge_count"] = len(display_edges)
    metadata["node_count"] = len(display_nodes)
    metadata["edge_count"] = len(display_edges)
    metadata["edge_types"] = sorted(
        {
            str(item.get("relation_type") or item.get("name") or "").strip()
            for item in display_edges
            if str(item.get("relation_type") or item.get("name") or "").strip()
        }
    )
    return {
        **payload,
        "nodes": display_nodes,
        "edges": display_edges,
        "metadata": metadata,
    }


def fetch_graphiti_payload(settings: Settings, graph_id: str) -> dict[str, Any]:
    """Load a graph payload directly from Graphiti."""
    client = GraphitiClient(settings)
    try:
        return client.get_graph_payload(graph_id)
    finally:
        client.close()


def reset_graph_from_base(settings: Settings, graph_id: str) -> dict[str, Any]:
    payload = _read_json(graph_base_path(settings, graph_id), {"nodes": [], "edges": [], "metadata": {}})
    save_graph_payload(settings, graph_id, payload)
    return payload


def prepare_task_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_dir(settings, simulation_id) / "prepare_task.json"


def simulation_state_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_dir(settings, simulation_id) / "state.json"


def simulation_profiles_path(settings: Settings, simulation_id: str, platform: str) -> Path:
    return simulation_dir(settings, simulation_id) / f"profiles_{platform}.json"


def simulation_config_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_dir(settings, simulation_id) / "config.json"


def simulation_entities_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_dir(settings, simulation_id) / "prepared_entities.json"


def simulation_preparation_manifest_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_dir(settings, simulation_id) / "preparation_manifest.json"


def simulation_actions_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_dir(settings, simulation_id) / "actions.json"


def simulation_posts_path(settings: Settings, simulation_id: str, platform: str) -> Path:
    return simulation_dir(settings, simulation_id) / f"posts_{platform}.json"


def simulation_comments_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_dir(settings, simulation_id) / "comments.json"


def simulation_env_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_dir(settings, simulation_id) / "env.json"


def simulation_plan_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_dir(settings, simulation_id) / "action_plan.json"


def simulation_interviews_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_dir(settings, simulation_id) / "interviews.json"


def load_simulation_state(settings: Settings, simulation_id: str) -> dict[str, Any]:
    default = {
        "status": "created",
        "runner_status": "idle",
        "profiles_generation_active": False,
        "config_generation_active": False,
        "current_round": 0,
        "total_rounds": 0,
        "progress_percent": 0,
        "twitter_running": False,
        "reddit_running": False,
        "twitter_actions_count": 0,
        "reddit_actions_count": 0,
        "total_actions_count": 0,
        "expected_entities_count": 0,
        "profiles_count": 0,
        "graph_id": None,
        "report_id": None,
        "error": "",
    }
    state = _read_json(simulation_state_path(settings, simulation_id), default)
    if not isinstance(state, dict):
        return default
    return {**default, **state}


def save_simulation_state(settings: Settings, simulation_id: str, payload: dict[str, Any]) -> None:
    _write_json(simulation_state_path(settings, simulation_id), payload)


def load_simulation_profiles(settings: Settings, simulation_id: str, platform: str) -> list[dict[str, Any]]:
    payload = _read_json(simulation_profiles_path(settings, simulation_id, platform), [])
    return payload if isinstance(payload, list) else []


def load_simulation_config(settings: Settings, simulation_id: str) -> dict[str, Any]:
    payload = _read_json(simulation_config_path(settings, simulation_id), {})
    return payload if isinstance(payload, dict) else {}


def load_simulation_entities(settings: Settings, simulation_id: str) -> dict[str, Any]:
    payload = _read_json(simulation_entities_path(settings, simulation_id), {})
    return payload if isinstance(payload, dict) else {}


def load_simulation_actions(settings: Settings, simulation_id: str) -> list[dict[str, Any]]:
    payload = _read_json(simulation_actions_path(settings, simulation_id), [])
    return payload if isinstance(payload, list) else []


def load_simulation_posts(settings: Settings, simulation_id: str, platform: str) -> list[dict[str, Any]]:
    payload = _read_json(simulation_posts_path(settings, simulation_id, platform), [])
    return payload if isinstance(payload, list) else []


def load_simulation_comments(settings: Settings, simulation_id: str) -> list[dict[str, Any]]:
    payload = _read_json(simulation_comments_path(settings, simulation_id), [])
    return payload if isinstance(payload, list) else []


def load_simulation_interviews(settings: Settings, simulation_id: str) -> list[dict[str, Any]]:
    payload = _read_json(simulation_interviews_path(settings, simulation_id), [])
    return payload if isinstance(payload, list) else []


def append_simulation_interviews(settings: Settings, simulation_id: str, entries: list[dict[str, Any]]) -> None:
    history = load_simulation_interviews(settings, simulation_id)
    history.extend(entries)
    _write_json(simulation_interviews_path(settings, simulation_id), history)


def load_simulation_env(settings: Settings, simulation_id: str) -> dict[str, Any]:
    payload = _read_json(
        simulation_env_path(settings, simulation_id),
        {
            "status": "idle",
            "twitter_available": False,
            "reddit_available": False,
            "closed_at": "",
        },
    )
    if not isinstance(payload, dict):
        return {
            "status": "idle",
            "twitter_available": False,
            "reddit_available": False,
            "closed_at": "",
        }
    return {
        "status": str(payload.get("status") or "idle"),
        "twitter_available": bool(payload.get("twitter_available")),
        "reddit_available": bool(payload.get("reddit_available")),
        "closed_at": str(payload.get("closed_at") or ""),
    }


def save_simulation_env(settings: Settings, simulation_id: str, payload: dict[str, Any]) -> None:
    _write_json(simulation_env_path(settings, simulation_id), payload)


def latest_graph_job(session: Session, project_id: str) -> GraphJob | None:
    statement = (
        select(GraphJob)
        .where(GraphJob.project_id == project_id)
        .order_by(GraphJob.created_at.desc())
    )
    return session.exec(statement).first()


def latest_simulation(session: Session, project_id: str) -> Simulation | None:
    statement = (
        select(Simulation)
        .where(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.desc())
    )
    return session.exec(statement).first()


def latest_report(session: Session, simulation_id: str) -> Report | None:
    statement = (
        select(Report)
        .where(Report.simulation_id == simulation_id)
        .order_by(Report.created_at.desc())
    )
    return session.exec(statement).first()


def glass_project_status(project: Project, graph_job: GraphJob | None, metadata: dict[str, Any]) -> str:
    """Map clean-room state to the glass workflow status labels."""
    if graph_job:
        if graph_job.status == WorkflowStatus.failed:
            return "failed"
        if graph_job.status in {WorkflowStatus.queued, WorkflowStatus.running}:
            return "graph_building"
        if graph_job.status == WorkflowStatus.completed:
            return "graph_completed"
    if metadata.get("ontology"):
        return "ontology_generated"
    return "created"


def ensure_graph_materialized(
    session: Session,
    settings: Settings,
    *,
    project: Project,
    graph_job: GraphJob,
) -> dict[str, Any]:
    """Ensure a graph payload exists for a completed graph job."""
    live_path = graph_live_path(settings, graph_job.id)
    if live_path.exists():
        return ensure_real_graph_payload(load_graph_payload(settings, graph_job.id))

    if settings.graph_backend == "graphiti" and settings.llm_provider != "test":
        try:
            payload = fetch_graphiti_payload(settings, graph_job.id)
        except Exception as exc:  # noqa: BLE001
            raise SyntheticGraphError(f"Stored real graph payload is unavailable: {exc}") from exc
        ensure_real_graph_payload(payload)
        save_graph_base_payload(settings, graph_job.id, payload)
        save_graph_payload(settings, graph_job.id, payload)
        return payload

    metadata = load_project_metadata(settings, project.id)
    ontology = metadata.get("ontology", {})
    documents = list_source_documents(session, project.id)
    payload = build_glass_graph_snapshot(
        project=project,
        source_digest=graph_job.source_digest,
        ontology=ontology if isinstance(ontology, dict) else {},
        source_texts=[item.extracted_text for item in documents if item.extracted_text],
        node_budget=max(18, min(graph_job.node_count or 24, 28)),
    )
    ensure_real_graph_payload(payload)
    save_graph_base_payload(settings, graph_job.id, payload)
    save_graph_payload(settings, graph_job.id, payload)
    return payload


def build_history_entry(
    session: Session,
    settings: Settings,
    simulation: Simulation,
) -> dict[str, Any]:
    """Build the glass history payload for a simulation."""
    project = session.get(Project, simulation.project_id)
    if not project:
        return {}
    metadata = load_project_metadata(settings, project.id)
    graph_job = latest_graph_job(session, project.id)
    report = latest_report(session, simulation.id)
    sim_state = load_simulation_state(settings, simulation.id)
    documents = list_source_documents(session, project.id)
    graph_id = sim_state.get("graph_id") or (graph_job.id if graph_job else None)
    graph_payload = load_graph_payload(settings, graph_id) if graph_id else {}
    graph_metadata = (
        graph_payload.get("metadata", {})
        if graph_id and not graph_payload_is_synthetic(graph_payload)
        else {}
    )
    ontology = metadata.get("ontology") or {}
    entity_types = [
        item.get("name")
        for item in ontology.get("entity_types", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    return {
        "simulation_id": simulation.id,
        "project_id": project.id,
        "report_id": report.id if report else sim_state.get("report_id"),
        "graph_id": graph_id,
        "status": sim_state.get("runner_status")
        if sim_state.get("runner_status") in {"running", "completed", "failed", "stopped"}
        else sim_state.get("status", "created"),
        "simulation_requirement": project.scenario_brief,
        "files": [
            {"filename": item.filename, "size": item.byte_size}
            for item in documents
        ],
        "entity_types": entity_types,
        "entities_count": graph_metadata.get("node_count"),
        "profiles_count": sim_state.get("profiles_count"),
        "current_round": sim_state.get("current_round"),
        "total_rounds": sim_state.get("total_rounds"),
        "created_at": simulation.created_at.isoformat(),
    }


def graph_entities_for_preparation(
    graph_payload: dict[str, Any],
    *,
    entity_types: set[str] | None = None,
    scenario_text: str = "",
) -> dict[str, Any]:
    """Extract a graph-grounded entity inventory for simulation preparation."""
    def label_slug(value: str) -> str:
        return "".join(char for char in str(value or "").lower() if char.isalnum())

    label_aliases = {
        "luxurybrand": "Luxury Brand",
        "fashionbrand": "Fashion Brand",
        "brand": "Brand",
        "competitorbrand": "Competitor Brand",
        "sportswearcompetitor": "Sportswear Competitor",
        "executive": "Executive",
        "fashioninfluencer": "Fashion Influencer",
        "consumercohort": "Consumer Cohort",
        "consumersegment": "Consumer Cohort",
        "genzconsumer": "Consumer Cohort",
        "luxuryconsumer": "Luxury Consumer",
        "fashionmediaoutlet": "Fashion Media Outlet",
        "mediaoutlet": "Media Outlet",
        "marketanalyst": "Market Analyst",
        "retailindustryanalyst": "Retail Industry Analyst",
        "geopoliticalcommentator": "Geopolitical Commentator",
        "sustainabilityactivist": "Sustainability Activist",
        "discountshopper": "Discount Shopper",
        "brandpurist": "Brand Purist",
        "athleteambassador": "Athlete Ambassador",
        "person": "Person",
        "organization": "Organization",
        "institutionalactor": "Institutional Actor",
        "creatorgroup": "Creator Group",
        "internalteam": "Internal Team",
        "campaign": "Campaign",
        "retailchannel": "Retail Channel",
        "retailpartner": "Retail Channel",
        "region": "Region",
        "audiencesegment": "Audience Segment",
        "productline": "Product Line",
        "platform": "Platform",
        "event": "Event",
        "location": "Location",
        "theme": "Theme",
        "signal": "Signal",
        "node": "Node",
        "entity": "Entity",
    }

    scenario_mode = detect_social_brand_simulation_submode(scenario_text)

    actor_labels = {
        "Luxury Brand",
        "Fashion Brand",
        "Competitor Brand",
        "Sportswear Competitor",
        "Executive",
        "Fashion Influencer",
        "Consumer Cohort",
        "Fashion Media Outlet",
        "Market Analyst",
        "Retail Industry Analyst",
        "Geopolitical Commentator",
        "Sustainability Activist",
        "Discount Shopper",
        "Brand Purist",
        "Athlete Ambassador",
        "Institutional Actor",
        "Person",
        "Audience Segment",
        "Media Outlet",
        "Brand",
        "Organization",
        "Creator Group",
        "Internal Team",
        "Campaign",
        "Retail Channel",
        "Region",
    }
    supporting_institutional_labels: set[str] = {
        "Institutional Actor",
        "Organization",
        "Creator Group",
        "Internal Team",
        "Campaign",
        "Retail Channel",
        "Region",
    }
    product_labels = {"Product Line"}
    excluded_context_labels = {"Node", "Signal", "Simulated Agent", "Theme", "Platform", "Event"}
    platform_names = {"instagram", "tiktok", "wechat", "pinterest", "youtube", "reddit", "twitter", "x"}
    location_names = {
        "uk",
        "united kingdom",
        "usa",
        "u.s.",
        "us",
        "china",
        "japan",
        "france",
        "italy",
        "london",
        "los angeles",
        "tokyo",
        "seoul",
        "south korea",
        "new york",
        "paris",
    }
    consumer_terms = {
        "consumer",
        "consumers",
        "shopper",
        "shoppers",
        "audience",
        "cohort",
        "millennial",
        "millennials",
        "gen z",
        "loyalist",
        "loyalists",
        "community",
        "communities",
        "luxury buyers",
        "aspirational",
    }
    influencer_terms = {"influencer", "creator", "creators", "model", "stylist", "ambassador", "tastemaker"}
    media_terms = {"media", "magazine", "press", "publication", "editorial", "news", "outlet", "journal"}
    analyst_terms = {"analyst", "analysts", "research", "strategy", "strategist", "economist"}
    geopolitical_terms = {"geopolitical", "nationalist", "backlash", "heritage branding", "american heritage", "domestic brand", "state media"}
    sustainability_terms = {"sustainab", "greenwashing", "labor", "sourcing", "supply chain", "ethic", "activist", "critic"}
    competitor_terms = {
        "competitor",
        "competitors",
        "domestic brand",
        "domestic brands",
        "local brand",
        "local brands",
        "li-ning",
        "anta",
        "pvh",
        "burberry",
        "hugo boss",
        "tommy hilfiger",
        "lacoste",
        "capri",
    }
    commentator_terms = {
        "commentator",
        "commentators",
        "critic",
        "critics",
        "watchdog",
        "watchdogs",
        "journalist",
        "journalists",
        "advocate",
        "advocates",
        "editor",
        "editors",
        "state media",
    }
    discount_terms = {"discount", "off-price", "off price", "tj maxx", "rack", "bargain", "deal"}
    purist_terms = {"purist", "exclusiv", "elevation", "brand discipline", "prestige"}
    athlete_terms = {"athlete", "olympic", "team usa", "sports", "sport", "runner", "uniform"}
    person_terms = {
        "founder",
        "ceo",
        "chief",
        "president",
        "director",
        "designer",
        "executive",
        "chairman",
        "chairwoman",
        "editor",
    }
    brand_terms = {"brand", "label", "collection", "fragrance", "fashion house", "line", "apparel", "competitor", "sportswear"}
    organization_terms = {
        "corp",
        "corporation",
        "group",
        "holdings",
        "beauty",
        "design",
        "retail",
        "partner",
        "partners",
        "operator",
        "platform",
        "license",
        "licensing",
        "store",
        "stores",
        "office",
        "company",
        "lp",
        "inc",
        "plc",
        "sa",
        "llc",
    }

    scenario_actor_sets: dict[str, tuple[set[str], set[str], set[str]]] = {
        "market_expansion": (
            {"Luxury Brand", "Competitor Brand", "Luxury Consumer", "Market Analyst", "Sustainability Activist", "Person", "Organization"},
            {"Organization"},
            set(),
        ),
        "channel_strategy": (
            {"Fashion Brand", "Discount Shopper", "Brand Purist", "Retail Industry Analyst", "Person", "Organization"},
            {"Organization"},
            set(),
        ),
        "sports_partnership": (
            {"Fashion Brand", "Athlete Ambassador", "Sportswear Competitor", "Fashion Media Outlet", "Person", "Organization"},
            {"Organization"},
            set(),
        ),
        "sustainability_launch": (
            {"Fashion Brand", "Sustainability Activist", "Consumer Cohort", "Fashion Media Outlet", "Person", "Organization"},
            {"Organization"},
            set(),
        ),
    }
    if scenario_mode in scenario_actor_sets:
        actor_labels, supporting_institutional_labels, product_labels = scenario_actor_sets[scenario_mode]

    scenario_focus_brand_markers: set[str] = set()
    possessive_match = re.search(
        r"\b([A-Z][A-Za-z&'.-]+(?:\s+[A-Z][A-Za-z&'.-]+){0,3})'s\b",
        scenario_text,
    )
    if possessive_match:
        scenario_focus_brand_markers.add(possessive_match.group(1).strip().lower())
    if not scenario_focus_brand_markers:
        for candidate in re.findall(r"\b[A-Z][A-Za-z&'.-]+(?:\s+[A-Z][A-Za-z&'.-]+){1,3}\b", scenario_text):
            lowered_candidate = candidate.strip().lower()
            if any(
                token in lowered_candidate
                for token in {
                    "tier 1",
                    "tier 2",
                    "western",
                    "chinese",
                    "wechat",
                    "social media",
                    "market analysts",
                    "geopolitical commentators",
                    "sustainability critics",
                    "fashion journalists",
                    "tier",
                    "cities",
                }
            ):
                continue
            scenario_focus_brand_markers.add(lowered_candidate)
            break

    def canonical_label(value: str) -> str:
        normalized = label_slug(value)
        if normalized in label_aliases:
            return label_aliases[normalized]
        cleaned = str(value or "").strip()
        return cleaned or "Entity"

    def is_context_name(name: str, summary: str) -> bool:
        lowered_name = name.strip().lower()
        lowered_summary = summary.strip().lower()
        if not lowered_name:
            return True
        if lowered_name in location_names:
            return True
        if re.fullmatch(r"tier\s*\d+", lowered_name):
            return True
        if any(token in lowered_summary for token in {"city", "country", "region", "province", "territory"}):
            return True
        if len(lowered_name) <= 2 and lowered_name not in {"uk", "us"}:
            return True
        return False

    def infer_generic_label(
        *,
        node_name: str,
        summary: str,
        related_nodes: list[dict[str, Any]],
    ) -> str | None:
        if is_context_name(node_name, summary):
            return None
        lowered_name = node_name.lower()
        lowered_summary = summary.lower()
        related_labels = Counter(
            canonical_label(str((item.get("labels") or ["Entity"])[0] or "Entity"))
            for item in related_nodes
            if item.get("labels")
        )
        hint_text = " ".join(
            [
                lowered_name,
                lowered_summary,
                " ".join(str(item.get("name") or "").lower() for item in related_nodes[:8]),
                " ".join(label.lower() for label in related_labels.elements()),
            ]
        )
        name_summary_hint = f"{lowered_name} {lowered_summary}"
        if scenario_mode == "market_expansion":
            node_matches_focus_brand = any(marker in lowered_name for marker in scenario_focus_brand_markers)
            brand_like = node_matches_focus_brand or any(term in name_summary_hint for term in brand_terms)
            if any(term in name_summary_hint for term in analyst_terms):
                return "Market Analyst"
            if any(term in name_summary_hint for term in sustainability_terms):
                return "Sustainability Activist"
            if lowered_name in platform_names:
                return "Organization"
            if any(term in name_summary_hint for term in competitor_terms) and (
                brand_like or "brand" in name_summary_hint or "competitor" in name_summary_hint
            ):
                return "Competitor Brand"
            if any(term in name_summary_hint for term in commentator_terms | geopolitical_terms | sustainability_terms | media_terms):
                return "Organization"
            if any(term in name_summary_hint for term in organization_terms):
                return "Organization"
            if node_matches_focus_brand:
                return "Luxury Brand"
            if brand_like and not is_context_name(node_name, summary):
                return "Competitor Brand"
            if any(term in name_summary_hint for term in consumer_terms):
                return "Luxury Consumer"
            if any(term in name_summary_hint for term in person_terms):
                return "Person"
        if scenario_mode == "channel_strategy":
            if any(term in name_summary_hint for term in discount_terms):
                return "Discount Shopper"
            if any(term in name_summary_hint for term in purist_terms):
                return "Brand Purist"
            if any(term in name_summary_hint for term in analyst_terms | media_terms):
                return "Retail Industry Analyst"
            if any(term in name_summary_hint for term in brand_terms):
                return "Fashion Brand"
            if any(term in name_summary_hint for term in consumer_terms | person_terms):
                return "Person"
            if lowered_name in platform_names or any(term in name_summary_hint for term in organization_terms):
                return "Organization"
        if scenario_mode == "sports_partnership":
            if any(term in name_summary_hint for term in athlete_terms):
                return "Athlete Ambassador"
            if any(term in name_summary_hint for term in {"nike", "adidas", "under armour", "sportswear"}):
                return "Sportswear Competitor"
            if any(term in name_summary_hint for term in media_terms):
                return "Fashion Media Outlet"
            if any(term in name_summary_hint for term in brand_terms):
                return "Fashion Brand"
            if any(term in name_summary_hint for term in person_terms | consumer_terms):
                return "Person"
            if lowered_name in platform_names or any(term in name_summary_hint for term in organization_terms):
                return "Organization"
        if scenario_mode == "sustainability_launch":
            if any(term in name_summary_hint for term in sustainability_terms):
                return "Sustainability Activist"
            if any(term in name_summary_hint for term in consumer_terms):
                return "Consumer Cohort"
            if any(term in name_summary_hint for term in media_terms):
                return "Fashion Media Outlet"
            if any(term in name_summary_hint for term in brand_terms):
                return "Fashion Brand"
            if any(term in name_summary_hint for term in person_terms):
                return "Person"
            if lowered_name in platform_names or any(term in name_summary_hint for term in organization_terms):
                return "Organization"
        if lowered_name in platform_names:
            return "Organization"
        if any(term in hint_text for term in consumer_terms):
            return "Consumer Cohort"
        if any(term in hint_text for term in influencer_terms):
            return "Fashion Influencer"
        if any(term in hint_text for term in media_terms):
            return "Fashion Media Outlet"
        if any(term in hint_text for term in person_terms):
            return "Person"
        if any(term in hint_text for term in organization_terms):
            return "Organization"
        if any(term in hint_text for term in brand_terms):
            return "Luxury Brand"
        if related_labels:
            top_label, top_count = related_labels.most_common(1)[0]
            if top_label in actor_labels | product_labels and top_count >= 2:
                if top_label == "Luxury Brand":
                    return "Organization"
                return top_label
        if related_nodes:
            return "Organization"
        if summary:
            return "Organization"
        return None

    nodes = graph_payload.get("nodes", [])
    edges = graph_payload.get("edges", [])
    scenario_lower = scenario_text.lower()
    normalized_entity_types = {canonical_label(item) for item in (entity_types or set())}
    node_lookup = {
        str(item.get("uuid")): item
        for item in nodes
        if isinstance(item, dict) and item.get("uuid")
    }

    ranked_entities: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_uuid = str(node.get("uuid") or "")
        raw_label = canonical_label(str(node.get("label") or "Entity"))
        if raw_label in excluded_context_labels:
            continue
        node_name = str(node.get("name") or "").strip()
        if not node_name:
            continue
        related_edges = [
            edge
            for edge in edges
            if isinstance(edge, dict)
            and (
                str(edge.get("source_uuid") or "") == node_uuid
                or str(edge.get("target_uuid") or "") == node_uuid
            )
        ]
        related_nodes: list[dict[str, Any]] = []
        seen_related: set[str] = set()
        for edge in related_edges:
            other_uuid = (
                str(edge.get("target_uuid") or "")
                if str(edge.get("source_uuid") or "") == node_uuid
                else str(edge.get("source_uuid") or "")
            )
            other = node_lookup.get(other_uuid)
            if not other or other_uuid in seen_related:
                continue
            seen_related.add(other_uuid)
            related_nodes.append(
                {
                    "uuid": other_uuid,
                    "name": other.get("name"),
                    "labels": [canonical_label(str(other.get("label") or "Entity"))],
                    "summary": other.get("summary") or "",
                    "attributes": dict(other.get("attributes") or {}),
                }
            )
        label = raw_label
        allowed_labels = actor_labels | supporting_institutional_labels | product_labels
        should_specialize_fallback = raw_label in {"Entity", "Node"}
        if should_specialize_fallback or label not in allowed_labels or raw_label in {"Organization", "Person"}:
            inferred = infer_generic_label(
                node_name=node_name,
                summary=str(node.get("summary") or "").strip(),
                related_nodes=related_nodes,
            )
            if inferred and (
                should_specialize_fallback
                or label not in allowed_labels
                or (
                    raw_label == "Organization"
                    and inferred in {"Market Analyst", "Retail Industry Analyst", "Luxury Consumer", "Sustainability Activist"}
                )
                or (
                    raw_label == "Person"
                    and inferred in {"Fashion Influencer", "Market Analyst", "Retail Industry Analyst", "Luxury Consumer", "Sustainability Activist"}
                )
            ):
                label = inferred
            elif label not in allowed_labels:
                continue
        if normalized_entity_types and label not in normalized_entity_types:
            continue
        connected_priority = sum(
            1
            for item in related_nodes
            if str((item.get("labels") or ["Entity"])[0]) in actor_labels | product_labels
        )
        summary = str(node.get("summary") or "").strip()
        mentioned_in_scenario = bool(node_name and node_name.lower() in scenario_lower)
        related_actor_count = sum(
            1
            for item in related_nodes
            if str((item.get("labels") or ["Entity"])[0]) in actor_labels
        )
        score = 0
        if label in actor_labels:
            score += 60
        elif label in product_labels:
            score += 22
        score += min(len(related_edges), 8) * 4
        score += min(connected_priority, 5) * 5
        score += min(related_actor_count, 4) * 6
        if summary:
            score += 6
        if mentioned_in_scenario:
            score += 18
        keep = label in actor_labels | supporting_institutional_labels | product_labels
        if raw_label == "Entity":
            keep = keep and (bool(summary) or mentioned_in_scenario or len(related_edges) >= 1 or connected_priority >= 1)
        elif label in product_labels:
            keep = keep or len(related_edges) >= 2
        if is_context_name(node_name, summary) and label not in {"Market Analyst", "Retail Industry Analyst"}:
            keep = False
        if not keep:
            continue
        ranked_entities.append(
            {
                "uuid": node_uuid,
                "name": node_name,
                "labels": [label],
                "summary": summary,
                "attributes": dict(node.get("attributes") or {}),
                "related_edges": related_edges,
                "related_nodes": related_nodes,
                "centrality_score": score,
                "mentioned_in_scenario": mentioned_in_scenario,
            }
        )

    ranked_entities.sort(
        key=lambda item: (
            -int(item.get("centrality_score", 0) or 0),
            -len(item.get("related_edges") or []),
            str(item.get("name") or ""),
        )
    )
    actor_entities = [item for item in ranked_entities if str((item.get("labels") or ["Entity"])[0]) in actor_labels]
    institutional_entities = [item for item in ranked_entities if str((item.get("labels") or ["Entity"])[0]) in supporting_institutional_labels]
    product_entities = [item for item in ranked_entities if str((item.get("labels") or ["Entity"])[0]) in product_labels]
    institutional_limit = max(10, min(24, 8 + (len(actor_entities) // 5)))
    product_limit = max(6, min(16, 4 + (len(actor_entities) // 8)))
    type_limits = {
        "Luxury Brand": 18,
        "Fashion Brand": 16,
        "Executive": 14,
        "Fashion Influencer": 18,
        "Consumer Cohort": 18,
        "Fashion Media Outlet": 16,
        "Market Analyst": 12,
        "Retail Industry Analyst": 10,
        "Geopolitical Commentator": 8,
        "Sustainability Activist": 10,
        "Discount Shopper": 10,
        "Brand Purist": 10,
        "Athlete Ambassador": 10,
        "Institutional Actor": 12,
        "Person": 24,
        "Audience Segment": 18,
        "Media Outlet": 16,
        "Brand": 18,
        "Competitor Brand": 18,
        "Sportswear Competitor": 10,
        "Organization": 24,
        "Creator Group": 14,
        "Internal Team": 12,
        "Campaign": 12,
        "Retail Channel": 12,
        "Region": 10,
        "Product Line": product_limit,
    }
    scenario_type_limits = {
        "market_expansion": {
            "Luxury Brand": 14,
            "Competitor Brand": 12,
            "Luxury Consumer": 8,
            "Market Analyst": 8,
            "Sustainability Activist": 8,
            "Person": 8,
            "Organization": 20,
        },
        "channel_strategy": {
            "Fashion Brand": 9,
            "Discount Shopper": 8,
            "Brand Purist": 8,
            "Retail Industry Analyst": 8,
            "Person": 10,
            "Organization": 10,
        },
        "sports_partnership": {
            "Fashion Brand": 9,
            "Athlete Ambassador": 8,
            "Sportswear Competitor": 8,
            "Fashion Media Outlet": 8,
            "Person": 10,
            "Organization": 10,
        },
        "sustainability_launch": {
            "Fashion Brand": 10,
            "Sustainability Activist": 8,
            "Consumer Cohort": 10,
            "Fashion Media Outlet": 8,
            "Person": 10,
            "Organization": 10,
        },
    }
    if scenario_mode in scenario_type_limits:
        type_limits.update(scenario_type_limits[scenario_mode])
    merged_entities: list[dict[str, Any]] = []
    type_counts: dict[str, int] = {}
    for item in (
        actor_entities
        + institutional_entities[:institutional_limit]
        + product_entities[:product_limit]
    ):
        label = str((item.get("labels") or ["Entity"])[0])
        current = type_counts.get(label, 0)
        limit = type_limits.get(label, 0)
        if limit and current >= limit:
            continue
        type_counts[label] = current + 1
        merged_entities.append(item)
    seen_entity_ids: set[str] = set()
    final_entities: list[dict[str, Any]] = []
    for item in merged_entities:
        entity_uuid = str(item.get("uuid") or "")
        if not entity_uuid or entity_uuid in seen_entity_ids:
            continue
        seen_entity_ids.add(entity_uuid)
        final_entities.append(item)
    final_entities = sorted(
        final_entities,
        key=lambda item: (
            -int(item.get("centrality_score", 0) or 0),
            -len(item.get("related_edges") or []),
            str(item.get("name") or ""),
        ),
    )
    if scenario_mode == "market_expansion":
        global_cap = max(
            34,
            min(
                60,
                len(actor_entities)
                + min(len(institutional_entities), 12)
                + min(len(product_entities), 5),
            ),
        )
    elif scenario_mode in {"channel_strategy", "sports_partnership", "sustainability_launch"}:
        global_cap = max(24, min(44, len(actor_entities) + min(len(institutional_entities), 8)))
    else:
        global_cap = max(
            36,
            min(
                72,
                len(actor_entities)
                + min(len(product_entities), max(6, len(actor_entities) // 4))
                + min(len(institutional_entities), max(8, len(actor_entities) // 3)),
            ),
        )
    final_entities = final_entities[:global_cap]
    return {
        "entities": final_entities,
        "entity_types": sorted({str((item.get("labels") or ["Entity"])[0]) for item in final_entities}),
        "total_count": len(nodes),
        "filtered_count": len(final_entities),
        "recommended_count": len(final_entities),
    }


def graph_search_facts(
    graph_payload: dict[str, Any],
    *,
    query_terms: list[str],
    limit: int = 4,
) -> list[str]:
    """Return a few graph facts that match the requested report focus."""
    lowered_terms = [item.lower() for item in query_terms if item]
    if not lowered_terms:
        return []
    facts: list[str] = []
    for edge in graph_payload.get("edges", []):
        if not isinstance(edge, dict):
            continue
        haystack = " ".join(
            str(edge.get(key) or "")
            for key in ("fact", "relation_type", "source_name", "target_name")
        ).lower()
        if not haystack:
            continue
        if any(term in haystack for term in lowered_terms):
            fact = str(edge.get("fact") or edge.get("relation_type") or "").strip()
            if fact and fact not in facts:
                facts.append(fact)
        if len(facts) >= limit:
            break
    return facts


class GlassRuntimeManager:
    """Background helpers for glass setup, live runs, and report generation."""

    def __init__(self, *, engine, settings: Settings, registry):
        self.engine = engine
        self.settings = settings
        self.registry = registry
        self._lock = Lock()
        self._run_controls: dict[str, Event] = {}
        self._run_processes: dict[str, subprocess.Popen[str]] = {}
        self._prepare_threads: dict[str, Thread] = {}
        self._graph_threads: dict[str, Thread] = {}
        self._report_threads: dict[str, Thread] = {}

    def shutdown(self) -> None:
        """Stop active simulation playback threads."""
        with self._lock:
            controls = list(self._run_controls.values())
            processes = list(self._run_processes.items())
        for control in controls:
            control.set()
        for simulation_id, process in processes:
            self._terminate_process(simulation_id, process)

    def _use_oasis_worker(self) -> bool:
        """Use the real worker in non-test environments."""
        return self.settings.llm_provider != "test"

    def _fail_report(
        self,
        report_id: str,
        *,
        message: str,
        state_path: Path,
        console_log_path: Path,
        agent_log_path: Path,
    ) -> None:
        """Persist a terminal failed report state and update the database."""
        _append_text(console_log_path, message + "\n")
        _append_jsonl(
            agent_log_path,
            {
                "timestamp": utc_now().isoformat(),
                "action": "report_failed",
                "stage": "failed",
                "details": {"message": message},
            },
        )
        _write_json(
            state_path,
            {
                "report_id": report_id,
                "status": "failed",
                "progress": 0,
                "message": message,
                "outline_ready": False,
                "completed_sections": [],
            },
        )
        with Session(self.engine) as session:
            report = session.get(Report, report_id)
            if not report:
                return
            report.status = WorkflowStatus.failed
            report.error_message = message
            report.updated_at = utc_now()
            session.add(report)
            session.commit()

    def _backend_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _terminate_process(self, simulation_id: str, process: subprocess.Popen[str] | None) -> None:
        if process is None:
            return
        if process.poll() is not None:
            with self._lock:
                self._run_processes.pop(simulation_id, None)
            return
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        with self._lock:
            self._run_processes.pop(simulation_id, None)

    def _start_native_oasis_run(
        self,
        simulation_id: str,
        *,
        platform: str,
        max_rounds: int | None,
        enable_graph_memory_update: bool,
        force: bool,
    ) -> None:
        with self._lock:
            current_process = self._run_processes.get(simulation_id)
        if current_process and current_process.poll() is None:
            if not force:
                return
            self._terminate_process(simulation_id, current_process)

        state = load_simulation_state(self.settings, simulation_id)
        graph_id = state.get("graph_id")
        if graph_id:
            reset_graph_from_base(self.settings, graph_id)

        _write_json(simulation_actions_path(self.settings, simulation_id), [])
        _write_json(simulation_posts_path(self.settings, simulation_id, "twitter"), [])
        _write_json(simulation_posts_path(self.settings, simulation_id, "reddit"), [])
        _write_json(simulation_comments_path(self.settings, simulation_id), [])
        _write_json(simulation_interviews_path(self.settings, simulation_id), [])
        save_simulation_env(
            self.settings,
            simulation_id,
            {
                "status": "starting",
                "twitter_available": False,
                "reddit_available": False,
                "closed_at": "",
            },
        )
        state.update(
            {
                "runtime_kind": "oasis-worker",
                "status": "running",
                "runner_status": "starting",
                "platform": platform,
                "enable_graph_memory_update": enable_graph_memory_update,
                "twitter_running": platform in {"twitter", "parallel"},
                "reddit_running": platform in {"reddit", "parallel"},
                "twitter_completed": False,
                "reddit_completed": False,
                "progress_percent": 0,
                "current_round": 0,
                "started_at": utc_now().isoformat(),
                "completed_at": "",
                "error": "",
            }
        )
        save_simulation_state(self.settings, simulation_id, state)

        command = [
            sys.executable,
            "-m",
            "app.oasis_worker",
            "--simulation-id",
            simulation_id,
            "--platform",
            platform,
        ]
        if max_rounds and max_rounds > 0:
            command.extend(["--max-rounds", str(max_rounds)])
        if enable_graph_memory_update:
            command.append("--enable-graph-memory-update")
        if graph_id:
            command.extend(["--graph-id", str(graph_id)])

        worker_env = os.environ.copy()
        worker_env.update(
            {
                "PERSONAGRAPH_DATA_DIR": str(Path(self.settings.data_dir).resolve()),
                "PERSONAGRAPH_LLM_PROVIDER": self.settings.llm_provider,
                "PERSONAGRAPH_LLM_BASE_URL": self.settings.llm_base_url,
                "PERSONAGRAPH_LLM_API_KEY": self.settings.llm_api_key,
                "PERSONAGRAPH_LLM_MODEL": self.settings.llm_model,
                "PERSONAGRAPH_GRAPHITI_BASE_URL": self.settings.graphiti_base_url,
                "PERSONAGRAPH_GRAPHITI_API_KEY": self.settings.graphiti_api_key,
                "PERSONAGRAPH_GRAPHITI_TIMEOUT_SECONDS": str(self.settings.graphiti_timeout_seconds),
            }
        )
        process = subprocess.Popen(
            command,
            cwd=str(self._backend_root()),
            env=worker_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        state["process_pid"] = process.pid
        save_simulation_state(self.settings, simulation_id, state)
        with self._lock:
            self._run_processes[simulation_id] = process

    def start_graph_build(self, graph_job_id: str) -> None:
        """Run a graph build through the real graph service."""
        with self._lock:
            thread = self._graph_threads.get(graph_job_id)
            if thread and thread.is_alive():
                return
            thread = Thread(
                target=self._run_graph_build,
                args=(graph_job_id,),
                name=f"glass-graph-{graph_job_id}",
                daemon=True,
            )
            self._graph_threads[graph_job_id] = thread
            thread.start()

    def graph_build_is_active(self, graph_job_id: str) -> bool:
        """Return whether a graph build thread is still actively running."""
        with self._lock:
            thread = self._graph_threads.get(graph_job_id)
            if thread is None:
                return False
            if thread.is_alive():
                return True
            self._graph_threads.pop(graph_job_id, None)
            return False

    def _project_document_text(self, session: Session, project_id: str) -> str:
        documents = list_source_documents(session, project_id)
        return "\n\n".join(item.extracted_text for item in documents if item.extracted_text).strip()

    def start_prepare(self, simulation_id: str) -> None:
        """Start preparation work if it is not already running."""
        with self._lock:
            thread = self._prepare_threads.get(simulation_id)
            if thread and thread.is_alive():
                return
            thread = Thread(
                target=self._run_prepare,
                args=(simulation_id,),
                name=f"glass-prepare-{simulation_id}",
                daemon=True,
            )
            self._prepare_threads[simulation_id] = thread
            thread.start()

    def start_run(
        self,
        simulation_id: str,
        *,
        platform: str = "parallel",
        max_rounds: int | None = None,
        enable_graph_memory_update: bool = False,
        force: bool = False,
    ) -> None:
        """Start or restart a live simulation playback."""
        if self._use_oasis_worker():
            self._start_native_oasis_run(
                simulation_id,
                platform=platform,
                max_rounds=max_rounds,
                enable_graph_memory_update=enable_graph_memory_update,
                force=force,
            )
            return
        with self._lock:
            current_control = self._run_controls.get(simulation_id)
            if current_control and not force:
                return
            if current_control and force:
                current_control.set()
            control = Event()
            self._run_controls[simulation_id] = control
            thread = Thread(
                target=self._run_simulation,
                args=(simulation_id, control, platform, max_rounds, enable_graph_memory_update),
                name=f"glass-run-{simulation_id}",
                daemon=True,
            )
            thread.start()

    def stop_run(self, simulation_id: str) -> dict[str, Any]:
        """Stop an active simulation playback."""
        if self._use_oasis_worker():
            with self._lock:
                process = self._run_processes.get(simulation_id)
            if process:
                self._terminate_process(simulation_id, process)
            state = load_simulation_state(self.settings, simulation_id)
            state.update(
                {
                    "runner_status": "stopped",
                    "status": "stopped",
                    "twitter_running": False,
                    "reddit_running": False,
                    "stopped_at": utc_now().isoformat(),
                    "completed_at": state.get("completed_at") or utc_now().isoformat(),
                }
            )
            save_simulation_state(self.settings, simulation_id, state)
            save_simulation_env(
                self.settings,
                simulation_id,
                {
                    "status": "closed",
                    "twitter_available": False,
                    "reddit_available": False,
                    "closed_at": utc_now().isoformat(),
                },
            )
            with Session(self.engine) as session:
                simulation = session.get(Simulation, simulation_id)
                if simulation:
                    simulation.status = WorkflowStatus.completed
                    simulation.updated_at = utc_now()
                    session.add(simulation)
                    session.commit()
            return state
        with self._lock:
            control = self._run_controls.get(simulation_id)
        if control:
            control.set()
        state = load_simulation_state(self.settings, simulation_id)
        state.update(
            {
                "runner_status": "stopped",
                "status": "stopped",
                "twitter_running": False,
                "reddit_running": False,
                "stopped_at": utc_now().isoformat(),
            }
        )
        save_simulation_state(self.settings, simulation_id, state)
        save_simulation_env(
            self.settings,
            simulation_id,
            {
                "status": "closed",
                "twitter_available": False,
                "reddit_available": False,
                "closed_at": utc_now().isoformat(),
            },
        )
        with Session(self.engine) as session:
            simulation = session.get(Simulation, simulation_id)
            if simulation:
                simulation.status = WorkflowStatus.completed
                simulation.updated_at = utc_now()
                session.add(simulation)
                session.commit()
        return state

    def start_report(self, report_id: str) -> None:
        """Start report generation if it is not already running."""
        with self._lock:
            thread = self._report_threads.get(report_id)
            if thread and thread.is_alive():
                return
            thread = Thread(
                target=self._run_report_safe,
                args=(report_id,),
                name=f"glass-report-{report_id}",
                daemon=True,
            )
            self._report_threads[report_id] = thread
            thread.start()

    def _run_report_safe(self, report_id: str) -> None:
        """Run report generation with terminal failure persistence."""
        report_root = report_dir(self.settings, report_id)
        state_path = report_root / "state.json"
        agent_log_path = report_root / "agent_log.jsonl"
        console_log_path = report_root / "console_log.txt"
        try:
            self._run_report(report_id)
        except Exception as exc:  # noqa: BLE001
            self._fail_report(
                report_id,
                message=f"Report generation failed: {exc}",
                state_path=state_path,
                console_log_path=console_log_path,
                agent_log_path=agent_log_path,
            )

    def _run_graph_build(self, graph_job_id: str) -> None:
        with Session(self.engine) as session:
            graph_job = session.get(GraphJob, graph_job_id)
            if not graph_job:
                return
            project = session.get(Project, graph_job.project_id)
            if not project:
                graph_job.status = WorkflowStatus.failed
                graph_job.error_message = "Project not found for graph build."
                graph_job.updated_at = utc_now()
                session.add(graph_job)
                session.commit()
                return

            graph_job.status = WorkflowStatus.running
            graph_job.progress_percent = 2
            graph_job.status_message = "Preparing source documents for graph build."
            graph_job.error_message = ""
            graph_job.started_at = utc_now()
            graph_job.updated_at = utc_now()
            session.add(graph_job)
            session.commit()

            metadata = load_project_metadata(self.settings, project.id)
            ontology = metadata.get("ontology") if isinstance(metadata.get("ontology"), dict) else {}
            documents = list_source_documents(session, project.id)
            source_texts = [item.extracted_text for item in documents if item.extracted_text]
            if ontology_is_generic(ontology):
                regenerated_ontology, analysis_summary = build_glass_ontology(
                    self.registry.llm,
                    project_name=project.name,
                    requirement=graph_job.objective or project.scenario_brief,
                    additional_context=project.description,
                    source_texts=source_texts,
                )
                metadata = dict(metadata)
                metadata["ontology"] = regenerated_ontology
                metadata["analysis_summary"] = analysis_summary
                save_project_metadata(self.settings, project.id, metadata)
                ontology = regenerated_ontology

            def progress_callback(progress: float, message: str) -> None:
                graph_job.progress_percent = progress
                graph_job.status_message = message[:500]
                graph_job.updated_at = utc_now()
                session.add(graph_job)
                session.commit()

            try:
                artifacts = self.registry.graph.build_artifacts(
                    llm=self.registry.llm,
                    project=project,
                    documents=documents,
                    objective=graph_job.objective or project.scenario_brief,
                    ontology=ontology if isinstance(ontology, dict) else None,
                    graph_id=graph_job.id,
                    progress_callback=progress_callback,
                )
                graph_job.summary = artifacts.summary
                graph_job.source_digest = artifacts.source_digest
                graph_job.schema_markdown = artifacts.schema_markdown
                graph_job.evidence_markdown = artifacts.evidence_markdown
                payload = artifacts.graph_payload
                used_fallback_payload = False
                if payload is None:
                    used_fallback_payload = True
                    payload = build_glass_graph_snapshot(
                        project=project,
                        source_digest=artifacts.source_digest,
                        ontology=ontology if isinstance(ontology, dict) else {},
                        source_texts=source_texts,
                        node_budget=max(18, min(artifacts.node_count or 24, 28)),
                    )
                ensure_real_graph_payload(payload)
                payload_metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
                result = {
                    "payload": payload,
                    "node_count": (
                        payload_metadata.get("node_count", 0)
                        if used_fallback_payload
                        else artifacts.node_count or payload_metadata.get("node_count", 0)
                    ),
                    "edge_count": (
                        payload_metadata.get("edge_count", 0)
                        if used_fallback_payload
                        else artifacts.edge_count or payload_metadata.get("edge_count", 0)
                    ),
                    "summary": artifacts.summary or "Materialized graph payload.",
                }

                save_graph_base_payload(self.settings, graph_job.id, payload)
                save_graph_payload(self.settings, graph_job.id, payload)
                graph_job.status = WorkflowStatus.completed
                graph_job.progress_percent = 100
                graph_job.status_message = "Graph build completed."
                graph_job.summary = str(result.get("summary") or "")
                graph_job.node_count = int(result.get("node_count") or payload.get("metadata", {}).get("node_count", 0))
                graph_job.edge_count = int(result.get("edge_count") or payload.get("metadata", {}).get("edge_count", 0))
                graph_job.completed_at = utc_now()
                graph_job.updated_at = utc_now()
                project.status = WorkflowStatus.running
                project.updated_at = utc_now()
                session.add(graph_job)
                session.add(project)
                session.commit()
            except SyntheticGraphError as exc:
                persist_graph_job_failure(
                    session,
                    graph_job=graph_job,
                    project=project,
                    message=str(exc),
                )
            except Exception as exc:
                persist_graph_job_failure(
                    session,
                    graph_job=graph_job,
                    project=project,
                    message=f"Graph build failed: {exc}",
                )

    def _run_prepare(self, simulation_id: str) -> None:
        prepare_path = prepare_task_path(self.settings, simulation_id)
        _write_json(
            prepare_path,
            {
                "task_id": f"prep_{simulation_id}",
                "simulation_id": simulation_id,
                "status": "processing",
                "progress": 8,
                "message": "Analyzing graph artifacts for persona preparation.",
                "already_prepared": False,
                "progress_detail": {
                    "current_stage": "loading",
                    "current_stage_name": "Loading graph context",
                    "stage_index": 1,
                    "total_stages": 3,
                    "stage_progress": 25,
                    "current_item": 0,
                    "total_items": 0,
                    "item_description": "Collecting ontology and source context",
                },
            },
        )
        try:
            with Session(self.engine) as session:
                simulation = session.get(Simulation, simulation_id)
                if not simulation:
                    _write_json(
                        prepare_path,
                        {
                            "task_id": f"prep_{simulation_id}",
                            "simulation_id": simulation_id,
                            "status": "failed",
                            "progress": 0,
                            "message": "Simulation not found",
                            "already_prepared": False,
                        },
                    )
                    return
                project = session.get(Project, simulation.project_id)
                graph_job = session.get(GraphJob, simulation.graph_job_id) if simulation.graph_job_id else None
                if not project or not graph_job:
                    _write_json(
                        prepare_path,
                        {
                            "task_id": f"prep_{simulation_id}",
                            "simulation_id": simulation_id,
                            "status": "failed",
                            "progress": 0,
                            "message": "Missing project or graph job for preparation",
                            "already_prepared": False,
                        },
                    )
                    return

                metadata = load_project_metadata(self.settings, project.id)
                ontology = metadata.get("ontology") if isinstance(metadata.get("ontology"), dict) else {}
                graph_payload = ensure_graph_materialized(
                    session,
                    self.settings,
                    project=project,
                    graph_job=graph_job,
                )
                preparation_entities = graph_entities_for_preparation(
                    graph_payload,
                    scenario_text=f"{project.name}\n{project.scenario_brief}\n{project.description}",
                )
                state = load_simulation_state(self.settings, simulation_id)
                state.update(
                    {
                        "status": "preparing",
                        "graph_id": graph_job.id,
                        "profiles_generation_active": True,
                        "config_generation_active": True,
                        "error": "",
                    }
                )
                save_simulation_state(self.settings, simulation_id, state)
                save_simulation_env(
                    self.settings,
                    simulation_id,
                    {
                        "status": "idle",
                        "twitter_available": False,
                        "reddit_available": False,
                        "closed_at": "",
                    },
                )
                _write_json(simulation_posts_path(self.settings, simulation_id, "twitter"), [])
                _write_json(simulation_posts_path(self.settings, simulation_id, "reddit"), [])
                _write_json(simulation_comments_path(self.settings, simulation_id), [])
                time.sleep(0.1)
                llm = self.registry.llm if self.settings.llm_provider != "test" else None

                def profile_progress(current_item: int, total_items: int, item_label: str) -> None:
                    current_total = max(total_items, 1)
                    current_progress = 18 + int((current_item / current_total) * 34)
                    _write_json(
                        prepare_path,
                        {
                            "task_id": f"prep_{simulation_id}",
                            "simulation_id": simulation_id,
                            "status": "processing",
                            "progress": current_progress,
                            "message": f"Generating persona {current_item}/{current_total}: {item_label}",
                            "already_prepared": False,
                            "progress_detail": {
                                "current_stage": "profiles",
                                "current_stage_name": "Generating profiles",
                                "stage_index": 2,
                                "total_stages": 3,
                                "stage_progress": int((current_item / current_total) * 100),
                                "current_item": current_item,
                                "total_items": current_total,
                                "item_description": item_label[:120],
                            },
                        },
                    )

                profiles_payload = build_glass_profiles(
                    project=project,
                    source_digest=graph_job.source_digest,
                    ontology=ontology,
                    expected_count=max(10, int(preparation_entities.get("recommended_count") or preparation_entities["filtered_count"] or graph_job.node_count or 18)),
                    entities=preparation_entities["entities"],
                    llm=llm,
                    progress_callback=profile_progress,
                )
                _write_json(simulation_entities_path(self.settings, simulation_id), preparation_entities)
                _write_json(
                    simulation_profiles_path(self.settings, simulation_id, "reddit"),
                    profiles_payload["reddit_profiles"],
                )
                _write_json(
                    simulation_profiles_path(self.settings, simulation_id, "twitter"),
                    profiles_payload["twitter_profiles"],
                )
                write_oasis_profile_artifacts(
                    self.settings,
                    simulation_id,
                    profiles_payload["reddit_profiles"],
                    profiles_payload["twitter_profiles"],
                )
                state.update(
                    {
                        "expected_entities_count": preparation_entities["filtered_count"] or profiles_payload["expected_count"],
                        "profiles_count": profiles_payload["expected_count"],
                    }
                )
                save_simulation_state(self.settings, simulation_id, state)
                _write_json(
                    prepare_path,
                    {
                        "task_id": f"prep_{simulation_id}",
                        "simulation_id": simulation_id,
                        "status": "processing",
                        "progress": 58,
                        "message": f"Prepared {profiles_payload['expected_count']} personas. Generating simulation config.",
                        "already_prepared": False,
                        "progress_detail": {
                            "current_stage": "profiles",
                            "current_stage_name": "Generating profiles",
                            "stage_index": 2,
                            "total_stages": 3,
                            "stage_progress": 100,
                            "current_item": profiles_payload["expected_count"],
                            "total_items": profiles_payload["expected_count"],
                            "item_description": "Persona generation complete",
                        },
                    },
                )
                time.sleep(0.15)

                config = build_glass_simulation_config(
                    project=project,
                    source_digest=graph_job.source_digest,
                    profiles=profiles_payload["reddit_profiles"],
                    entities=preparation_entities["entities"],
                    llm=llm,
                )
                _write_json(simulation_config_path(self.settings, simulation_id), config)
                _write_json(
                    simulation_preparation_manifest_path(self.settings, simulation_id),
                    {
                        "simulation_id": simulation_id,
                        "project_id": project.id,
                        "graph_id": graph_job.id,
                        "prepared_at": utc_now().isoformat(),
                        "entity_types": preparation_entities["entity_types"],
                        "total_graph_nodes": preparation_entities["total_count"],
                        "filtered_entities_count": preparation_entities["filtered_count"],
                        "profiles_count": profiles_payload["expected_count"],
                        "graph_linked_profiles_count": profiles_payload.get("graph_entity_count", 0),
                        "hot_topics": config.get("event_config", {}).get("hot_topics", []),
                        "scheduled_events_count": len(config.get("event_config", {}).get("scheduled_events", [])),
                        "time_config": config.get("time_config", {}),
                    },
                )
                _write_json(simulation_interviews_path(self.settings, simulation_id), [])
                state.update(
                    {
                        "status": "ready",
                        "profiles_generation_active": False,
                        "config_generation_active": False,
                        "runtime_kind": "oasis-worker" if self._use_oasis_worker() else "synthetic",
                    }
                )
                save_simulation_state(self.settings, simulation_id, state)
                simulation.updated_at = utc_now()
                session.add(simulation)
                session.commit()
                _write_json(
                    prepare_path,
                    {
                        "task_id": f"prep_{simulation_id}",
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "progress": 100,
                        "message": "Profiles and config are ready.",
                        "already_prepared": False,
                        "progress_detail": {
                            "current_stage": "config",
                            "current_stage_name": "Finalizing config",
                            "stage_index": 3,
                            "total_stages": 3,
                            "stage_progress": 100,
                            "current_item": 1,
                            "total_items": 1,
                            "item_description": "Simulation config saved",
                        },
                    },
                )
        except Exception as exc:
            state = load_simulation_state(self.settings, simulation_id)
            state.update(
                {
                    "status": "failed",
                    "profiles_generation_active": False,
                    "config_generation_active": False,
                    "error": str(exc),
                }
            )
            save_simulation_state(self.settings, simulation_id, state)
            _write_json(
                prepare_path,
                {
                    "task_id": f"prep_{simulation_id}",
                    "simulation_id": simulation_id,
                    "status": "failed",
                    "progress": 0,
                    "message": str(exc),
                    "already_prepared": False,
                },
            )

    def _run_simulation(
        self,
        simulation_id: str,
        control: Event,
        platform: str,
        max_rounds: int | None,
        enable_graph_memory_update: bool,
    ) -> None:
        with Session(self.engine) as session:
            simulation = session.get(Simulation, simulation_id)
            if not simulation:
                return
            project = session.get(Project, simulation.project_id)
            if not project:
                return

            state = load_simulation_state(self.settings, simulation_id)
            graph_id = state.get("graph_id")
            if not graph_id and simulation.graph_job_id:
                graph_id = simulation.graph_job_id
                state["graph_id"] = graph_id
            if graph_id:
                reset_graph_from_base(self.settings, graph_id)

            config = load_simulation_config(self.settings, simulation_id)
            profiles = load_simulation_profiles(self.settings, simulation_id, "reddit")
            active_platforms = {"twitter", "reddit"} if platform == "parallel" else {platform}
            derived_total_rounds = int(
                (
                    config.get("time_config", {}).get("total_simulation_hours", 12) * 60
                )
                / max(config.get("time_config", {}).get("minutes_per_round", 10), 1)
            )
            minutes_per_round = int(config.get("time_config", {}).get("minutes_per_round", 10) or 10)
            total_simulation_hours = int(config.get("time_config", {}).get("total_simulation_hours", 12) or 12)
            total_rounds = max_rounds or derived_total_rounds
            action_plan = build_glass_action_plan(
                project=project,
                profiles=profiles,
                config=config,
                total_rounds=total_rounds,
            )
            if platform != "parallel":
                action_plan = [
                    item
                    for item in action_plan
                    if str(item.get("platform") or "").lower() == platform
                ]
            _write_json(simulation_plan_path(self.settings, simulation_id), action_plan)
            _write_json(simulation_actions_path(self.settings, simulation_id), [])
            _write_json(simulation_posts_path(self.settings, simulation_id, "twitter"), [])
            _write_json(simulation_posts_path(self.settings, simulation_id, "reddit"), [])
            _write_json(simulation_comments_path(self.settings, simulation_id), [])
            _write_json(simulation_interviews_path(self.settings, simulation_id), [])
            save_simulation_env(
                self.settings,
                simulation_id,
                {
                    "status": "alive",
                    "twitter_available": "twitter" in active_platforms,
                    "reddit_available": "reddit" in active_platforms,
                    "closed_at": "",
                },
            )

            state.update(
                {
                    "status": "running",
                    "runner_status": "starting",
                    "current_round": 0,
                    "total_rounds": total_rounds,
                    "progress_percent": 0,
                    "platform": platform,
                    "enable_graph_memory_update": enable_graph_memory_update,
                    "minutes_per_round": minutes_per_round,
                    "total_simulation_hours": total_simulation_hours,
                    "simulated_hours": 0,
                    "twitter_current_round": 0,
                    "reddit_current_round": 0,
                    "twitter_simulated_hours": 0,
                    "reddit_simulated_hours": 0,
                    "twitter_completed": False,
                    "reddit_completed": False,
                    "twitter_running": "twitter" in active_platforms,
                    "reddit_running": "reddit" in active_platforms,
                    "twitter_actions_count": 0,
                    "reddit_actions_count": 0,
                    "total_actions_count": 0,
                    "error": "",
                    "started_at": utc_now().isoformat(),
                    "process_pid": os.getpid(),
                }
            )
            save_simulation_state(self.settings, simulation_id, state)
            simulation.status = WorkflowStatus.running
            simulation.progress_percent = 0
            simulation.updated_at = utc_now()
            session.add(simulation)
            session.commit()

        time.sleep(0.1)
        all_actions: list[dict[str, Any]] = []
        posts_by_platform: dict[str, list[dict[str, Any]]] = {"twitter": [], "reddit": []}
        comments: list[dict[str, Any]] = []
        grouped_by_round: dict[int, list[dict[str, Any]]] = {}
        for action in _read_json(simulation_plan_path(self.settings, simulation_id), []):
            grouped_by_round.setdefault(int(action["round_num"]), []).append(action)

        for round_number in range(1, total_rounds + 1):
            if control.is_set():
                break
            round_actions = grouped_by_round.get(round_number, [])
            timestamp_base = utc_now()
            for offset, action in enumerate(round_actions):
                action["timestamp"] = (timestamp_base + timedelta(seconds=offset)).isoformat()
                platform = str(action.get("platform") or "reddit")
                action_type = str(action.get("action_type") or "").upper()
                if action_type == "CREATE_POST":
                    post = {
                        "post_id": f"{platform}_post_{round_number:03d}_{offset + 1:02d}",
                        "platform": platform,
                        "agent_id": str(action.get("agent_id") or ""),
                        "agent_name": str(action.get("agent_name") or "Agent"),
                        "title": str(action.get("topic") or "Scenario update"),
                        "content": str(action.get("content") or ""),
                        "score": round_number + offset + 1,
                        "created_at": str(action.get("timestamp") or timestamp_base.isoformat()),
                    }
                    posts_by_platform.setdefault(platform, []).append(post)
                    action["post_id"] = post["post_id"]
                elif action_type == "COMMENT":
                    available_posts = posts_by_platform.get(platform) or []
                    if available_posts:
                        parent = available_posts[-1]
                        comment = {
                            "comment_id": f"{platform}_comment_{round_number:03d}_{offset + 1:02d}",
                            "platform": platform,
                            "post_id": parent["post_id"],
                            "agent_id": str(action.get("agent_id") or ""),
                            "agent_name": str(action.get("agent_name") or "Agent"),
                            "content": str(action.get("content") or ""),
                            "score": max(1, round_number - offset),
                            "created_at": str(action.get("timestamp") or timestamp_base.isoformat()),
                        }
                        comments.append(comment)
                        action["post_id"] = parent["post_id"]
            all_actions.extend(round_actions)
            _write_json(simulation_actions_path(self.settings, simulation_id), all_actions)
            _write_json(
                simulation_posts_path(self.settings, simulation_id, "twitter"),
                posts_by_platform.get("twitter", []),
            )
            _write_json(
                simulation_posts_path(self.settings, simulation_id, "reddit"),
                posts_by_platform.get("reddit", []),
            )
            _write_json(simulation_comments_path(self.settings, simulation_id), comments)

            state = load_simulation_state(self.settings, simulation_id)
            twitter_actions = len([item for item in all_actions if item["platform"] == "twitter"])
            reddit_actions = len([item for item in all_actions if item["platform"] == "reddit"])
            simulated_hours = round((round_number * minutes_per_round) / 60, 2)
            state.update(
                {
                    "runner_status": "running",
                    "current_round": round_number,
                    "progress_percent": round((round_number / total_rounds) * 100, 2),
                    "simulated_hours": simulated_hours,
                    "twitter_current_round": round_number if "twitter" in active_platforms else 0,
                    "reddit_current_round": round_number if "reddit" in active_platforms else 0,
                    "twitter_simulated_hours": simulated_hours if "twitter" in active_platforms else 0,
                    "reddit_simulated_hours": simulated_hours if "reddit" in active_platforms else 0,
                    "twitter_actions_count": twitter_actions,
                    "reddit_actions_count": reddit_actions,
                    "total_actions_count": len(all_actions),
                }
            )
            save_simulation_state(self.settings, simulation_id, state)
            self._extend_graph(state.get("graph_id"), round_number, round_actions)
            time.sleep(0.2)

        final_state = load_simulation_state(self.settings, simulation_id)
        stopped = control.is_set()
        final_state.update(
            {
                "runner_status": "stopped" if stopped else "completed",
                "status": "stopped" if stopped else "completed",
                "twitter_running": False,
                "reddit_running": False,
                "twitter_completed": not stopped and "twitter" in active_platforms,
                "reddit_completed": not stopped and "reddit" in active_platforms,
                "progress_percent": final_state.get("progress_percent", 100 if not stopped else 0),
                "completed_at": utc_now().isoformat(),
            }
        )
        if not stopped:
            final_state["progress_percent"] = 100
        save_simulation_state(self.settings, simulation_id, final_state)
        save_simulation_env(
            self.settings,
            simulation_id,
            {
                "status": "alive" if not stopped else "closed",
                "twitter_available": not stopped and "twitter" in active_platforms,
                "reddit_available": not stopped and "reddit" in active_platforms,
                "closed_at": "" if not stopped else utc_now().isoformat(),
            },
        )

        with Session(self.engine) as session:
            simulation = session.get(Simulation, simulation_id)
            project = session.get(Project, simulation.project_id) if simulation else None
            if simulation:
                simulation.status = WorkflowStatus.completed
                simulation.progress_percent = float(final_state.get("progress_percent", 100))
                simulation.rounds = int(final_state.get("total_rounds", 0))
                simulation.event_count = len(all_actions)
                simulation.summary = (
                    f"Completed a {simulation.rounds}-round live playback with {len(all_actions)} visible actions."
                )
                simulation.timeline_markdown = "\n".join(
                    [
                        "## Simulation timeline",
                        "",
                        *[
                            runtime_action_line(item, verb="posted about")
                            for item in all_actions[:12]
                        ],
                    ]
                )
                simulation.event_log_json = json.dumps(all_actions)
                simulation.completed_at = utc_now()
                simulation.updated_at = utc_now()
                session.add(simulation)
            if project and not stopped:
                project.status = WorkflowStatus.running
                project.updated_at = utc_now()
                session.add(project)
            session.commit()

        with self._lock:
            self._run_controls.pop(simulation_id, None)

    def _extend_graph(self, graph_id: str | None, round_number: int, round_actions: list[dict[str, Any]]) -> None:
        if not graph_id:
            return
        graph_payload = load_graph_payload(self.settings, graph_id)
        if not round_actions:
            return
        lead_action = round_actions[0]
        topic = str(lead_action.get("topic", "Signal"))
        platform = str(lead_action.get("platform", "twitter")).title()
        signal_id = f"signal_round_{round_number:03d}"
        nodes = graph_payload.setdefault("nodes", [])
        edges = graph_payload.setdefault("edges", [])
        nodes.append(
            {
                "uuid": signal_id,
                "name": f"{topic} Round {round_number}",
                "label": "Signal",
                "summary": lead_action.get("content"),
            }
        )
        topic_id = f"topic_{topic.strip().lower().replace(' ', '-')}"
        platform_id = f"platform_{platform.lower()}"
        edges.append(
            {
                "uuid": f"edge_{signal_id}_{topic_id}",
                "source_uuid": signal_id,
                "target_uuid": topic_id,
                "relation_type": "reacts_to",
                "fact": f"Round {round_number} action connected {topic} to live discussion.",
            }
        )
        edges.append(
            {
                "uuid": f"edge_{signal_id}_{platform_id}",
                "source_uuid": signal_id,
                "target_uuid": platform_id,
                "relation_type": "emerges_on",
                "fact": f"Round {round_number} signal emerged on {platform}.",
            }
        )
        graph_payload["metadata"] = {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "entity_types": sorted({str(item.get("label", "Entity")) for item in nodes}),
            "edge_types": sorted({str(item.get("relation_type", "related_to")) for item in edges}),
        }
        save_graph_payload(self.settings, graph_id, graph_payload)

    def _run_report(self, report_id: str) -> None:
        report_root = report_dir(self.settings, report_id)
        state_path = report_root / "state.json"
        agent_log_path = report_root / "agent_log.jsonl"
        console_log_path = report_root / "console_log.txt"
        sections_root = report_root / "sections"
        sections_root.mkdir(parents=True, exist_ok=True)
        _write_text(console_log_path, "")
        _write_text(agent_log_path, "")
        _write_json(
            state_path,
            {
                "report_id": report_id,
                "status": "generating",
                "progress": 6,
                "message": "Planning report outline.",
                "outline_ready": False,
                "completed_sections": [],
            },
        )

        with Session(self.engine) as session:
            report = session.get(Report, report_id)
            if not report:
                return
            simulation = session.get(Simulation, report.simulation_id)
            project = session.get(Project, simulation.project_id) if simulation else None
            if not simulation or not project:
                _write_json(
                    state_path,
                    {
                        "report_id": report_id,
                        "status": "failed",
                        "progress": 0,
                        "message": "Missing simulation or project for report generation.",
                    },
                )
                return

            report.status = WorkflowStatus.running
            report.progress_percent = 5
            report.updated_at = utc_now()
            session.add(report)
            session.commit()

            _append_jsonl(
                agent_log_path,
                {
                    "timestamp": utc_now().isoformat(),
                    "action": "report_start",
                    "stage": "pending",
                    "details": {
                        "simulation_id": simulation.id,
                        "project_id": project.id,
                        "message": "Report generation task started.",
                    },
                },
            )
            _append_jsonl(
                agent_log_path,
                {
                    "timestamp": utc_now().isoformat(),
                    "action": "planning_start",
                    "stage": "planning",
                    "details": {"message": "Starting report outline planning."},
                },
            )

            config = load_simulation_config(self.settings, simulation.id)
            actions = load_simulation_actions(self.settings, simulation.id)
            profiles = load_simulation_profiles(self.settings, simulation.id, "reddit")
            posts_by_platform = {
                "twitter": load_simulation_posts(self.settings, simulation.id, "twitter"),
                "reddit": load_simulation_posts(self.settings, simulation.id, "reddit"),
            }
            comments = load_simulation_comments(self.settings, simulation.id)
            state = load_simulation_state(self.settings, simulation.id)
            graph_id = str(state.get("graph_id") or "")
            graph_payload = load_graph_payload(self.settings, graph_id) if graph_id else {"nodes": [], "edges": [], "metadata": {}}
            graph_metadata = graph_payload.get("metadata", {}) if isinstance(graph_payload, dict) else {}
            search_terms = top_terms(
                " ".join(
                    [
                        str(report.focus or ""),
                        str(project.scenario_brief or ""),
                        " ".join(
                            str(item)
                            for item in config.get("event_config", {}).get("hot_topics", [])
                            if isinstance(item, str)
                        ),
                    ]
                ),
                limit=4,
            )
            graph_facts = graph_search_facts(graph_payload, query_terms=search_terms, limit=4)
            agent_activity_counts: dict[str, int] = {}
            for item in actions:
                agent_id = str(item.get("agent_id") or "")
                if not agent_id:
                    continue
                agent_activity_counts[agent_id] = agent_activity_counts.get(agent_id, 0) + 1
            selected_profiles = sorted(
                profiles,
                key=lambda item: (
                    -agent_activity_counts.get(str(item.get("agent_id") or ""), 0),
                    str(item.get("name") or ""),
                ),
            )[:4]
            interviews: list[dict[str, str]] = []

            _append_text(
                console_log_path,
                f"Collected graph statistics: {graph_metadata.get('node_count', 0)} nodes, {graph_metadata.get('edge_count', 0)} edges\n",
            )
            _append_jsonl(
                agent_log_path,
                {
                    "timestamp": utc_now().isoformat(),
                    "action": "tool_call",
                    "stage": "planning",
                    "details": {
                        "message": "Collected graph statistics and runtime platform evidence.",
                        "tool_name": "graph_statistics",
                        "graph_metadata": graph_metadata,
                        "twitter_posts": len(posts_by_platform["twitter"]),
                        "reddit_posts": len(posts_by_platform["reddit"]),
                        "comments": len(comments),
                    },
                },
            )
            if graph_facts:
                _append_text(
                    console_log_path,
                    f"Panorama search matched {len(graph_facts)} graph facts for: {', '.join(search_terms)}\n",
                )
                _append_jsonl(
                    agent_log_path,
                    {
                        "timestamp": utc_now().isoformat(),
                        "action": "tool_call",
                        "stage": "planning",
                        "details": {
                            "message": "Queried graph facts for the planned report focus.",
                            "tool_name": "panorama_search",
                            "parameters": {"graph_id": graph_id, "query_terms": search_terms},
                            "results_preview": graph_facts,
                        },
                    },
                )

            env = load_simulation_env(self.settings, simulation.id)
            interview_prompt = report.focus or "What matters most in this scenario now?"
            used_runtime_interviews = False
            if env.get("status") == "alive" and state.get("runtime_kind") == "oasis-worker" and selected_profiles:
                message = f"Interviewing {len(selected_profiles)} personas through the live OASIS environment."
                _append_text(console_log_path, message + "\n")
                _append_jsonl(
                    agent_log_path,
                    {
                        "timestamp": utc_now().isoformat(),
                        "action": "tool_call",
                        "section_index": 4,
                        "details": {
                            "message": message,
                            "tool_name": "interview_agents",
                            "parameters": {
                                "agent_ids": [item["agent_id"] for item in selected_profiles],
                                "prompt": interview_prompt,
                            },
                        },
                    },
                )
                try:
                    ipc_response = send_ipc_command(
                        self.settings,
                        simulation.id,
                        command_type="batch_interview",
                        args={
                            "platform": "twitter",
                            "interviews": [
                                {
                                    "agent_id": int(profile.get("oasis_user_id", profile.get("user_id", 0))),
                                    "prompt": interview_prompt,
                                    "platform": "twitter",
                                }
                                for profile in selected_profiles
                            ],
                        },
                        timeout_seconds=20.0,
                    )
                    if str(ipc_response.get("status") or "") == "completed":
                        raw_results = ((ipc_response.get("result") or {}).get("interview_results") or [])
                        for item in raw_results:
                            if not isinstance(item, dict) or not str(item.get("response") or "").strip():
                                continue
                            interviews.append(
                                {
                                    "agent_id": str(item.get("agent_id") or ""),
                                    "agent_name": str(item.get("agent_name") or item.get("agent_id") or "Persona"),
                                    "response": str(item.get("response") or "").strip(),
                                }
                            )
                        used_runtime_interviews = bool(interviews)
                except TimeoutError:
                    _append_text(console_log_path, "Live interview batch timed out. Falling back to local synthesis.\n")

            if not used_runtime_interviews:
                for index, profile in enumerate(selected_profiles, start=1):
                    message = f"Interviewing {profile['name']} for section evidence."
                    _append_text(console_log_path, message + "\n")
                    _append_jsonl(
                        agent_log_path,
                        {
                            "timestamp": utc_now().isoformat(),
                            "action": "tool_call",
                            "section_index": 4,
                            "details": {
                                "message": message,
                                "tool_name": "interview_agents",
                                "parameters": {"agent_id": profile["agent_id"], "prompt": interview_prompt},
                            },
                        },
                    )
                    response = build_glass_interview_response(
                        None,
                        project=project,
                        profile=profile,
                        prompt=interview_prompt,
                        recent_actions=[item for item in actions if item.get("agent_id") == profile["agent_id"]][:4],
                    )
                    interviews.append(
                        {
                            "agent_id": str(profile["agent_id"]),
                            "agent_name": str(profile["name"]),
                            "response": response,
                        }
                    )
                    _write_json(
                        state_path,
                        {
                            "report_id": report_id,
                            "status": "generating",
                            "progress": 12 + index * 8,
                            "message": f"Collected interview evidence from {index}/{len(selected_profiles)} personas.",
                        },
                    )
                    time.sleep(0.05)

            package = build_glass_report_package(
                project=project,
                focus=report.focus,
                config=config,
                actions=actions,
                interviews=interviews,
                posts_by_platform=posts_by_platform,
                comments=comments,
                graph_metadata=graph_metadata,
                graph_nodes=graph_payload.get("nodes", []) if isinstance(graph_payload, dict) else [],
                graph_facts=graph_facts,
                llm=None,
            )
            _write_json(
                report_evidence_path(self.settings, report_id),
                package.get("evidence_summary", {}),
            )
            outline = {
                "title": package["title"],
                "summary": package["summary"],
                "sections": [
                    {
                        "index": item["index"],
                        "title": item["title"],
                    }
                    for item in package["sections"]
                ],
            }
            _append_jsonl(
                agent_log_path,
                {
                    "timestamp": utc_now().isoformat(),
                    "action": "planning_complete",
                    "stage": "planning",
                    "details": {
                        "message": "Outline planning complete.",
                        "outline": outline,
                    },
                },
            )
            _write_json(
                state_path,
                {
                    "report_id": report_id,
                    "status": "generating",
                    "progress": 28,
                    "message": "Outline ready. Drafting sections.",
                    "title": package["title"],
                    "summary": package["summary"],
                    "outline": outline,
                    "evidence_summary": package.get("evidence_summary", {}),
                    "outline_ready": True,
                    "current_section": 1,
                    "completed_sections": [],
                },
            )

            total_sections = len(package["sections"])
            for offset, section in enumerate(package["sections"], start=1):
                section_path = sections_root / f"{offset:02d}_{section['title'].lower().replace(' ', '-')}.md"
                _append_jsonl(
                    agent_log_path,
                    {
                        "timestamp": utc_now().isoformat(),
                        "action": "section_start",
                        "stage": "generating",
                        "section_index": offset,
                        "section_title": section["title"],
                        "details": {"message": f"Starting section generation: {section['title']}"},
                    },
                )
                _write_text(section_path, section["content"] + "\n")
                line = f"Generated section {offset}/{total_sections}: {section['title']}"
                _append_text(console_log_path, line + "\n")
                _append_jsonl(
                    agent_log_path,
                    {
                        "timestamp": utc_now().isoformat(),
                        "action": "section_content",
                        "section_index": offset,
                        "section_title": section["title"],
                        "details": {
                            "message": line,
                            "content": section["content"],
                            "content_length": len(section["content"]),
                        },
                    },
                )
                completed_sections = list(range(1, offset + 1))
                _append_jsonl(
                    agent_log_path,
                    {
                        "timestamp": utc_now().isoformat(),
                        "action": "section_complete",
                        "stage": "generating",
                        "section_index": offset,
                        "section_title": section["title"],
                        "details": {"message": f"Completed section: {section['title']}"},
                    },
                )
                _write_json(
                    state_path,
                    {
                        "report_id": report_id,
                        "status": "generating",
                        "progress": 35 + int((offset / total_sections) * 55),
                        "message": f"Drafting section {offset}/{total_sections}: {section['title']}",
                        "title": package["title"],
                        "summary": package["summary"],
                        "outline": outline,
                        "evidence_summary": package.get("evidence_summary", {}),
                        "outline_ready": True,
                        "current_section": min(offset + 1, total_sections),
                        "completed_sections": completed_sections,
                    },
                )
                time.sleep(0.05)

            markdown_body = package["markdown_body"] + "\n"
            _write_text(report_root / "report.md", markdown_body)
            _write_text(report_root / "full_report.md", markdown_body)
            _append_jsonl(
                agent_log_path,
                {
                    "timestamp": utc_now().isoformat(),
                    "action": "report_complete",
                    "stage": "completed",
                    "details": {"message": "Report generation complete."},
                },
            )
            _write_json(
                state_path,
                {
                    "report_id": report_id,
                    "status": "completed",
                    "progress": 100,
                    "message": "Report completed.",
                    "title": package["title"],
                    "summary": package["summary"],
                    "outline": outline,
                    "evidence_summary": package.get("evidence_summary", {}),
                    "outline_ready": True,
                    "current_section": total_sections,
                    "completed_sections": list(range(1, total_sections + 1)),
                    "sections": [
                        {
                            "section_index": item["index"],
                            "title": item["title"],
                            "filename": f"{item['index']:02d}_{item['title'].lower().replace(' ', '-')}.md",
                        }
                        for item in package["sections"]
                    ],
                },
            )

            report.status = WorkflowStatus.completed
            report.progress_percent = 100
            report.summary = str(package["summary"])
            report.executive_summary = str(package["executive_summary"])
            report.markdown_body = str(package["markdown_body"])
            report.completed_at = utc_now()
            report.updated_at = utc_now()
            session.add(report)
            project.status = WorkflowStatus.completed
            project.updated_at = utc_now()
            session.add(project)
            session.commit()


def create_glass_project(
    session: Session,
    settings: Settings,
    registry,
    *,
    name: str,
    requirement: str,
    additional_context: str,
    files: list[tuple[str, str, bytes]],
) -> tuple[Project, dict[str, Any], str, int]:
    """Create a project and persist the ontology metadata for the glass flow."""
    project = Project(
        id=f"proj_{uuid4().hex[:12]}",
        name=name,
        description=requirement,
        scenario_brief="\n\n".join(part for part in [requirement, additional_context] if part.strip()),
        status=WorkflowStatus.draft,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    documents: list[SourceDocument] = []
    for filename, content_type, raw_bytes in files:
        from .runtime import create_source_document

        document = create_source_document(
            session,
            settings,
            project.id,
            filename,
            content_type,
            raw_bytes,
        )
        documents.append(document)

    source_texts = [item.extracted_text for item in documents if item.extracted_text]
    inferred_name = infer_project_name(
        project.name,
        requirement=requirement,
        additional_context=additional_context,
        source_texts=source_texts,
    )
    if inferred_name and inferred_name != project.name:
        project.name = inferred_name
        project.updated_at = utc_now()
        session.add(project)
        session.commit()
        session.refresh(project)
    ontology, analysis_summary = build_glass_ontology(
        registry.llm,
        project_name=project.name,
        requirement=requirement,
        additional_context=additional_context,
        source_texts=source_texts,
    )
    total_text_length = sum(len(text) for text in source_texts)
    save_project_metadata(
        settings,
        project.id,
        {
            "ontology": ontology,
            "analysis_summary": analysis_summary,
            "total_text_length": total_text_length,
        },
    )
    return project, ontology, analysis_summary, total_text_length
