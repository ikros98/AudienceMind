"""Clean-room OASIS runtime helpers shared by the API and worker process."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import sqlite3
import time
from typing import Any
import uuid

from ..config import Settings
from .runtime import sanitize_runtime_payload, sanitize_runtime_text


IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
RUN_STATE_ALIAS = "run_state.json"
ENV_STATUS_ALIAS = "env_status.json"
SIMULATION_LOG_NAME = "simulation.log"

TRACE_ACTION_MAP = {
    "create_post": "CREATE_POST",
    "like_post": "LIKE_POST",
    "repost": "REPOST",
    "quote_post": "QUOTE_POST",
    "follow": "FOLLOW",
    "create_comment": "COMMENT",
    "like_comment": "LIKE_COMMENT",
    "dislike_post": "DISLIKE_POST",
    "dislike_comment": "DISLIKE_COMMENT",
    "search_posts": "SEARCH_POSTS",
    "search_user": "SEARCH_USER",
    "trend": "TREND",
    "refresh": "REFRESH",
    "mute": "MUTE",
    "do_nothing": "DO_NOTHING",
    "interview": "INTERVIEW",
}

IGNORED_TRACE_ACTIONS = {
    "sign_up",
    "update_rec_table",
    "exit",
}


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(sanitize_runtime_text(content), encoding="utf-8")
    temp_path.replace(path)


def _write_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(sanitize_runtime_payload(payload), indent=2, ensure_ascii=False))


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sanitize_runtime_payload(payload), ensure_ascii=False) + "\n")


def _append_text(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(sanitize_runtime_text(line))


def simulation_root(settings: Settings, simulation_id: str) -> Path:
    return Path(settings.data_dir).resolve() / "glass" / "simulations" / simulation_id


def reddit_profiles_json_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_root(settings, simulation_id) / "reddit_profiles.json"


def twitter_profiles_csv_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_root(settings, simulation_id) / "twitter_profiles.csv"


def simulation_log_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_root(settings, simulation_id) / SIMULATION_LOG_NAME


def platform_actions_jsonl_path(settings: Settings, simulation_id: str, platform: str) -> Path:
    return simulation_root(settings, simulation_id) / platform / "actions.jsonl"


def platform_db_path(settings: Settings, simulation_id: str, platform: str) -> Path:
    return simulation_root(settings, simulation_id) / f"{platform}_simulation.db"


def ipc_commands_dir(settings: Settings, simulation_id: str) -> Path:
    return simulation_root(settings, simulation_id) / IPC_COMMANDS_DIR


def ipc_responses_dir(settings: Settings, simulation_id: str) -> Path:
    return simulation_root(settings, simulation_id) / IPC_RESPONSES_DIR


def run_state_alias_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_root(settings, simulation_id) / RUN_STATE_ALIAS


def env_status_alias_path(settings: Settings, simulation_id: str) -> Path:
    return simulation_root(settings, simulation_id) / ENV_STATUS_ALIAS


def write_runtime_state(state_path: Path, alias_path: Path, payload: dict[str, Any]) -> None:
    _write_json(state_path, payload)
    _write_json(alias_path, payload)


def write_runtime_env(env_path: Path, alias_path: Path, payload: dict[str, Any]) -> None:
    _write_json(env_path, payload)
    _write_json(alias_path, payload)


def append_simulation_log(settings: Settings, simulation_id: str, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    _append_text(simulation_log_path(settings, simulation_id), f"[{timestamp}] {message}\n")


def write_oasis_profile_artifacts(
    settings: Settings,
    simulation_id: str,
    reddit_profiles: list[dict[str, Any]],
    twitter_profiles: list[dict[str, Any]],
) -> None:
    _write_json(reddit_profiles_json_path(settings, simulation_id), reddit_profiles)
    csv_path = twitter_profiles_csv_path(settings, simulation_id)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["user_id", "name", "username", "user_char", "description"],
        )
        writer.writeheader()
        for profile in twitter_profiles:
            writer.writerow(
                {
                    "user_id": int(profile.get("user_id", 0)),
                    "name": sanitize_runtime_text(str(profile.get("name") or "")).strip(),
                    "username": sanitize_runtime_text(str(profile.get("username") or "")).strip(),
                    "user_char": sanitize_runtime_text(str(profile.get("persona") or "")).strip(),
                    "description": sanitize_runtime_text(str(profile.get("bio") or "")).strip(),
                }
            )


def build_agent_maps(
    profiles: list[dict[str, Any]],
) -> tuple[dict[int, str], dict[int, str], dict[str, int]]:
    numeric_to_external: dict[int, str] = {}
    numeric_to_name: dict[int, str] = {}
    external_to_numeric: dict[str, int] = {}
    for index, profile in enumerate(profiles):
        numeric_id = int(profile.get("oasis_user_id", profile.get("user_id", index)))
        external_id = str(profile.get("agent_id") or f"agent_{numeric_id:03d}")
        numeric_to_external[numeric_id] = external_id
        numeric_to_name[numeric_id] = str(profile.get("name") or external_id)
        external_to_numeric[external_id] = numeric_id
    return numeric_to_external, numeric_to_name, external_to_numeric


def build_camel_model(settings: Settings):
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType

    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=settings.llm_model,
        api_key=settings.llm_api_key,
        url=settings.llm_base_url,
        timeout=settings.graphiti_timeout_seconds,
    )


def choose_active_agent_ids(
    config: dict[str, Any],
    current_hour: int,
    *,
    platform: str | None = None,
    preview_run: bool = False,
    platform_count: int = 1,
) -> list[int]:
    time_config = config.get("time_config", {})
    agent_configs = config.get("agent_configs", [])

    base_min = int(time_config.get("agents_per_hour_min", 4) or 4)
    base_max = int(time_config.get("agents_per_hour_max", 12) or 12)
    peak_hours = {int(item) for item in time_config.get("peak_hours", []) if isinstance(item, int)}
    morning_hours = {int(item) for item in time_config.get("morning_hours", []) if isinstance(item, int)}
    work_hours = {int(item) for item in time_config.get("work_hours", []) if isinstance(item, int)}
    off_peak_hours = {int(item) for item in time_config.get("off_peak_hours", []) if isinstance(item, int)}

    multiplier = 1.0
    if current_hour in peak_hours:
        multiplier = float(time_config.get("peak_activity_multiplier", 1.4) or 1.4)
    elif current_hour in morning_hours:
        multiplier = float(time_config.get("morning_activity_multiplier", 0.8) or 0.8)
    elif current_hour in work_hours:
        multiplier = float(time_config.get("work_activity_multiplier", 1.1) or 1.1)
    elif current_hour in off_peak_hours:
        multiplier = float(time_config.get("off_peak_activity_multiplier", 0.35) or 0.35)

    target_count = int(round(random.uniform(base_min, max(base_max, base_min)) * multiplier))
    if preview_run:
        target_count = int(round(target_count * 1.0))
    platform_mix = time_config.get("platform_mix", {})
    if platform in {"twitter", "reddit"} and isinstance(platform_mix, dict):
        mix = platform_mix.get(platform)
        if isinstance(mix, (int, float)):
            if preview_run and platform_count > 1:
                mix_scale = 1.0
            else:
                mix_scale = max(0.2 if preview_run else 0.25, min(0.9, float(mix)))
            if platform_count > 1:
                target_count = int(round(target_count * mix_scale))
    if preview_run and platform_count > 1:
        target_count = max(0, target_count)
    if target_count <= 0:
        return []

    weighted_candidates: list[tuple[int, float]] = []
    for item in agent_configs:
        try:
            agent_id = int(item.get("agent_id"))
        except Exception:
            continue
        active_hours = item.get("active_hours") or list(range(8, 23))
        if current_hour not in active_hours:
            continue
        activity_level = float(item.get("activity_level", 0.5) or 0.5)
        posts_per_hour = float(item.get("posts_per_hour", 0.0) or 0.0)
        comments_per_hour = float(item.get("comments_per_hour", 0.0) or 0.0)
        preferred_platform = str(item.get("preferred_platform") or "")
        cross_platform_affinity = float(item.get("cross_platform_affinity", 0.55) or 0.55)
        platform_bias = 1.0
        if platform in {"twitter", "reddit"} and preferred_platform:
            platform_bias = 1.0 if preferred_platform == platform else cross_platform_affinity
        influence_weight = float(item.get("influence_weight", 1.0) or 1.0)
        engagement_bias = min(1.35, 0.35 + (posts_per_hour * 0.22) + (comments_per_hour * 0.09))
        selection_weight = activity_level * platform_bias * engagement_bias * max(0.75, min(influence_weight / 1.8, 1.4))
        if selection_weight <= 0.015:
            continue
        weighted_candidates.append((agent_id, selection_weight))
    if not weighted_candidates:
        return []
    if len(weighted_candidates) <= target_count:
        return [agent_id for agent_id, _ in weighted_candidates]

    selected: list[int] = []
    pool = list(weighted_candidates)
    while pool and len(selected) < target_count:
        total_weight = sum(weight for _, weight in pool)
        if total_weight <= 0:
            break
        threshold = random.random() * total_weight
        cumulative = 0.0
        chosen_index = 0
        for index, (_agent_id, weight) in enumerate(pool):
            cumulative += weight
            if cumulative >= threshold:
                chosen_index = index
                break
        agent_id, _weight = pool.pop(chosen_index)
        selected.append(agent_id)
    return selected


def _query_one(cursor: sqlite3.Cursor, query: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
    try:
        cursor.execute(query, params)
        return cursor.fetchone()
    except Exception:
        return None


def _load_user_name(cursor: sqlite3.Cursor, user_id: int, numeric_to_name: dict[int, str]) -> str:
    row = _query_one(cursor, "SELECT agent_id, name, user_name FROM user WHERE user_id = ?", (user_id,))
    if row:
        agent_id = row[0]
        if agent_id in numeric_to_name:
            return numeric_to_name[int(agent_id)]
        return str(row[1] or row[2] or f"Agent {user_id}")
    return numeric_to_name.get(user_id, f"Agent {user_id}")


def _load_post_context(cursor: sqlite3.Cursor, post_id: int, numeric_to_name: dict[int, str]) -> dict[str, Any]:
    row = _query_one(
        cursor,
        """
        SELECT p.content, p.quote_content, p.original_post_id, p.user_id, u.agent_id, p.created_at
        FROM post p
        LEFT JOIN user u ON p.user_id = u.user_id
        WHERE p.post_id = ?
        """,
        (post_id,),
    )
    if not row:
        return {}
    content, quote_content, original_post_id, user_id, agent_id, created_at = row
    author_name = numeric_to_name.get(int(agent_id), _load_user_name(cursor, int(user_id), numeric_to_name))
    payload = {
        "post_content": str(content or ""),
        "quote_content": str(quote_content or ""),
        "post_author_name": author_name,
        "created_at": created_at,
    }
    if original_post_id:
        original = _load_post_context(cursor, int(original_post_id), numeric_to_name)
        if original:
            payload["original_content"] = original.get("post_content", "")
            payload["original_author_name"] = original.get("post_author_name", "")
    return payload


def _load_comment_context(cursor: sqlite3.Cursor, comment_id: int, numeric_to_name: dict[int, str]) -> dict[str, Any]:
    row = _query_one(
        cursor,
        """
        SELECT c.content, c.user_id, u.agent_id, c.post_id, c.created_at
        FROM comment c
        LEFT JOIN user u ON c.user_id = u.user_id
        WHERE c.comment_id = ?
        """,
        (comment_id,),
    )
    if not row:
        return {}
    content, user_id, agent_id, post_id, created_at = row
    return {
        "comment_content": str(content or ""),
        "comment_author_name": numeric_to_name.get(int(agent_id), _load_user_name(cursor, int(user_id), numeric_to_name)),
        "post_id": post_id,
        "created_at": created_at,
    }


def _enrich_action_args(
    cursor: sqlite3.Cursor,
    action_type: str,
    action_args: dict[str, Any],
    numeric_to_name: dict[int, str],
) -> dict[str, Any]:
    enriched = dict(action_args)
    if "post_id" in enriched:
        enriched.update(_load_post_context(cursor, int(enriched["post_id"]), numeric_to_name))
    if "quoted_id" in enriched:
        enriched.update(_load_post_context(cursor, int(enriched["quoted_id"]), numeric_to_name))
    if "comment_id" in enriched:
        enriched.update(_load_comment_context(cursor, int(enriched["comment_id"]), numeric_to_name))
    if "follow_id" in enriched:
        follow_row = _query_one(cursor, "SELECT followee_id FROM follow WHERE follow_id = ?", (int(enriched["follow_id"]),))
        if follow_row:
            enriched["target_user_name"] = _load_user_name(cursor, int(follow_row[0]), numeric_to_name)
    return enriched


def fetch_new_actions_from_db(
    db_path: Path,
    *,
    platform: str,
    last_rowid: int,
    numeric_to_external: dict[int, str],
    numeric_to_name: dict[int, str],
    round_num: int,
) -> tuple[list[dict[str, Any]], int]:
    actions: list[dict[str, Any]] = []
    new_last_rowid = last_rowid
    if not db_path.exists():
        return actions, new_last_rowid
    connection = sqlite3.connect(str(db_path))
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT rowid, user_id, created_at, action, info
            FROM trace
            WHERE rowid > ?
            ORDER BY rowid ASC
            """,
            (last_rowid,),
        )
        for rowid, user_id, created_at, action, info_json in cursor.fetchall():
            new_last_rowid = int(rowid)
            action_name = str(action or "")
            if action_name in IGNORED_TRACE_ACTIONS:
                continue
            parsed_args = {}
            if info_json:
                try:
                    parsed_args = json.loads(info_json)
                except Exception:
                    parsed_args = {"raw": str(info_json)}
            normalized_type = TRACE_ACTION_MAP.get(action_name, action_name.upper())
            enriched_args = _enrich_action_args(cursor, normalized_type, parsed_args, numeric_to_name)
            external_id = numeric_to_external.get(int(user_id), f"agent_{int(user_id):03d}")
            content = None
            for key in ("content", "quote_content", "comment_content", "post_content", "original_content"):
                value = enriched_args.get(key)
                if isinstance(value, str) and value.strip():
                    content = value.strip()
                    break
            actions.append(
                {
                    "timestamp": str(created_at or datetime.now(timezone.utc).isoformat()),
                    "platform": platform,
                    "round_num": round_num,
                    "agent_id": external_id,
                    "oasis_user_id": int(user_id),
                    "agent_name": numeric_to_name.get(int(user_id), external_id),
                    "action_type": normalized_type,
                    "action_args": enriched_args,
                    "content": content,
                }
            )
    finally:
        connection.close()
    return actions, new_last_rowid


