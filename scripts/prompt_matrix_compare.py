#!/usr/bin/env python3
"""Run serial PersonaGraph vs legacy-reference comparisons for multiple prompt variants."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any

from legacy_oracle_parity import http_request, log, poll_envelope


DEFAULT_PERSONA_BASE = "http://127.0.0.1:8020"
DEFAULT_LEGACY_BASE = "http://127.0.0.1:5001"
DEFAULT_SEED_DIR = Path("/Users/aldo.fumagalli/Documents/GitHub") / ("Miro" + "Fish") / "seed_documents"
DEFAULT_OUTPUT = Path("/Users/aldo.fumagalli/Documents/GitHub/PersonaGraph/output/prompt-matrix-compare.json")
DEFAULT_CHAT_QUESTION = (
    "Does this simulation indicate sustained brand loyalty or a fleeting viral moment, "
    "and what are the main reasons?"
)


@dataclass(frozen=True)
class PromptCase:
    option: int
    title: str
    prompt: str


def parse_prompt_cases(path: Path) -> list[PromptCase]:
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^## Prompt Option (\d+): (.+?)\n> (.+?)(?=\n## Prompt Option \d+:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    cases: list[PromptCase] = []
    for option_raw, title, prompt in pattern.findall(content):
        cases.append(
            PromptCase(
                option=int(option_raw),
                title=title.strip(),
                prompt=" ".join(line.strip().lstrip("> ").strip() for line in prompt.strip().splitlines()).strip(),
            )
        )
    return cases


def extract_graph_id(project_payload: dict[str, Any], task_payload: dict[str, Any]) -> str:
    graph_id = (
        ((task_payload.get("result") or {}).get("graph_id"))
        or project_payload.get("graph_id")
        or project_payload.get("legacy_graph_id")
        or ""
    )
    return str(graph_id)


def load_project(base_url: str, project_id: str) -> dict[str, Any]:
    response = http_request(base_url, "GET", f"/api/graph/project/{project_id}")
    if response["status_code"] != 200 or not response["json"].get("success"):
        raise RuntimeError(f"project lookup failed for {project_id}: {response}")
    return response["json"]["data"]


def load_graph(base_url: str, graph_id: str) -> dict[str, Any]:
    response = http_request(base_url, "GET", f"/api/graph/data/{graph_id}", timeout=300.0)
    if response["status_code"] != 200 or not response["json"].get("success"):
        raise RuntimeError(f"graph lookup failed for {graph_id}: {response}")
    return response["json"]["data"]


def count_actions_by_platform(actions_payload: dict[str, Any]) -> dict[str, int]:
    items = actions_payload.get("actions") or actions_payload.get("items") or []
    platform_counts = {"twitter": 0, "reddit": 0}
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            platform = str(item.get("platform") or "").strip().lower()
            if platform in platform_counts:
                platform_counts[platform] += 1
    return platform_counts


def count_posts_comments(posts_payload: dict[str, Any], comments_payload: dict[str, Any]) -> dict[str, int]:
    twitter_posts = 0
    reddit_posts = 0
    comments = 0

    platforms = posts_payload.get("platforms")
    if isinstance(platforms, dict):
        twitter_posts = len(platforms.get("twitter") or [])
        reddit_posts = len(platforms.get("reddit") or [])
    else:
        items = posts_payload.get("posts") or posts_payload.get("items") or []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                platform = str(item.get("platform") or "").strip().lower()
                if platform == "twitter":
                    twitter_posts += 1
                elif platform == "reddit":
                    reddit_posts += 1

    comment_items = comments_payload.get("comments") or comments_payload.get("items") or []
    if isinstance(comment_items, list):
        comments = len(comment_items)
    elif isinstance(comment_items, dict):
        comments = sum(len(value or []) for value in comment_items.values())

    return {
        "twitter_posts": twitter_posts,
        "reddit_posts": reddit_posts,
        "comments": comments,
    }


def is_clean_chat_response(text: str) -> bool:
    lowered = text.lower()
    if not text.strip():
        return False
    banned_fragments = (
        "<think",
        "</think",
        "<final_answer",
        "paragraph 1:",
        "paragraph 2:",
        "format:",
        "input data:",
        "key entities:",
        "key findings:",
        "draft:",
    )
    return not any(fragment in lowered for fragment in banned_fragments)


def run_case(label: str, base_url: str, case: PromptCase, brief_path: Path, max_rounds: int) -> dict[str, Any]:
    log(f"[{label}] prompt {case.option} ontology")
    ontology_response = http_request(
        base_url,
        "POST",
        "/api/graph/ontology/generate",
        form_fields={
            "simulation_requirement": case.prompt,
            "project_name": f"Prompt {case.option} - {case.title} - {label}",
            "additional_context": "Keep the comparison aligned to the uploaded Ralph Lauren brief.",
        },
        files=[
            (
                "files",
                brief_path.name,
                brief_path.read_bytes(),
                "text/markdown",
            )
        ],
        timeout=600.0,
    )
    if ontology_response["status_code"] != 200 or not ontology_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: ontology failed: {ontology_response}")
    ontology_payload = ontology_response["json"]["data"]
    project_id = str(ontology_payload["project_id"])

    log(f"[{label}] prompt {case.option} graph build")
    build_response = http_request(
        base_url,
        "POST",
        "/api/graph/build",
        json_payload={"project_id": project_id},
        timeout=300.0,
    )
    if build_response["status_code"] != 200 or not build_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: graph build start failed: {build_response}")
    task_id = str(build_response["json"]["data"]["task_id"])
    task_payload = poll_envelope(
        base_url,
        "GET",
        f"/api/graph/task/{task_id}",
        terminal_statuses={"completed"},
        timeout_seconds=2400.0,
        interval_seconds=4.0,
    )
    project_payload = load_project(base_url, project_id)
    graph_id = extract_graph_id(project_payload, task_payload)
    graph_payload = load_graph(base_url, graph_id)
    graph_metadata = graph_payload.get("metadata") or {}
    graph_node_count = int(graph_metadata.get("node_count") or len(graph_payload.get("nodes") or []))
    graph_edge_count = int(graph_metadata.get("edge_count") or len(graph_payload.get("edges") or []))

    log(f"[{label}] prompt {case.option} simulation create/prepare")
    simulation_response = http_request(
        base_url,
        "POST",
        "/api/simulation/create",
        json_payload={"project_id": project_id, "graph_id": graph_id},
        timeout=300.0,
    )
    if simulation_response["status_code"] != 200 or not simulation_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: simulation create failed: {simulation_response}")
    simulation_id = str(simulation_response["json"]["data"]["simulation_id"])

    prepare_response = http_request(
        base_url,
        "POST",
        "/api/simulation/prepare",
        json_payload={"simulation_id": simulation_id},
        timeout=300.0,
    )
    if prepare_response["status_code"] != 200 or not prepare_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: prepare start failed: {prepare_response}")
    poll_envelope(
        base_url,
        "POST",
        "/api/simulation/prepare/status",
        json_payload={"simulation_id": simulation_id},
        terminal_statuses={"ready", "completed"},
        timeout_seconds=2400.0,
        interval_seconds=4.0,
    )
    config_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/config", timeout=300.0)
    if config_response["status_code"] != 200 or not config_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: config lookup failed: {config_response}")
    config_payload = config_response["json"]["data"]
    agent_configs = config_payload.get("agent_configs") or []

    log(f"[{label}] prompt {case.option} run start")
    start_response = http_request(
        base_url,
        "POST",
        "/api/simulation/start",
        json_payload={"simulation_id": simulation_id, "max_rounds": max_rounds, "force": True},
        timeout=300.0,
    )
    if start_response["status_code"] != 200 or not start_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: start failed: {start_response}")
    run_status = poll_envelope(
        base_url,
        "GET",
        f"/api/simulation/{simulation_id}/run-status",
        terminal_statuses={"completed"},
        timeout_seconds=2400.0,
        interval_seconds=4.0,
    )

    actions_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/actions", timeout=300.0)
    posts_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/posts", timeout=300.0)
    comments_response = http_request(base_url, "GET", f"/api/simulation/{simulation_id}/comments", timeout=300.0)
    if actions_response["status_code"] != 200 or not actions_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: actions lookup failed: {actions_response}")
    if posts_response["status_code"] != 200 or not posts_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: posts lookup failed: {posts_response}")
    if comments_response["status_code"] != 200 or not comments_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: comments lookup failed: {comments_response}")
    actions_payload = actions_response["json"]["data"]
    posts_payload = posts_response["json"]["data"]
    comments_payload = comments_response["json"]["data"]
    action_platform_counts = count_actions_by_platform(actions_payload)
    post_comment_counts = count_posts_comments(posts_payload, comments_payload)

    log(f"[{label}] prompt {case.option} report")
    report_response = http_request(
        base_url,
        "POST",
        "/api/report/generate",
        json_payload={"simulation_id": simulation_id},
        timeout=300.0,
    )
    if report_response["status_code"] != 200 or not report_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: report generate failed: {report_response}")
    report_data = report_response["json"]["data"]
    report_id = str(report_data["report_id"])
    report_task_id = str(report_data.get("task_id") or "")
    poll_envelope(
        base_url,
        "POST",
        "/api/report/generate/status",
        json_payload={"simulation_id": simulation_id, "task_id": report_task_id},
        terminal_statuses={"completed"},
        timeout_seconds=2400.0,
        interval_seconds=4.0,
    )
    report_detail_response = http_request(base_url, "GET", f"/api/report/{report_id}", timeout=300.0)
    report_sections_response = http_request(base_url, "GET", f"/api/report/{report_id}/sections", timeout=300.0)
    report_chat_response = http_request(
        base_url,
        "POST",
        "/api/report/chat",
        json_payload={
            "simulation_id": simulation_id,
            "message": DEFAULT_CHAT_QUESTION,
            "chat_history": [],
        },
        timeout=300.0,
    )
    if report_detail_response["status_code"] != 200 or not report_detail_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: report detail failed: {report_detail_response}")
    if report_sections_response["status_code"] != 200 or not report_sections_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: report sections failed: {report_sections_response}")
    if report_chat_response["status_code"] != 200 or not report_chat_response["json"].get("success"):
        raise RuntimeError(f"{label} prompt {case.option}: report chat failed: {report_chat_response}")
    report_detail = report_detail_response["json"]["data"]
    report_markdown = str(
        report_detail.get("markdown")
        or report_detail.get("markdown_content")
        or report_detail.get("content")
        or report_detail.get("full_report")
        or ""
    )
    report_sections = report_sections_response["json"]["data"].get("sections") or []
    report_chat_text = str(report_chat_response["json"]["data"].get("response") or "")

    return {
        "label": label,
        "project_id": project_id,
        "graph_task_id": task_id,
        "graph_id": graph_id,
        "simulation_id": simulation_id,
        "report_id": report_id,
        "prompt_option": case.option,
        "prompt_title": case.title,
        "ontology_types": [item.get("label") or item.get("name") or item for item in ontology_payload.get("ontology", {}).get("entity_types", [])],
        "graph_node_count": graph_node_count,
        "graph_edge_count": graph_edge_count,
        "prepared_personas": len(agent_configs),
        "requested_rounds": max_rounds,
        "applied_rounds": int(run_status.get("total_rounds") or max_rounds),
        "current_round": int(run_status.get("current_round") or 0),
        "total_actions": int(run_status.get("total_actions_count") or actions_payload.get("total") or 0),
        "twitter_actions": action_platform_counts["twitter"],
        "reddit_actions": action_platform_counts["reddit"],
        "twitter_posts": post_comment_counts["twitter_posts"],
        "reddit_posts": post_comment_counts["reddit_posts"],
        "comments": post_comment_counts["comments"],
        "report_sections": len(report_sections),
        "report_markdown_bytes": len(report_markdown.encode("utf-8")),
        "report_chat_clean": is_clean_chat_response(report_chat_text),
        "report_chat_excerpt": report_chat_text[:280],
    }


def compare_results(persona: dict[str, Any], legacy: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_node_delta": persona["graph_node_count"] - legacy["graph_node_count"],
        "graph_edge_delta": persona["graph_edge_count"] - legacy["graph_edge_count"],
        "persona_count_delta": persona["prepared_personas"] - legacy["prepared_personas"],
        "action_delta": persona["total_actions"] - legacy["total_actions"],
        "report_bytes_delta": persona["report_markdown_bytes"] - legacy["report_markdown_bytes"],
        "graph_band_close": abs(persona["graph_node_count"] - legacy["graph_node_count"]) <= 12
        and abs(persona["graph_edge_count"] - legacy["graph_edge_count"]) <= 12,
        "setup_band_close": abs(persona["prepared_personas"] - legacy["prepared_personas"]) <= 12,
        "runtime_band_close": abs(persona["total_actions"] - legacy["total_actions"]) <= 15,
        "report_chat_clean_both": persona["report_chat_clean"] and legacy["report_chat_clean"],
    }


def select_cases(all_cases: list[PromptCase], prompt_options: list[int]) -> list[PromptCase]:
    by_option = {case.option: case for case in all_cases}
    missing = [option for option in prompt_options if option not in by_option]
    if missing:
        raise ValueError(f"Prompt options not found: {missing}")
    return [by_option[option] for option in prompt_options]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona-base", default=DEFAULT_PERSONA_BASE)
    parser.add_argument("--legacy-base", default=DEFAULT_LEGACY_BASE)
    parser.add_argument("--seed-dir", type=Path, default=DEFAULT_SEED_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument(
        "--prompts",
        default="2,4,5",
        help="Comma-separated prompt option numbers to compare.",
    )
    args = parser.parse_args()

    prompt_readme = args.seed_dir / "README_simulation_prompts.md"
    brief_path = args.seed_dir / "ralph_lauren_marketing_brief.md"
    cases = select_cases(
        parse_prompt_cases(prompt_readme),
        [int(item.strip()) for item in args.prompts.split(",") if item.strip()],
    )

    output: dict[str, Any] = {
        "persona_base": args.persona_base,
        "legacy_base": args.legacy_base,
        "rounds": args.rounds,
        "cases": [],
    }
    for case in cases:
        persona_result = run_case("PersonaGraph", args.persona_base, case, brief_path, args.rounds)
        legacy_result = run_case("Legacy Reference", args.legacy_base, case, brief_path, args.rounds)
        output["cases"].append(
            {
                "prompt_option": case.option,
                "prompt_title": case.title,
                "prompt": case.prompt,
                "persona": persona_result,
                "legacy": legacy_result,
                "comparison": compare_results(persona_result, legacy_result),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(output, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
