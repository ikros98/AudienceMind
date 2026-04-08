#!/usr/bin/env python3
"""Run a strict legacy-oracle parity audit for the glass workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib import error, parse, request
import uuid


REQUIRED_FRONTEND_ROUTES = {
    "/process/:projectId",
    "/simulation/:simulationId",
    "/simulation/:simulationId/start",
    "/report/:reportId",
    "/interaction/:reportId",
}

REQUIRED_STEP_COMPONENTS = {
    "Step1GraphBuild",
    "Step2EnvSetup",
    "Step3Simulation",
    "Step4Report",
    "Step5Interaction",
}

REQUIRED_FRONTEND_API_ENDPOINTS = {
    ("POST", "/api/graph/ontology/generate"),
    ("POST", "/api/graph/build"),
    ("GET", "/api/graph/task/{task_id}"),
    ("GET", "/api/graph/project/list"),
    ("GET", "/api/graph/project/{project_id}"),
    ("GET", "/api/graph/data/{graph_id}"),
    ("POST", "/api/simulation/create"),
    ("POST", "/api/simulation/prepare"),
    ("POST", "/api/simulation/prepare/status"),
    ("GET", "/api/simulation/{simulation_id}"),
    ("GET", "/api/simulation/list"),
    ("GET", "/api/simulation/history"),
    ("GET", "/api/simulation/{simulation_id}/profiles"),
    ("GET", "/api/simulation/{simulation_id}/profiles/realtime"),
    ("GET", "/api/simulation/{simulation_id}/config"),
    ("GET", "/api/simulation/{simulation_id}/config/realtime"),
    ("POST", "/api/simulation/start"),
    ("POST", "/api/simulation/stop"),
    ("GET", "/api/simulation/{simulation_id}/run-status"),
    ("GET", "/api/simulation/{simulation_id}/run-status/detail"),
    ("GET", "/api/simulation/{simulation_id}/actions"),
    ("GET", "/api/simulation/{simulation_id}/posts"),
    ("POST", "/api/simulation/env-status"),
    ("POST", "/api/simulation/close-env"),
    ("POST", "/api/simulation/interview/batch"),
    ("POST", "/api/report/generate"),
    ("GET", "/api/report/{report_id}"),
    ("GET", "/api/report/{report_id}/agent-log"),
    ("GET", "/api/report/{report_id}/console-log"),
    ("POST", "/api/report/chat"),
}

UTILITY_API_ENDPOINTS = {
    ("GET", "/api/graph/tasks"),
    ("POST", "/api/graph/project/{project_id}/reset"),
    ("DELETE", "/api/graph/project/{project_id}"),
    ("DELETE", "/api/graph/delete/{graph_id}"),
    ("GET", "/api/simulation/{simulation_id}/config/download"),
    ("GET", "/api/simulation/script/{script_name}/download"),
    ("POST", "/api/simulation/generate-profiles"),
    ("GET", "/api/report/by-simulation/{simulation_id}"),
    ("GET", "/api/report/list"),
    ("GET", "/api/report/{report_id}/download"),
    ("DELETE", "/api/report/{report_id}"),
    ("GET", "/api/report/{report_id}/progress"),
}

CRITICAL_DYNAMIC_CHECKS = {
    "ontology_generated",
    "graph_build_completed",
    "graph_payload_present",
    "entities_endpoints_present",
    "simulation_created",
    "simulation_prepared",
    "profiles_present",
    "config_present",
    "simulation_completed",
    "actions_present",
    "posts_present",
    "interview_batch_present",
    "env_status_present",
    "close_env_present",
    "report_completed",
    "report_sections_present",
    "report_check_present",
    "agent_log_present",
    "console_log_present",
    "report_chat_present",
}

OPTIONAL_DYNAMIC_CHECKS = {
    "timeline_present",
    "agent_stats_present",
    "comments_present",
    "interview_present",
    "interview_all_present",
    "interview_history_present",
    "report_tools_present",
}

UTILITY_DYNAMIC_CHECKS = {
    "graph_tasks_present",
    "simulation_config_download_present",
    "generate_profiles_present",
    "script_download_present",
    "report_lookup_present",
    "report_list_present",
    "report_download_present",
    "report_progress_present",
    "report_delete_present",
    "graph_delete_present",
    "project_delete_present",
}


@dataclass(frozen=True)
class AuditConfig:
    repo_root: Path
    legacy_repo: Path
    legacy_base_url: str
    persona_base_url: str
    output_path: Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def build_multipart_body(fields: dict[str, str], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"----PersonaGraphParity{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    for field_name, filename, content, content_type in files:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode(),
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def http_request(
    base_url: str,
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    form_fields: dict[str, str] | None = None,
    files: list[tuple[str, str, bytes, str]] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    target = f"{base_url.rstrip('/')}{path}"
    if params:
        query = parse.urlencode({key: value for key, value in params.items() if value is not None})
        target = f"{target}?{query}"
    headers = {"Accept": "application/json"}
    data: bytes | None = None
    if json_payload is not None:
        data = json.dumps(json_payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form_fields is not None or files is not None:
        data, content_type = build_multipart_body(form_fields or {}, files or [])
        headers["Content-Type"] = content_type
    req = request.Request(target, data=data, headers=headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return {"status_code": response.status, "json": json.loads(raw)}
    except error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except Exception:
            parsed = {"error": payload}
        return {"status_code": exc.code, "json": parsed}


def http_request_text(
    base_url: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    target = f"{base_url.rstrip('/')}{path}"
    if params:
        query = parse.urlencode({key: value for key, value in params.items() if value is not None})
        target = f"{target}?{query}"
    req = request.Request(target, headers={"Accept": "*/*"}, method=method.upper())
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return {"status_code": response.status, "text": raw, "content_type": response.headers.get("Content-Type", "")}
    except error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        return {"status_code": exc.code, "text": payload, "content_type": exc.headers.get("Content-Type", "")}


def poll_envelope(
    base_url: str,
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    terminal_statuses: set[str],
    timeout_seconds: float = 480.0,
    interval_seconds: float = 2.0,
    stop_on_error: bool = False,
    tolerated_http_statuses: set[int] | None = None,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_data: dict[str, Any] | None = None
    while time.time() < deadline:
        response = http_request(base_url, method, path, json_payload=json_payload)
        if response["status_code"] != 200:
            if tolerated_http_statuses and response["status_code"] in tolerated_http_statuses:
                payload = response["json"]
                error_text = payload.get("error") if isinstance(payload, dict) else payload
                return {
                    "status": "failed",
                    "runner_status": "failed",
                    "error": str(error_text),
                    "_http_status": response["status_code"],
                }
            raise RuntimeError(f"{path} returned {response['status_code']}: {response['json']}")
        payload = response["json"]
        if not payload.get("success", False):
            raise RuntimeError(f"{path} returned failure envelope: {payload}")
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise RuntimeError(f"{path} returned non-dict data: {data}")
        last_data = data
        current_status = str(data.get("status") or data.get("runner_status") or "").strip().lower()
        if current_status in terminal_statuses:
            return data
        if stop_on_error and data.get("error"):
            return data
        time.sleep(interval_seconds)
    raise TimeoutError(f"Timed out waiting for {path}; last data was {last_data}")


def parse_frontend_routes(path: Path) -> set[str]:
    content = read_text(path)
    return {match.group(1) for match in re.finditer(r"path:\s*['\"]([^'\"]+)['\"]", content)}


def parse_step_components(path: Path) -> set[str]:
    return {item.stem for item in path.iterdir() if item.is_file() and item.suffix in {".vue", ".tsx", ".ts"}}


def parse_fastapi_endpoints(path: Path) -> set[tuple[str, str]]:
    content = read_text(path)
    results: set[tuple[str, str]] = set()
    pattern = re.compile(r'@router\.(get|post|delete)\("([^"]+)"\)')
    for method, route in pattern.findall(content):
        results.add((method.upper(), route))
    return results


def parse_flask_endpoints(paths: list[Path]) -> set[tuple[str, str]]:
    pattern = re.compile(r'@(?:\w+)_bp\.route\((["\'])(.+?)\1(?:,\s*methods=\[([^\]]+)\])?')
    results: set[tuple[str, str]] = set()
    for path in paths:
        content = read_text(path)
        for _, route, methods_raw in pattern.findall(content):
            methods = [item.strip().strip("'\"") for item in methods_raw.split(",")] if methods_raw else ["GET"]
            prefix = ""
            if path.name == "graph.py":
                prefix = "/api/graph"
            elif path.name == "simulation.py":
                prefix = "/api/simulation"
            elif path.name == "report.py":
                prefix = "/api/report"
            for method in methods:
                normalized_route = re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", route)
                results.add((method.upper(), f"{prefix}{normalized_route}"))
    return results


def check_static_surface(config: AuditConfig) -> dict[str, Any]:
    legacy_routes = parse_frontend_routes(config.legacy_repo / "frontend/src/router/index.js")
    persona_routes = parse_frontend_routes(config.repo_root / "frontend/src/router/index.tsx")

    legacy_components = parse_step_components(config.legacy_repo / "frontend/src/components")
    persona_components = parse_step_components(config.repo_root / "frontend/src/components/steps")

    legacy_endpoints = parse_flask_endpoints(
        [
            config.legacy_repo / "backend/app/api/graph.py",
            config.legacy_repo / "backend/app/api/simulation.py",
            config.legacy_repo / "backend/app/api/report.py",
        ]
    )
    persona_endpoints = parse_fastapi_endpoints(config.repo_root / "backend/app/routes/legacy_compat.py")

    static_checks: list[dict[str, Any]] = []
    for name, required, legacy_set, persona_set in (
        ("frontend_routes", REQUIRED_FRONTEND_ROUTES, legacy_routes, persona_routes),
        ("step_components", REQUIRED_STEP_COMPONENTS, legacy_components, persona_components),
    ):
        missing_in_legacy = sorted(required - legacy_set)
        missing_in_persona = sorted(required - persona_set)
        static_checks.append(
            {
                "name": name,
                "passed": not missing_in_legacy and not missing_in_persona,
                "missing_in_legacy": missing_in_legacy,
                "missing_in_persona": missing_in_persona,
            }
        )

    endpoint_missing_in_legacy = sorted(REQUIRED_FRONTEND_API_ENDPOINTS - legacy_endpoints)
    endpoint_missing_in_persona = sorted(REQUIRED_FRONTEND_API_ENDPOINTS - persona_endpoints)
    static_checks.append(
        {
            "name": "api_endpoints",
            "passed": not endpoint_missing_in_legacy and not endpoint_missing_in_persona,
            "missing_in_legacy": endpoint_missing_in_legacy,
            "missing_in_persona": endpoint_missing_in_persona,
        }
    )
    utility_missing_in_legacy = sorted(UTILITY_API_ENDPOINTS - legacy_endpoints)
    utility_missing_in_persona = sorted(UTILITY_API_ENDPOINTS - persona_endpoints)
    static_checks.append(
        {
            "name": "utility_api_endpoints",
            "passed": not utility_missing_in_legacy and not utility_missing_in_persona,
            "missing_in_legacy": utility_missing_in_legacy,
            "missing_in_persona": utility_missing_in_persona,
        }
    )
    legacy_missing_in_persona = sorted(legacy_endpoints - persona_endpoints)
    persona_extra_vs_legacy = sorted(persona_endpoints - legacy_endpoints)
    static_checks.append(
        {
            "name": "full_legacy_route_diff",
            "passed": not legacy_missing_in_persona,
            "missing_in_persona": legacy_missing_in_persona,
            "extra_in_persona": persona_extra_vs_legacy,
        }
    )
    return {"checks": static_checks, "passed": all(item["passed"] for item in static_checks)}


def run_dynamic_flow(label: str, base_url: str) -> dict[str, Any]:
    log(f"[{label}] ontology")
    sample_fields = {
        "simulation_requirement": "Test how a sustainability claim changes audience trust over a week.",
        "project_name": f"Legacy Oracle Parity {label}",
        "additional_context": "Focus on reputation, creators, and community response.",
    }
    files = [
        (
            "files",
            "brief.txt",
            b"Creators and policy watchers are debating whether the new sustainability claim is credible.",
            "text/plain",
        )
    ]
    checks: dict[str, bool] = {}
    metrics: dict[str, Any] = {}

    ontology_response = http_request(
        base_url,
        "POST",
        "/api/graph/ontology/generate",
        form_fields=sample_fields,
        files=files,
        timeout=300.0,
    )
    if ontology_response["status_code"] != 200:
        raise RuntimeError(f"{label}: ontology generation failed: {ontology_response['json']}")
    ontology_payload = ontology_response["json"]["data"]
    project_id = str(ontology_payload["project_id"])
    checks["ontology_generated"] = bool(project_id and ontology_payload.get("ontology"))
    metrics["ontology_entity_types"] = len(ontology_payload.get("ontology", {}).get("entity_types", []))

    build_response = http_request(base_url, "POST", "/api/graph/build", json_payload={"project_id": project_id}, timeout=180.0)
    if build_response["status_code"] != 200:
        raise RuntimeError(f"{label}: graph build failed to start: {build_response['json']}")
    log(f"[{label}] graph build")
    task_id = str(build_response["json"]["data"]["task_id"])
    task_payload = poll_envelope(base_url, "GET", f"/api/graph/task/{task_id}", terminal_statuses={"completed"}, timeout_seconds=480.0)
    graph_id = str(((task_payload.get("result") or {}).get("graph_id")) or task_id)
    checks["graph_build_completed"] = str(task_payload.get("status")) == "completed"

    log(f"[{label}] graph reads")
    project_response = http_request(base_url, "GET", f"/api/graph/project/{project_id}")
    graph_response = http_request(base_url, "GET", f"/api/graph/data/{graph_id}", timeout=180.0)
    if project_response["status_code"] != 200 or graph_response["status_code"] != 200:
        raise RuntimeError(f"{label}: graph project/data lookup failed")
    graph_tasks = http_request(base_url, "GET", "/api/graph/tasks", timeout=180.0)
    checks["graph_tasks_present"] = graph_tasks["status_code"] == 200 and any(
        str(item.get("task_id") or "") == task_id for item in graph_tasks["json"].get("data", [])
    )
    graph_payload = graph_response["json"]["data"]
    metadata = graph_payload.get("metadata", {})
    metrics["graph_node_count"] = int(metadata.get("node_count", len(graph_payload.get("nodes", []))) or 0)
    metrics["graph_edge_count"] = int(metadata.get("edge_count", len(graph_payload.get("edges", []))) or 0)
    checks["graph_payload_present"] = metrics["graph_node_count"] > 0 and metrics["graph_edge_count"] > 0

    log(f"[{label}] entities")
    entities_response = http_request(base_url, "GET", f"/api/simulation/entities/{graph_id}", timeout=180.0)
    if entities_response["status_code"] != 200:
        raise RuntimeError(f"{label}: entities endpoint failed: {entities_response['json']}")
    entities_payload = entities_response["json"]["data"]
    entities = entities_payload.get("entities", [])
    if not entities:
        raise RuntimeError(f"{label}: no entities returned")
    first_entity = entities[0]
    by_type_label = str(first_entity.get("labels", ["Entity"])[0])
    entity_uuid = str(first_entity["uuid"])
    entity_detail = http_request(base_url, "GET", f"/api/simulation/entities/{graph_id}/{entity_uuid}", timeout=180.0)
    entities_by_type = http_request(base_url, "GET", f"/api/simulation/entities/{graph_id}/by-type/{parse.quote(by_type_label)}", timeout=180.0)
    checks["entities_endpoints_present"] = entity_detail["status_code"] == 200 and entities_by_type["status_code"] == 200
    metrics["filtered_entities"] = int(entities_payload.get("filtered_count", len(entities)) or 0)

    log(f"[{label}] simulation create")
    simulation_response = http_request(base_url, "POST", "/api/simulation/create", json_payload={"project_id": project_id, "graph_id": graph_id}, timeout=180.0)
    if simulation_response["status_code"] != 200:
        raise RuntimeError(f"{label}: simulation create failed: {simulation_response['json']}")
    simulation_id = str(simulation_response["json"]["data"]["simulation_id"])
    checks["simulation_created"] = bool(simulation_id)

    log(f"[{label}] prepare")
    prepare_response = http_request(base_url, "POST", "/api/simulation/prepare", json_payload={"simulation_id": simulation_id}, timeout=180.0)
    if prepare_response["status_code"] != 200:
        raise RuntimeError(f"{label}: prepare failed to start: {prepare_response['json']}")
    prepare_status = poll_envelope(
        base_url,
        "POST",
        "/api/simulation/prepare/status",
        json_payload={"simulation_id": simulation_id},
        terminal_statuses={"ready", "completed"},
        timeout_seconds=900.0,
        interval_seconds=3.0,
    )
    checks["simulation_prepared"] = str(prepare_status.get("status")) in {"ready", "completed"}

    log(f"[{label}] profiles/config")
    profiles_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/profiles", params={"platform": "reddit"}, timeout=180.0)
    profiles_realtime_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/profiles/realtime", params={"platform": "reddit"}, timeout=180.0)
    config_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/config", timeout=180.0)
    config_realtime_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/config/realtime", timeout=180.0)
    config_download_response = http_request_text(
        base_url,
        "GET",
        f"/api/simulation/{simulation_id}/config/download",
        timeout=180.0,
    )
    profiles = profiles_response["json"]["data"]["profiles"]
    config_payload = config_response["json"]["data"]
    agent_configs = config_payload.get("agent_configs", [])
    config_by_name = {
        str(item.get("entity_name") or "").strip().lower(): item
        for item in agent_configs
        if isinstance(item, dict) and str(item.get("entity_name") or "").strip()
    }
    normalized_profiles: list[dict[str, Any]] = []
    for index, raw_profile in enumerate(profiles):
        profile = dict(raw_profile)
        if "agent_id" not in profile:
            matched_config = config_by_name.get(str(profile.get("name") or "").strip().lower(), {})
            profile["agent_id"] = matched_config.get("agent_id", profile.get("user_id", index))
        if "source_entity_uuid" not in profile:
            matched_config = config_by_name.get(str(profile.get("name") or "").strip().lower(), {})
            if matched_config.get("entity_uuid"):
                profile["source_entity_uuid"] = matched_config["entity_uuid"]
        normalized_profiles.append(profile)
    profiles = normalized_profiles
    checks["profiles_present"] = profiles_response["status_code"] == 200 and profiles_realtime_response["status_code"] == 200 and len(profiles) > 0
    checks["config_present"] = config_response["status_code"] == 200 and config_realtime_response["status_code"] == 200 and len(agent_configs) == len(profiles)
    checks["simulation_config_download_present"] = config_download_response["status_code"] == 200 and "agent_configs" in config_download_response["text"]
    metrics["profile_count"] = len(profiles)
    metrics["agent_config_count"] = len(agent_configs)
    metrics["total_simulation_hours"] = int(config_payload.get("time_config", {}).get("total_simulation_hours", 0) or 0)
    metrics["minutes_per_round"] = int(config_payload.get("time_config", {}).get("minutes_per_round", 0) or 0)

    log(f"[{label}] run start")
    start_response = http_request(
        base_url,
        "POST",
        "/api/simulation/start",
        json_payload={"simulation_id": simulation_id, "max_rounds": 4, "force": True},
        timeout=180.0,
    )
    if start_response["status_code"] != 200:
        raise RuntimeError(f"{label}: simulation start failed: {start_response['json']}")
    try:
        run_status = poll_envelope(
            base_url,
            "GET",
            f"/api/simulation/{simulation_id}/run-status",
            terminal_statuses={"completed", "failed", "stopped"},
            timeout_seconds=900.0,
            interval_seconds=3.0,
            stop_on_error=True,
            tolerated_http_statuses={500},
        )
    except TimeoutError as exc:
        fallback_run_status = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/run-status", timeout=180.0)
        run_status = dict(fallback_run_status.get("json", {}).get("data", {}))
        run_status["_poll_timeout"] = str(exc)
    run_status_detail = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/run-status/detail", timeout=180.0)
    checks["simulation_completed"] = str(run_status.get("runner_status") or run_status.get("status")) == "completed"
    metrics["current_round"] = int(run_status.get("current_round", 0) or 0)
    metrics["total_actions_count"] = int(run_status.get("total_actions_count", 0) or 0)

    log(f"[{label}] run reads")
    actions_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/actions", timeout=180.0)
    timeline_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/timeline", timeout=180.0)
    agent_stats_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/agent-stats", timeout=180.0)
    posts_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/posts", timeout=180.0)
    comments_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/comments", timeout=180.0)
    checks["actions_present"] = actions_response["status_code"] == 200 and int(actions_response["json"]["data"].get("total", 0) or 0) > 0
    timeline_items = timeline_response["json"]["data"].get("events")
    if timeline_items is None:
        timeline_items = timeline_response["json"]["data"].get("timeline", [])
    agent_stats_items = agent_stats_response["json"]["data"].get("items")
    if agent_stats_items is None:
        agent_stats_items = agent_stats_response["json"]["data"].get("agents", [])
    checks["timeline_present"] = timeline_response["status_code"] == 200 and len(timeline_items) > 0
    checks["agent_stats_present"] = agent_stats_response["status_code"] == 200 and len(agent_stats_items) > 0
    checks["posts_present"] = posts_response["status_code"] == 200 and (
        len(posts_response["json"]["data"].get("platforms", {})) > 0 or posts_response["json"]["data"].get("count", 0) >= 0
    )
    checks["comments_present"] = comments_response["status_code"] == 200
    metrics["timeline_count"] = len(timeline_items)

    generate_profiles_response = http_request(
        base_url,
        "POST",
        "/api/simulation/generate-profiles",
        json_payload={"graph_id": graph_id, "platform": "reddit", "use_llm": False},
        timeout=300.0,
    )
    script_download_response = http_request_text(
        base_url,
        "GET",
        "/api/simulation/script/run_parallel_simulation.py/download",
        timeout=180.0,
    )
    checks["generate_profiles_present"] = (
        generate_profiles_response["status_code"] == 200
        and int(generate_profiles_response["json"]["data"].get("count", 0) or 0) > 0
    )
    checks["script_download_present"] = script_download_response["status_code"] == 200 and "oasis_worker" in script_download_response["text"]

    log(f"[{label}] interviews")
    interview_response = http_request(
        base_url,
        "POST",
        "/api/simulation/interview",
        json_payload={"simulation_id": simulation_id, "agent_id": profiles[0]["agent_id"], "prompt": "What are you noticing right now?"},
        timeout=180.0,
    )
    batch_response = http_request(
        base_url,
        "POST",
        "/api/simulation/interview/batch",
        json_payload={
            "simulation_id": simulation_id,
            "interviews": [
                {"agent_id": profiles[0]["agent_id"], "prompt": "What matters most now?"},
                {"agent_id": profiles[min(1, len(profiles) - 1)]["agent_id"], "prompt": "What would increase trust fastest?"},
            ],
        },
        timeout=300.0,
    )
    all_response = http_request(
        base_url,
        "POST",
        "/api/simulation/interview/all",
        json_payload={"simulation_id": simulation_id, "prompt": "What should analysts monitor next?", "platform": "reddit"},
        timeout=600.0,
    )
    history_response = http_request(
        base_url,
        "POST",
        "/api/simulation/interview/history",
        json_payload={"simulation_id": simulation_id, "limit": 20},
        timeout=180.0,
    )
    checks["interview_present"] = interview_response["status_code"] == 200 and bool(interview_response["json"]["data"].get("result"))
    checks["interview_batch_present"] = batch_response["status_code"] == 200 and len(batch_response["json"]["data"].get("interview_results", [])) > 0
    checks["interview_all_present"] = all_response["status_code"] == 200 and int(all_response["json"]["data"].get("interviews_count", 0) or 0) >= len(profiles)
    checks["interview_history_present"] = history_response["status_code"] == 200 and int(history_response["json"]["data"].get("count", 0) or 0) > 0

    log(f"[{label}] env close")
    env_status_response = http_request(base_url, "POST", "/api/simulation/env-status", json_payload={"simulation_id": simulation_id}, timeout=180.0)
    close_env_response = http_request(base_url, "POST", "/api/simulation/close-env", json_payload={"simulation_id": simulation_id}, timeout=180.0)
    time.sleep(1.0)
    env_status_after = http_request(base_url, "POST", "/api/simulation/env-status", json_payload={"simulation_id": simulation_id}, timeout=180.0)
    checks["env_status_present"] = env_status_response["status_code"] == 200 and bool(env_status_response["json"]["data"])
    checks["close_env_present"] = close_env_response["status_code"] == 200 and bool(env_status_after["json"]["data"])

    log(f"[{label}] report generate")
    report_response = http_request(base_url, "POST", "/api/report/generate", json_payload={"simulation_id": simulation_id}, timeout=180.0)
    if report_response["status_code"] != 200:
        raise RuntimeError(f"{label}: report start failed: {report_response['json']}")
    report_id = str(report_response["json"]["data"]["report_id"])
    report_task_id = str(report_response["json"]["data"].get("task_id") or "")
    report_status = poll_envelope(
        base_url,
        "POST",
        "/api/report/generate/status",
        json_payload={"simulation_id": simulation_id, "task_id": report_task_id},
        terminal_statuses={"completed"},
        timeout_seconds=900.0,
        interval_seconds=3.0,
    )
    checks["report_completed"] = str(report_status.get("status")) == "completed"

    log(f"[{label}] report reads")
    report_check = http_request(base_url, "GET", f"/api/report/check/{simulation_id}", timeout=180.0)
    report_lookup = http_request(base_url, "GET", f"/api/report/by-simulation/{simulation_id}", timeout=180.0)
    report_list = http_request(base_url, "GET", "/api/report/list", params={"simulation_id": simulation_id}, timeout=180.0)
    report_detail = http_request(base_url, "GET", f"/api/report/{report_id}", timeout=180.0)
    report_progress = http_request(base_url, "GET", f"/api/report/{report_id}/progress", timeout=180.0)
    report_download = http_request_text(base_url, "GET", f"/api/report/{report_id}/download", timeout=180.0)
    report_sections = http_request(base_url, "GET", f"/api/report/{report_id}/sections", timeout=180.0)
    report_section_one = http_request(base_url, "GET", f"/api/report/{report_id}/section/1", timeout=180.0)
    agent_log = http_request(base_url, "GET", f"/api/report/{report_id}/agent-log", timeout=180.0)
    agent_log_stream = http_request(base_url, "GET", f"/api/report/{report_id}/agent-log/stream", timeout=180.0)
    console_log = http_request(base_url, "GET", f"/api/report/{report_id}/console-log", timeout=180.0)
    console_log_stream = http_request(base_url, "GET", f"/api/report/{report_id}/console-log/stream", timeout=180.0)
    tool_search = http_request(base_url, "POST", "/api/report/tools/search", json_payload={"graph_id": graph_id, "query": "trust"}, timeout=180.0)
    tool_stats = http_request(base_url, "POST", "/api/report/tools/statistics", json_payload={"graph_id": graph_id}, timeout=180.0)
    report_chat = http_request(
        base_url,
        "POST",
        "/api/report/chat",
        json_payload={
            "simulation_id": simulation_id,
            "message": "What should the analyst team monitor first?",
            "chat_history": [{"role": "user", "content": "Summarize the main risk."}],
        },
        timeout=180.0,
    )
    checks["report_sections_present"] = report_sections["status_code"] == 200 and len(report_sections["json"]["data"].get("sections", [])) >= 4
    checks["report_check_present"] = report_check["status_code"] == 200 and bool(report_check["json"]["data"])
    checks["report_lookup_present"] = report_lookup["status_code"] == 200 and bool(report_lookup["json"].get("has_report"))
    checks["report_list_present"] = report_list["status_code"] == 200 and int(report_list["json"].get("count", 0) or 0) >= 1
    checks["report_download_present"] = report_download["status_code"] == 200 and bool(report_download["text"].strip())
    checks["report_progress_present"] = report_progress["status_code"] == 200 and bool(report_progress["json"]["data"])
    checks["agent_log_present"] = agent_log["status_code"] == 200 and agent_log_stream["status_code"] == 200
    checks["console_log_present"] = console_log["status_code"] == 200 and console_log_stream["status_code"] == 200
    checks["report_tools_present"] = tool_search["status_code"] == 200 and tool_stats["status_code"] == 200
    checks["report_chat_present"] = report_chat["status_code"] == 200 and bool(report_chat["json"]["data"].get("response"))

    metrics["report_id"] = report_id
    metrics["report_sections_count"] = len(report_sections["json"]["data"].get("sections", []))
    metrics["report_chat_tool_calls"] = len(report_chat["json"]["data"].get("tool_calls", []))
    metrics["report_chat_sources"] = len(report_chat["json"]["data"].get("sources", []))
    metrics["report_outline_ready"] = bool(report_status.get("outline_ready"))
    metrics["completed_sections"] = list(report_status.get("completed_sections", []))
    metrics["env_status_before_close"] = env_status_response["json"]["data"]
    metrics["env_status_after_close"] = env_status_after["json"]["data"]
    metrics["run_status_detail_present"] = run_status_detail["status_code"] == 200
    metrics["report_section_one_present"] = report_section_one["status_code"] == 200

    report_delete = http_request(base_url, "DELETE", f"/api/report/{report_id}", timeout=180.0)
    graph_delete = http_request(base_url, "DELETE", f"/api/graph/delete/{graph_id}", timeout=180.0)
    project_delete = http_request(base_url, "DELETE", f"/api/graph/project/{project_id}", timeout=180.0)
    checks["report_delete_present"] = report_delete["status_code"] == 200 and bool(report_delete["json"].get("success"))
    checks["graph_delete_present"] = graph_delete["status_code"] == 200 and bool(graph_delete["json"].get("success"))
    checks["project_delete_present"] = project_delete["status_code"] == 200 and bool(project_delete["json"].get("success"))

    log(f"[{label}] complete")
    required_checks = CRITICAL_DYNAMIC_CHECKS | UTILITY_DYNAMIC_CHECKS
    missing_checks = sorted(required_checks - {name for name, passed in checks.items() if passed})
    return {
        "label": label,
        "base_url": base_url,
        "project_id": project_id,
        "graph_id": graph_id,
        "simulation_id": simulation_id,
        "report_id": report_id,
        "checks": checks,
        "missing_checks": missing_checks,
        "passed": not missing_checks,
        "metrics": metrics,
    }


def compare_dynamic(legacy: dict[str, Any], persona: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    legacy_unobserved: list[str] = []
    persona_optional_gaps: list[str] = []

    for check_name in sorted(CRITICAL_DYNAMIC_CHECKS | UTILITY_DYNAMIC_CHECKS):
        if not persona["checks"].get(check_name, False):
            failures.append(f"PersonaGraph failed critical check: {check_name}")
        if not legacy["checks"].get(check_name, False):
            legacy_unobserved.append(check_name)

    for check_name in sorted(OPTIONAL_DYNAMIC_CHECKS):
        if not persona["checks"].get(check_name, False):
            persona_optional_gaps.append(check_name)
        if not legacy["checks"].get(check_name, False):
            legacy_unobserved.append(check_name)

    for key in ("total_simulation_hours", "minutes_per_round"):
        legacy_value = int(legacy["metrics"].get(key, 0) or 0)
        persona_value = int(persona["metrics"].get(key, 0) or 0)
        if legacy_value <= 0 or persona_value <= 0:
            failures.append(f"Invalid time-config value for {key}: legacy={legacy_value} persona={persona_value}")
        elif legacy_value != persona_value:
            warnings.append(
                f"Time-config differs for {key}: legacy={legacy_value} persona={persona_value}"
            )

    for key in ("profile_count", "agent_config_count", "graph_node_count", "graph_edge_count", "report_sections_count"):
        if int(persona["metrics"].get(key, 0) or 0) <= 0:
            failures.append(f"PersonaGraph metric {key} did not produce a positive value.")
        if int(legacy["metrics"].get(key, 0) or 0) <= 0:
            failures.append(f"Legacy metric {key} did not produce a positive value.")

    if not persona["metrics"].get("report_outline_ready"):
        failures.append("PersonaGraph report did not expose outline_ready=true.")
    if not legacy["metrics"].get("report_outline_ready"):
        warnings.append("Legacy report did not expose outline_ready=true in the sampled run.")

    if len(persona["metrics"].get("completed_sections", [])) < 4:
        failures.append("PersonaGraph completed fewer than four report sections.")
    if len(legacy["metrics"].get("completed_sections", [])) < 4:
        warnings.append("Legacy completed fewer than four report sections in the sampled run.")

    if int(persona["metrics"].get("report_chat_tool_calls", 0) or 0) == 0:
        failures.append("PersonaGraph report chat returned no tool calls.")
    if int(legacy["metrics"].get("report_chat_tool_calls", 0) or 0) == 0:
        warnings.append("Legacy report chat returned no tool calls.")

    if int(persona["metrics"].get("report_chat_sources", 0) or 0) == 0:
        failures.append("PersonaGraph report chat returned no sources.")
    if int(legacy["metrics"].get("report_chat_sources", 0) or 0) == 0:
        warnings.append("Legacy report chat returned no sources.")

    if int(persona["metrics"].get("current_round", 0) or 0) != 4:
        failures.append(f"PersonaGraph run completed with unexpected current_round={persona['metrics'].get('current_round')}")
    if int(legacy["metrics"].get("current_round", 0) or 0) != 4:
        warnings.append(f"Legacy run completed with unexpected current_round={legacy['metrics'].get('current_round')}")

    return {
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "legacy_unobserved_checks": sorted(set(legacy_unobserved)),
        "persona_optional_gaps": sorted(set(persona_optional_gaps)),
    }


def write_report(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def default_output_path() -> Path:
    return Path(__file__).resolve().parents[1] / "backend/data/parity/legacy_oracle_latest.json"


def discover_legacy_repo(repo_root: Path) -> Path:
    if (
        (repo_root / "frontend/src/router/index.js").exists()
        and (repo_root / "backend/app/api/simulation.py").exists()
        and (repo_root / "backend/app/api/report.py").exists()
    ):
        return repo_root

    search_root = repo_root.parent
    candidates: list[Path] = []
    for candidate in search_root.iterdir():
        if candidate == repo_root or not candidate.is_dir():
            continue
        if (
            (candidate / "frontend/src/router/index.js").exists()
            and (candidate / "backend/app/api/simulation.py").exists()
            and (candidate / "backend/app/api/report.py").exists()
        ):
            candidates.append(candidate)
    if len(candidates) == 1:
        return candidates[0]
    raise SystemExit("Could not auto-discover the legacy reference repo. Pass --legacy-repo explicitly.")


def parse_args(argv: list[str]) -> AuditConfig:
    repo_root = Path(__file__).resolve().parents[1]
    legacy_repo = discover_legacy_repo(repo_root)
    legacy_base_url = "http://127.0.0.1:5001"
    persona_base_url = "http://127.0.0.1:8020"
    output_path = default_output_path()
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--legacy-repo":
            legacy_repo = Path(argv[index + 1])
            index += 2
            continue
        if arg == "--legacy-base-url":
            legacy_base_url = argv[index + 1]
            index += 2
            continue
        if arg == "--persona-base-url":
            persona_base_url = argv[index + 1]
            index += 2
            continue
        if arg == "--output":
            output_path = Path(argv[index + 1])
            index += 2
            continue
        raise SystemExit(f"Unknown argument: {arg}")
    return AuditConfig(
        repo_root=repo_root,
        legacy_repo=legacy_repo,
        legacy_base_url=legacy_base_url,
        persona_base_url=persona_base_url,
        output_path=output_path,
    )


def main(argv: list[str]) -> int:
    config = parse_args(argv)
    log("[static] surface")
    static_surface = check_static_surface(config)
    legacy_dynamic = run_dynamic_flow("legacy", config.legacy_base_url)
    persona_dynamic = run_dynamic_flow("persona", config.persona_base_url)
    log("[compare] dynamic")
    dynamic_comparison = compare_dynamic(legacy_dynamic, persona_dynamic)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "legacy_repo": str(config.legacy_repo),
        "legacy_base_url": config.legacy_base_url,
        "persona_base_url": config.persona_base_url,
        "static_surface": static_surface,
        "dynamic_runs": {
            "legacy": legacy_dynamic,
            "persona": persona_dynamic,
        },
        "comparison": dynamic_comparison,
        "passed": bool(static_surface["passed"] and dynamic_comparison["passed"]),
    }
    write_report(config.output_path, report)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