def load_posts_from_db(
    db_path: Path,
    *,
    platform: str,
    numeric_to_external: dict[int, str],
    numeric_to_name: dict[int, str],
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    connection = sqlite3.connect(str(db_path))
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT p.post_id, p.user_id, p.content, p.quote_content, p.created_at, p.num_likes, p.num_dislikes, u.agent_id
            FROM post p
            LEFT JOIN user u ON p.user_id = u.user_id
            ORDER BY p.post_id ASC
            """
        )
        posts: list[dict[str, Any]] = []
        for post_id, user_id, content, quote_content, created_at, num_likes, num_dislikes, agent_id in cursor.fetchall():
            numeric_id = int(agent_id) if agent_id is not None else int(user_id)
            posts.append(
                {
                    "post_id": f"{platform}_post_{int(post_id)}",
                    "platform": platform,
                    "agent_id": numeric_to_external.get(numeric_id, f"agent_{numeric_id:03d}"),
                    "oasis_user_id": numeric_id,
                    "agent_name": numeric_to_name.get(numeric_id, f"Agent {numeric_id}"),
                    "title": f"{platform.title()} thread {int(post_id)}",
                    "content": str(quote_content or content or ""),
                    "score": int((num_likes or 0) - (num_dislikes or 0)),
                    "created_at": str(created_at or ""),
                }
            )
        return posts
    finally:
        connection.close()


def load_comments_from_db(
    db_path: Path,
    *,
    platform: str,
    numeric_to_external: dict[int, str],
    numeric_to_name: dict[int, str],
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    connection = sqlite3.connect(str(db_path))
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT c.comment_id, c.post_id, c.user_id, c.content, c.created_at, c.num_likes, c.num_dislikes, u.agent_id
            FROM comment c
            LEFT JOIN user u ON c.user_id = u.user_id
            ORDER BY c.comment_id ASC
            """
        )
        comments: list[dict[str, Any]] = []
        for comment_id, post_id, user_id, content, created_at, num_likes, num_dislikes, agent_id in cursor.fetchall():
            numeric_id = int(agent_id) if agent_id is not None else int(user_id)
            comments.append(
                {
                    "comment_id": f"{platform}_comment_{int(comment_id)}",
                    "platform": platform,
                    "post_id": f"{platform}_post_{int(post_id)}",
                    "agent_id": numeric_to_external.get(numeric_id, f"agent_{numeric_id:03d}"),
                    "oasis_user_id": numeric_id,
                    "agent_name": numeric_to_name.get(numeric_id, f"Agent {numeric_id}"),
                    "content": str(content or ""),
                    "score": int((num_likes or 0) - (num_dislikes or 0)),
                    "created_at": str(created_at or ""),
                }
            )
        return comments
    finally:
        connection.close()


