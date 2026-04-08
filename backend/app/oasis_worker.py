"""Native OASIS simulation worker for the React glass workflow."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import traceback
from typing import Any

from .config import get_settings
from .services.glass_compat import (
    graph_live_path,
    load_graph_payload,
    load_simulation_actions,
    load_simulation_config,
    load_simulation_profiles,
    load_simulation_state,
    save_graph_payload,
    simulation_actions_path,
    simulation_comments_path,
    simulation_env_path,
    simulation_interviews_path,
    simulation_posts_path,
    simulation_state_path,
)
from .services.generation import looks_like_prompt_echo, sanitize_short_model_text
from .services.llm import LLMGenerationError, OpenAICompatibleLLM
from .services.oasis_runtime import (
    append_simulation_log,
    build_agent_maps,
    build_camel_model,
    choose_active_agent_ids,
    env_status_alias_path,
    fetch_new_actions_from_db,
    ipc_commands_dir,
    ipc_responses_dir,
    load_comments_from_db,
    load_posts_from_db,
    platform_actions_jsonl_path,
    platform_db_path,
    poll_next_ipc_command,
    read_latest_interview_response,
    reddit_profiles_json_path,
    run_state_alias_path,
    twitter_profiles_csv_path,
    write_ipc_response,
    write_runtime_env,
    write_runtime_state,
)


SHUTDOWN_EVENT: asyncio.Event | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(settings, simulation_id: str, message: str) -> None:
    print(message, flush=True)
    append_simulation_log(settings, simulation_id, message)


def _set_state(settings, simulation_id: str, **updates: Any) -> dict[str, Any]:
    path = simulation_state_path(settings, simulation_id)
    state = load_simulation_state(settings, simulation_id)
    state.update(updates)
    write_runtime_state(path, run_state_alias_path(settings, simulation_id), state)
    return state


def _set_env(settings, simulation_id: str, **updates: Any) -> dict[str, Any]:
    path = simulation_env_path(settings, simulation_id)
    payload = {
        "status": "idle",
        "twitter_available": False,
        "reddit_available": False,
        "closed_at": "",
    }
    payload.update(updates)
    write_runtime_env(path, env_status_alias_path(settings, simulation_id), payload)
    return payload


def _safe_write_json(path: Path, payload: Any) -> None:
    from .services.oasis_runtime import _write_json  # local import keeps helper private

    _write_json(path, payload)


def _fallback_interview_response(
    *,
    agent_name: str,
    platform: str,
    profile: dict[str, Any],
    prompt: str,
    recent_actions: list[dict[str, Any]],
) -> str:
    trust_lens = str(profile.get("trust_lens") or "").strip()
    platform_behavior = str(profile.get("platform_behavior") or "").strip()
    topics = [str(item).strip() for item in profile.get("interested_topics", []) if str(item).strip()]
    topic_text = ", ".join(topics[:2]) or "brand trust and public reaction"
    signal_line = ""
    visible_action = next(
        (
            str(item.get("content") or "").strip()
            for item in reversed(recent_actions)
            if str(item.get("content") or "").strip()
            and str(item.get("action_type") or "").upper() not in {"REFRESH", "TREND", "SEARCH_POSTS", "SEARCH_USER", "DO_NOTHING"}
        ),
        "",
    )
    if visible_action:
        snippet = visible_action if len(visible_action) <= 220 else f"{visible_action[:217].rsplit(' ', 1)[0]}..."
        signal_line = f" The clearest recent signal I saw was: {snippet}"
    behavioral_read = platform_behavior or (
        f"On {platform}, I watch whether attention around {topic_text.lower()} becomes conviction or just another short cycle."
    )
    trust_read = trust_lens or (
        f"My main test is whether the conversation around {topic_text.lower()} is earning trust or just stacking visibility."
    )
    return (
        f"I'm {agent_name}, and from the {platform} side of the simulation I'm reading this through {topic_text.lower()}. "
        f"{trust_read} {behavioral_read}{signal_line} "
        f"That is what shapes how I answer the question: {prompt}"
    )


def _response_is_shallow(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return True
    bad_prefixes = (
        "persona function:",
        "role:",
        "bio:",
        "trust lens:",
        "platform behavior:",
        "narrative role:",
        "persona description:",
    )
    if lowered.startswith(bad_prefixes):
        return True
    if len(lowered.split()) < 14:
        return True
    return False


def _extend_graph(settings, graph_id: str | None, round_number: int, round_actions: list[dict[str, Any]]) -> None:
    if not graph_id or not round_actions:
        return
    graph_path = graph_live_path(settings, graph_id)
    if not graph_path.exists():
        return
    payload = load_graph_payload(settings, graph_id)
    nodes = list(payload.get("nodes", []))
    edges = list(payload.get("edges", []))
    lead = round_actions[0]
    topic = str(lead.get("action_args", {}).get("post_content") or lead.get("content") or lead.get("action_type") or "Signal")
    topic = topic.strip()[:60] or "Signal"
    signal_id = f"oasis_signal_{round_number:03d}"
    if not any(str(item.get("uuid")) == signal_id for item in nodes):
        nodes.append(
            {
                "uuid": signal_id,
                "name": f"Round {round_number} signal",
                "label": "Signal",
                "summary": topic,
            }
        )
        for item in round_actions[:4]:
            agent_id = str(item.get("agent_id") or "")
            agent_name = str(item.get("agent_name") or agent_id or "Agent")
            agent_node_id = f"agent_delta_{agent_id}"
            if not any(str(node.get("uuid")) == agent_node_id for node in nodes):
                nodes.append(
                    {
                        "uuid": agent_node_id,
                        "name": agent_name,
                        "label": "Simulated Agent",
                        "summary": f"Active in the OASIS simulation during round {round_number}.",
                    }
                )
            edges.append(
                {
                    "uuid": f"edge_{signal_id}_{agent_node_id}",
                    "source_uuid": agent_node_id,
                    "target_uuid": signal_id,
                    "relation_type": "contributed_to",
                    "fact": f"{agent_name} contributed to the live discussion in round {round_number}.",
                }
            )
    payload["nodes"] = nodes
    payload["edges"] = edges
    payload["metadata"] = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "entity_types": sorted({str(node.get("label", "Entity")) for node in nodes}),
        "edge_types": sorted({str(edge.get("relation_type", "related_to")) for edge in edges}),
    }
    save_graph_payload(settings, graph_id, payload)


def _install_signal_handlers() -> None:
    def _handle_signal(signum, frame) -> None:  # noqa: ARG001
        if SHUTDOWN_EVENT is not None:
            SHUTDOWN_EVENT.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)


async def _init_platform(
    *,
    settings,
    simulation_id: str,
    platform: str,
):
    import oasis
    from oasis import ActionType, generate_reddit_agent_graph, generate_twitter_agent_graph

    db_path = platform_db_path(settings, simulation_id, platform)
    db_path.unlink(missing_ok=True)
    model = build_camel_model(settings)

    if platform == "twitter":
        agent_graph = await generate_twitter_agent_graph(
            profile_path=str(twitter_profiles_csv_path(settings, simulation_id)),
            model=model,
            available_actions=[
                ActionType.CREATE_POST,
                ActionType.LIKE_POST,
                ActionType.REPOST,
                ActionType.FOLLOW,
                ActionType.DO_NOTHING,
                ActionType.QUOTE_POST,
            ],
        )
        env = oasis.make(
            agent_graph=agent_graph,
            platform=oasis.DefaultPlatformType.TWITTER,
            database_path=str(db_path),
            semaphore=30,
        )
    else:
        agent_graph = await generate_reddit_agent_graph(
            profile_path=str(reddit_profiles_json_path(settings, simulation_id)),
            model=model,
            available_actions=ActionType.get_default_reddit_actions(),
        )
        env = oasis.make(
            agent_graph=agent_graph,
            platform=oasis.DefaultPlatformType.REDDIT,
            database_path=str(db_path),
            semaphore=30,
        )

    await env.reset()
    return {"env": env, "agent_graph": agent_graph, "db_path": db_path, "last_rowid": 0}


async def _seed_initial_posts(
    *,
    contexts: dict[str, dict[str, Any]],
    config: dict[str, Any],
    simulation_id: str,
    settings,
    numeric_to_name: dict[int, str],
    preview_run: bool,
) -> list[dict[str, Any]]:
    from oasis import ActionType, ManualAction

    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    if not isinstance(initial_posts, list) or not initial_posts:
        return []
    seeded_actions: list[dict[str, Any]] = []
    for platform, context in contexts.items():
        actions: dict[Any, Any] = {}
        platform_posts = 0
        for item in initial_posts:
            target_platform = str(item.get("platform") or "")
            if target_platform and target_platform != platform:
                continue
            if preview_run and platform_posts >= 4:
                break
            try:
                poster_id = int(item.get("poster_agent_id"))
            except Exception:
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            try:
                agent = context["agent_graph"].get_agent(poster_id)
            except Exception:
                continue
            action = ManualAction(action_type=ActionType.CREATE_POST, action_args={"content": content})
            existing = actions.get(agent)
            if existing is None:
                actions[agent] = action
            elif isinstance(existing, list):
                existing.append(action)
            else:
                actions[agent] = [existing, action]
            platform_posts += 1
        if not actions:
            continue
        await context["env"].step(actions)
        _log(settings, simulation_id, f"[{platform}] seeded {len(actions)} initial posts")
        initial_actions, new_last_rowid = fetch_new_actions_from_db(
            context["db_path"],
            platform=platform,
            last_rowid=context["last_rowid"],
            numeric_to_external=context["numeric_to_external"],
            numeric_to_name=numeric_to_name,
            round_num=0,
        )
        context["last_rowid"] = new_last_rowid
        seeded_actions.extend(initial_actions)
        from .services.oasis_runtime import _append_jsonl

        for action in initial_actions:
            _append_jsonl(platform_actions_jsonl_path(settings, simulation_id, platform), action)
    _safe_write_json(simulation_actions_path(settings, simulation_id), seeded_actions)
    return seeded_actions


async def _seed_scheduled_events(
    *,
    contexts: dict[str, dict[str, Any]],
    config: dict[str, Any],
    simulation_id: str,
    settings,
    numeric_to_name: dict[int, str],
    round_number: int,
    simulated_hour: int,
    fired_event_ids: set[str],
    preview_run: bool,
) -> list[dict[str, Any]]:
    from oasis import ActionType, ManualAction

    event_config = config.get("event_config", {})
    scheduled_events = event_config.get("scheduled_events", [])
    if not isinstance(scheduled_events, list) or not scheduled_events:
        return []

    due_events: list[dict[str, Any]] = []
    for index, item in enumerate(scheduled_events, start=1):
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("event_id") or f"event_{index:02d}")
        if event_id in fired_event_ids:
            continue
        event_round = int(item.get("round", 0) or 0)
        event_hour = int(item.get("simulated_hour", -1) or -1)
        if event_round and event_round != round_number:
            continue
        if not event_round and event_hour >= 0 and event_hour != simulated_hour:
            continue
        due_events.append({**item, "event_id": event_id})

    if preview_run and len(due_events) > 4:
        due_events = due_events[:4]

    if not due_events:
        return []

    seeded_actions: list[dict[str, Any]] = []
    for platform, context in contexts.items():
        actions: dict[Any, Any] = {}
        for item in due_events:
            target_platform = str(item.get("platform") or "").strip().lower()
            if target_platform and target_platform not in {platform, "both"}:
                continue
            try:
                poster_id = int(item.get("poster_agent_id"))
            except Exception:
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            try:
                agent = context["agent_graph"].get_agent(poster_id)
            except Exception:
                continue
            action = ManualAction(action_type=ActionType.CREATE_POST, action_args={"content": content})
            existing = actions.get(agent)
            if existing is None:
                actions[agent] = action
            elif isinstance(existing, list):
                existing.append(action)
            else:
                actions[agent] = [existing, action]
        if not actions:
            continue
        await context["env"].step(actions)
        _log(settings, simulation_id, f"[{platform}] seeded {len(actions)} scheduled events in round {round_number}")
        round_actions, new_last_rowid = fetch_new_actions_from_db(
            context["db_path"],
            platform=platform,
            last_rowid=context["last_rowid"],
            numeric_to_external=context["numeric_to_external"],
            numeric_to_name=numeric_to_name,
            round_num=round_number,
        )
        context["last_rowid"] = new_last_rowid
        seeded_actions.extend(round_actions)
        from .services.oasis_runtime import _append_jsonl

        for action in round_actions:
            _append_jsonl(platform_actions_jsonl_path(settings, simulation_id, platform), action)
    for item in due_events:
        fired_event_ids.add(str(item["event_id"]))
    if seeded_actions:
        _safe_write_json(simulation_actions_path(settings, simulation_id), load_simulation_actions(settings, simulation_id) + seeded_actions)
    return seeded_actions


async def _interview_single_platform(
    *,
    settings,
    simulation_id: str,
    context: dict[str, Any],
    platform: str,
    numeric_id: int,
    external_id: str,
    agent_name: str,
    prompt: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    recent_actions = [
        item
        for item in load_simulation_actions(settings, simulation_id)
        if str(item.get("agent_id") or "") == external_id and str(item.get("platform") or "") == platform
    ][-5:]
    action_summary = "\n".join(
        f"- Round {item.get('round_num', '?')}: {item.get('action_type', 'ACTION')} :: {item.get('content') or item.get('action_args', {})}"
        for item in recent_actions
    ) or "- No recent actions recorded."
    trust_lens = str(profile.get("trust_lens") or "")
    narrative_role = str(profile.get("narrative_role") or "")
    platform_behavior = str(profile.get("platform_behavior") or "")
    engagement_style = str(profile.get("engagement_style") or "")
    fallback = _fallback_interview_response(
        agent_name=agent_name,
        platform=platform,
        profile=profile,
        prompt=prompt,
        recent_actions=recent_actions,
    )
    try:
        llm = OpenAICompatibleLLM(settings)
        response_text = llm.generate(
            system_prompt=(
                "Answer in first person as the simulated persona. Be concrete, concise, and grounded in the recent runtime activity. "
                "Do not mention being an AI or a simulation."
            ),
            user_prompt=(
                f"Platform: {platform}\n"
                f"Persona name: {agent_name}\n"
                f"Role: {profile.get('profession')}\n"
                f"Bio: {profile.get('bio')}\n"
                f"Persona: {profile.get('persona')}\n"
                f"Trust lens: {trust_lens}\n"
                f"Narrative role: {narrative_role}\n"
                f"Platform behavior: {platform_behavior}\n"
                f"Engagement style: {engagement_style}\n"
                f"Recent runtime activity:\n{action_summary}\n\n"
                f"Question: {prompt}"
            ),
            temperature=0.3,
            max_tokens=320,
        )
    except LLMGenerationError:
        response_text = fallback
    cleaned_response = sanitize_short_model_text(response_text, fallback)
    if looks_like_prompt_echo(cleaned_response):
        cleaned_response = fallback
    if isinstance(cleaned_response, str) and ":" in cleaned_response:
        leading_label = cleaned_response.split(":", 1)[0].strip().lower()
        if leading_label in {
            "platform",
            "bio/context",
            "persona description",
            "recent runtime activity",
            "role",
            "bio",
            "question",
        }:
            cleaned_response = fallback
    if isinstance(cleaned_response, str) and _response_is_shallow(cleaned_response):
        cleaned_response = fallback
    result = read_latest_interview_response(context["db_path"], user_id=numeric_id)
    return {
        "platform": platform,
        "agent_id": external_id,
        "oasis_user_id": numeric_id,
        "agent_name": agent_name,
        "prompt": prompt,
        "response": cleaned_response or result.get("response") or fallback,
        "timestamp": _utc_now(),
    }


async def _handle_ipc_command(
    *,
    settings,
    simulation_id: str,
    command: dict[str, Any],
    contexts: dict[str, dict[str, Any]],
    numeric_to_external: dict[int, str],
    numeric_to_name: dict[int, str],
) -> bool:
    command_id = str(command.get("command_id") or "")
    command_type = str(command.get("command_type") or "")
    args = command.get("args") or {}
    responses_dir = ipc_responses_dir(settings, simulation_id)

    if command_type == "close_env":
        write_ipc_response(
            responses_dir,
            {
                "command_id": command_id,
                "status": "completed",
                "result": {"message": "Environment closing."},
                "timestamp": _utc_now(),
            },
        )
        if SHUTDOWN_EVENT is not None:
            SHUTDOWN_EVENT.set()
        return False

    if command_type == "interview":
        numeric_id = int(args.get("agent_id"))
        prompt = str(args.get("prompt") or "")
        platform = str(args.get("platform") or "")
        external_id = numeric_to_external.get(numeric_id, f"agent_{numeric_id:03d}")
        agent_name = numeric_to_name.get(numeric_id, external_id)
        profile = next(
            (
                item
                for item in load_simulation_profiles(settings, simulation_id, "reddit")
                if int(item.get("oasis_user_id", item.get("user_id", -1))) == numeric_id
            ),
            {},
        )
        if platform in {"twitter", "reddit"}:
            result = await _interview_single_platform(
                settings=settings,
                simulation_id=simulation_id,
                context=contexts[platform],
                platform=platform,
                numeric_id=numeric_id,
                external_id=external_id,
                agent_name=agent_name,
                prompt=prompt,
                profile=profile,
            )
        else:
            platform_results = await asyncio.gather(
                *[
                    _interview_single_platform(
                        settings=settings,
                        simulation_id=simulation_id,
                        context=context,
                        platform=name,
                        numeric_id=numeric_id,
                        external_id=external_id,
                        agent_name=agent_name,
                        prompt=prompt,
                        profile=profile,
                    )
                    for name, context in contexts.items()
                ]
            )
            result = {
                "agent_id": external_id,
                "oasis_user_id": numeric_id,
                "prompt": prompt,
                "platforms": {item["platform"]: item for item in platform_results},
            }
        write_ipc_response(
            responses_dir,
            {
                "command_id": command_id,
                "status": "completed",
                "result": result,
                "timestamp": _utc_now(),
            },
        )
        return True

    if command_type == "batch_interview":
        interviews = args.get("interviews") or []
        default_platform = str(args.get("platform") or "")
        results: list[dict[str, Any]] = []
        for item in interviews:
            numeric_id = int(item.get("agent_id"))
            prompt = str(item.get("prompt") or "")
            item_platform = str(item.get("platform") or default_platform or "")
            external_id = numeric_to_external.get(numeric_id, f"agent_{numeric_id:03d}")
            agent_name = numeric_to_name.get(numeric_id, external_id)
            profile = next(
                (
                    item
                    for item in load_simulation_profiles(settings, simulation_id, "reddit")
                    if int(item.get("oasis_user_id", item.get("user_id", -1))) == numeric_id
                ),
                {},
            )
            target_platforms = [item_platform] if item_platform in {"twitter", "reddit"} else list(contexts.keys())
            platform_results = await asyncio.gather(
                *[
                    _interview_single_platform(
                        settings=settings,
                        simulation_id=simulation_id,
                        context=contexts[name],
                        platform=name,
                        numeric_id=numeric_id,
                        external_id=external_id,
                        agent_name=agent_name,
                        prompt=prompt,
                        profile=profile,
                    )
                    for name in target_platforms
                ]
            )
            results.extend(platform_results)
        write_ipc_response(
            responses_dir,
            {
                "command_id": command_id,
                "status": "completed",
                "result": {"interview_results": results},
                "timestamp": _utc_now(),
            },
        )
        return True

    write_ipc_response(
        responses_dir,
        {
            "command_id": command_id,
            "status": "failed",
            "error": f"Unsupported command type: {command_type}",
            "timestamp": _utc_now(),
        },
    )
    return True


async def _run(args: argparse.Namespace) -> int:
    import oasis
    from oasis import LLMAction

    settings = get_settings()
    simulation_id = args.simulation_id
    config = load_simulation_config(settings, simulation_id)
    profiles = load_simulation_profiles(settings, simulation_id, "reddit")
    numeric_to_external, numeric_to_name, _ = build_agent_maps(profiles)

    _install_signal_handlers()
    sim_root = reddit_profiles_json_path(settings, simulation_id).parent
    ipc_commands_dir(settings, simulation_id).mkdir(parents=True, exist_ok=True)
    ipc_responses_dir(settings, simulation_id).mkdir(parents=True, exist_ok=True)
    _safe_write_json(simulation_actions_path(settings, simulation_id), [])
    _safe_write_json(simulation_posts_path(settings, simulation_id, "twitter"), [])
    _safe_write_json(simulation_posts_path(settings, simulation_id, "reddit"), [])
    _safe_write_json(simulation_comments_path(settings, simulation_id), [])
    _safe_write_json(simulation_interviews_path(settings, simulation_id), [])

    requested_platforms = ("twitter", "reddit") if args.platform == "parallel" else (args.platform,)
    graph_id = str(args.graph_id or "") or None
    total_hours = int(config.get("time_config", {}).get("total_simulation_hours", 12) or 12)
    minutes_per_round = int(config.get("time_config", {}).get("minutes_per_round", 10) or 10)
    total_rounds = max(1, int((total_hours * 60) / max(minutes_per_round, 1)))
    if args.max_rounds and args.max_rounds > 0:
        total_rounds = min(total_rounds, args.max_rounds)

    _set_state(
        settings,
        simulation_id,
        runtime_kind="oasis-worker",
        status="running",
        runner_status="starting",
        platform=args.platform,
        enable_graph_memory_update=bool(args.enable_graph_memory_update),
        current_round=0,
        total_rounds=total_rounds,
        progress_percent=0,
        minutes_per_round=minutes_per_round,
        total_simulation_hours=total_hours,
        simulated_hours=0,
        twitter_current_round=0,
        reddit_current_round=0,
        twitter_simulated_hours=0,
        reddit_simulated_hours=0,
        twitter_running="twitter" in requested_platforms,
        reddit_running="reddit" in requested_platforms,
        twitter_actions_count=0,
        reddit_actions_count=0,
        total_actions_count=0,
        twitter_completed=False,
        reddit_completed=False,
        started_at=_utc_now(),
        completed_at="",
        process_pid=os.getpid(),
        error="",
    )
    _set_env(
        settings,
        simulation_id,
        status="starting",
        twitter_available=False,
        reddit_available=False,
        closed_at="",
    )
    _log(settings, simulation_id, f"Starting native OASIS worker for {simulation_id} on {', '.join(requested_platforms)}")

    contexts: dict[str, dict[str, Any]] = {}
    try:
        for platform in requested_platforms:
            contexts[platform] = await _init_platform(settings=settings, simulation_id=simulation_id, platform=platform)
            contexts[platform]["numeric_to_external"] = numeric_to_external

        _set_env(
            settings,
            simulation_id,
            status="alive",
            twitter_available="twitter" in contexts,
            reddit_available="reddit" in contexts,
            closed_at="",
        )
        _set_state(settings, simulation_id, runner_status="running")

        all_actions = await _seed_initial_posts(
            contexts=contexts,
            config=config,
            simulation_id=simulation_id,
            settings=settings,
            numeric_to_name=numeric_to_name,
            preview_run=total_rounds <= 12,
        )
        fired_event_ids: set[str] = set()
        preview_run = total_rounds <= 12
        for round_number in range(1, total_rounds + 1):
            if SHUTDOWN_EVENT is not None and SHUTDOWN_EVENT.is_set():
                break

            simulated_hours = round((round_number * minutes_per_round) / 60, 2)
            current_hour = int(((round_number - 1) * minutes_per_round) / 60) % 24
            seeded_round_actions = await _seed_scheduled_events(
                contexts=contexts,
                config=config,
                simulation_id=simulation_id,
                settings=settings,
                numeric_to_name=numeric_to_name,
                round_number=round_number,
                simulated_hour=current_hour,
                fired_event_ids=fired_event_ids,
                preview_run=preview_run,
            )
            if seeded_round_actions:
                all_actions.extend(seeded_round_actions)
            platform_tasks: list[asyncio.Task[Any]] = []
            platform_state: dict[str, list[dict[str, Any]]] = {}
            for platform, context in contexts.items():
                agent_ids = choose_active_agent_ids(
                    config,
                    current_hour,
                    platform=platform,
                    preview_run=preview_run,
                    platform_count=len(contexts),
                )
                configured_cap = int(config.get("time_config", {}).get("agents_per_hour_max", 8) or 8)
                if preview_run:
                    per_platform_cap = max(6, min(10, configured_cap + 2))
                else:
                    per_platform_cap = max(8, min(16, configured_cap + 2))
                if not preview_run and len(profiles) > 48:
                    per_platform_cap = min(18, per_platform_cap + 2)
                if len(agent_ids) > per_platform_cap:
                    agent_ids = agent_ids[:per_platform_cap]
                actions = {}
                for numeric_id in agent_ids:
                    try:
                        agent = context["agent_graph"].get_agent(numeric_id)
                    except Exception:
                        continue
                    actions[agent] = LLMAction()
                platform_state[platform] = []
                from .services.oasis_runtime import _append_jsonl

                _append_jsonl(
                    platform_actions_jsonl_path(settings, simulation_id, platform),
                    {
                        "event_type": "round_start",
                        "round": round_number,
                        "simulated_hour": current_hour,
                        "timestamp": _utc_now(),
                    },
                )
                if actions:
                    platform_tasks.append(asyncio.create_task(context["env"].step(actions)))

            if platform_tasks:
                await asyncio.gather(*platform_tasks)

            for platform, context in contexts.items():
                round_actions, new_last_rowid = fetch_new_actions_from_db(
                    context["db_path"],
                    platform=platform,
                    last_rowid=context["last_rowid"],
                    numeric_to_external=numeric_to_external,
                    numeric_to_name=numeric_to_name,
                    round_num=round_number,
                )
                context["last_rowid"] = new_last_rowid
                platform_state[platform] = round_actions
                all_actions.extend(round_actions)
                from .services.oasis_runtime import _append_jsonl

                for action in round_actions:
                    _append_jsonl(platform_actions_jsonl_path(settings, simulation_id, platform), action)
                _append_jsonl(
                    platform_actions_jsonl_path(settings, simulation_id, platform),
                    {
                        "event_type": "round_end",
                        "round": round_number,
                        "actions_count": len(round_actions),
                        "timestamp": _utc_now(),
                    },
                )
                _safe_write_json(
                    simulation_posts_path(settings, simulation_id, platform),
                    load_posts_from_db(
                        context["db_path"],
                        platform=platform,
                        numeric_to_external=numeric_to_external,
                        numeric_to_name=numeric_to_name,
                    ),
                )
            if "reddit" in contexts:
                _safe_write_json(
                    simulation_comments_path(settings, simulation_id),
                    load_comments_from_db(
                        contexts["reddit"]["db_path"],
                        platform="reddit",
                        numeric_to_external=numeric_to_external,
                        numeric_to_name=numeric_to_name,
                    ),
                )
            _safe_write_json(simulation_actions_path(settings, simulation_id), all_actions)

            _set_state(
                settings,
                simulation_id,
                runner_status="running",
                current_round=round_number,
                progress_percent=round((round_number / total_rounds) * 100, 2),
                simulated_hours=simulated_hours,
                twitter_current_round=round_number if "twitter" in contexts else 0,
                reddit_current_round=round_number if "reddit" in contexts else 0,
                twitter_simulated_hours=simulated_hours if "twitter" in contexts else 0,
                reddit_simulated_hours=simulated_hours if "reddit" in contexts else 0,
                twitter_actions_count=len([item for item in all_actions if item.get("platform") == "twitter"]),
                reddit_actions_count=len([item for item in all_actions if item.get("platform") == "reddit"]),
                total_actions_count=len(all_actions),
            )
            if args.enable_graph_memory_update:
                round_actions = [item for items in platform_state.values() for item in items]
                _extend_graph(settings, graph_id, round_number, round_actions)

        stopped_early = SHUTDOWN_EVENT is not None and SHUTDOWN_EVENT.is_set()
        final_status = "stopped" if stopped_early else "completed"
        _set_state(
            settings,
            simulation_id,
            status=final_status,
            runner_status=final_status,
            twitter_running=False,
            reddit_running=False,
            twitter_completed=not stopped_early and "twitter" in contexts,
            reddit_completed=not stopped_early and "reddit" in contexts,
            progress_percent=100 if not stopped_early else load_simulation_state(settings, simulation_id).get("progress_percent", 0),
            completed_at=_utc_now(),
        )
        _set_env(
            settings,
            simulation_id,
            status="alive" if not stopped_early else "closed",
            twitter_available=not stopped_early and "twitter" in contexts,
            reddit_available=not stopped_early and "reddit" in contexts,
            closed_at="" if not stopped_early else _utc_now(),
        )
        _log(settings, simulation_id, f"Simulation loop finished with status={final_status}")

        if not stopped_early and not args.no_wait:
            while SHUTDOWN_EVENT is None or not SHUTDOWN_EVENT.is_set():
                command = poll_next_ipc_command(ipc_commands_dir(settings, simulation_id))
                if command is None:
                    await asyncio.sleep(0.25)
                    continue
                should_continue = await _handle_ipc_command(
                    settings=settings,
                    simulation_id=simulation_id,
                    command=command,
                    contexts=contexts,
                    numeric_to_external=numeric_to_external,
                    numeric_to_name=numeric_to_name,
                )
                if not should_continue:
                    break
    except Exception as exc:
        _set_state(
            settings,
            simulation_id,
            status="failed",
            runner_status="failed",
            twitter_running=False,
            reddit_running=False,
            error=f"{type(exc).__name__}: {exc}",
            completed_at=_utc_now(),
        )
        _set_env(
            settings,
            simulation_id,
            status="closed",
            twitter_available=False,
            reddit_available=False,
            closed_at=_utc_now(),
        )
        _log(settings, simulation_id, f"Simulation failed: {type(exc).__name__}: {exc}")
        _log(settings, simulation_id, traceback.format_exc())
        return 1
    finally:
        for platform, context in list(contexts.items()):
            try:
                await context["env"].close()
                _log(settings, simulation_id, f"[{platform}] environment closed")
            except Exception:
                pass
        _set_env(
            settings,
            simulation_id,
            status="closed",
            twitter_available=False,
            reddit_available=False,
            closed_at=_utc_now(),
        )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a clean-room OASIS simulation worker")
    parser.add_argument("--simulation-id", required=True)
    parser.add_argument("--platform", choices=["twitter", "reddit", "parallel"], default="parallel")
    parser.add_argument("--max-rounds", type=int, default=0)
    parser.add_argument("--graph-id", default="")
    parser.add_argument("--enable-graph-memory-update", action="store_true")
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args()

    global SHUTDOWN_EVENT
    SHUTDOWN_EVENT = asyncio.Event()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