def read_latest_interview_response(db_path: Path, *, user_id: int) -> dict[str, Any]:
    result = {"agent_id": user_id, "response": None, "timestamp": None}
    if not db_path.exists():
        return result
    connection = sqlite3.connect(str(db_path))
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT info, created_at
            FROM trace
            WHERE action = ? AND user_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            ("interview", user_id),
        )
        row = cursor.fetchone()
        if row:
            info_json, created_at = row
            result["timestamp"] = created_at
            try:
                payload = json.loads(info_json) if info_json else {}
            except Exception:
                payload = {"response": str(info_json)}
            result["response"] = payload.get("response", payload)
    finally:
        connection.close()
    return result


def send_ipc_command(
    settings: Settings,
    simulation_id: str,
    *,
    command_type: str,
    args: dict[str, Any],
    timeout_seconds: float = 60.0,
    poll_interval_seconds: float = 0.25,
) -> dict[str, Any]:
    command_id = str(uuid.uuid4())
    command_payload = {
        "command_id": command_id,
        "command_type": command_type,
        "args": args,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    commands_dir = ipc_commands_dir(settings, simulation_id)
    responses_dir = ipc_responses_dir(settings, simulation_id)
    commands_dir.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)
    command_path = commands_dir / f"{command_id}.json"
    response_path = responses_dir / f"{command_id}.json"
    _write_json(command_path, command_payload)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if response_path.exists():
            response = _read_json(response_path, {})
            command_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)
            return response if isinstance(response, dict) else {}
        time.sleep(poll_interval_seconds)
    command_path.unlink(missing_ok=True)
    raise TimeoutError(f"Timed out waiting for IPC response {command_id}")


def poll_next_ipc_command(commands_dir: Path) -> dict[str, Any] | None:
    for path in sorted(commands_dir.glob("*.json")):
        payload = _read_json(path, None)
        path.unlink(missing_ok=True)
        if isinstance(payload, dict):
            return payload
    return None


def write_ipc_response(responses_dir: Path, payload: dict[str, Any]) -> None:
    command_id = str(payload.get("command_id") or uuid.uuid4())
    _write_json(responses_dir / f"{command_id}.json", payload)
