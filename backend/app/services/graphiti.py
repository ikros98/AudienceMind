"""Native Graphiti HTTP helpers for clean-room graph materialization."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import re
import time
from typing import Any, Callable

import httpx

from ..config import Settings


GraphitiProgressCallback = Callable[[str, float], None]
_GENERIC_NODE_LABELS = {"Entity", "Node"}
_BROAD_FALLBACK_LABELS = _GENERIC_NODE_LABELS | {"Organization"}
_KNOWN_LOCATION_NAMES = {
    "beijing",
    "california",
    "china",
    "france",
    "italy",
    "japan",
    "london",
    "los angeles",
    "new york",
    "paris",
    "seoul",
    "shanghai",
    "south korea",
    "tokyo",
    "uk",
    "u.k.",
    "united kingdom",
    "us",
    "u.s.",
    "usa",
}
_LOCATION_HINTS = {"city", "country", "region", "geography", "province", "territory"}
_PLATFORM_OR_ORG_NAMES = {
    "good on you",
    "instagram",
    "pinterest",
    "reddit",
    "tiktok",
    "twitter",
    "wechat",
    "youtube",
    "nyse",
}
_ORGANIZATION_HINTS = {
    "commerce",
    "company",
    "corporation",
    "design",
    "group",
    "holdings",
    "index",
    "mini-program",
    "mini program",
    "office",
    "operator",
    "partner",
    "platform",
    "restaurant",
    "retail",
    "social commerce",
    "store",
}


def graphiti_safe_identifier(value: str) -> str:
    """Convert a human label into a Graphiti-safe identifier."""
    candidate = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    candidate = re.sub(r"_+", "_", candidate).strip("_")
    if not candidate:
        return "Entity"
    if not re.match(r"^[A-Za-z_]", candidate):
        candidate = f"_{candidate}"
    return candidate


def display_graph_label(value: str) -> str:
    """Convert a Graphiti-safe identifier back to a readable label."""
    if value in _GENERIC_NODE_LABELS:
        return value
    return value.replace("_", " ")


def split_text_chunks(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Split source text into moderately sized chunks with simple boundary awareness."""
    if not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text.strip()]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            window = text[start:end]
            for separator in ("\n\n", ". ", "! ", "? ", ".\n", "!\n", "?\n"):
                boundary = window.rfind(separator)
                if boundary != -1 and boundary > int(chunk_size * 0.3):
                    end = start + boundary + len(separator)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break
        start = max(end - overlap, start + 1)

    return chunks


def preferred_graph_label(labels: list[str] | None) -> str:
    """Choose the most informative label from a Graphiti node."""
    ordered = [str(label).strip() for label in (labels or []) if str(label).strip()]
    for label in ordered:
        if label not in _GENERIC_NODE_LABELS:
            return display_graph_label(label)
    if ordered:
        return display_graph_label(ordered[0])
    return "Entity"


def infer_generic_graph_label(
    *,
    current_label: str,
    name: str,
    summary: str,
    attributes: dict[str, Any] | None = None,
) -> str | None:
    """Recover a concrete label for broad fallback nodes when the node name is obviously geographic."""
    if current_label not in _BROAD_FALLBACK_LABELS:
        return None
    lowered_name = " ".join(str(name or "").strip().lower().split())
    lowered_summary = str(summary or "").strip().lower()
    attribute_text = " ".join(f"{key} {value}" for key, value in (attributes or {}).items()).lower()
    hint_text = " ".join(part for part in (lowered_summary, attribute_text) if part).strip()

    if lowered_name in _KNOWN_LOCATION_NAMES:
        return "Location"
    if any(token in lowered_name for token in {" city", " province", " county", " region"}) or lowered_name.endswith(
        (" city", " province", " county", " region")
    ):
        return "Location"
    if lowered_name in _PLATFORM_OR_ORG_NAMES:
        return "Organization"
    if any(token in lowered_name for token in _ORGANIZATION_HINTS) or any(
        token in hint_text for token in _ORGANIZATION_HINTS
    ):
        return "Organization"
    if any(token in hint_text for token in _LOCATION_HINTS):
        return "Location"
    if current_label == "Organization":
        return "Organization"
    return None


def normalize_graphiti_payload(raw_payload: dict[str, Any], graph_id: str) -> dict[str, Any]:
    """Normalize Graphiti graph data into the payload expected by the glass client."""
    raw_nodes = raw_payload.get("nodes", [])
    raw_edges = raw_payload.get("edges", [])

    nodes: list[dict[str, Any]] = []
    for item in raw_nodes:
        if not isinstance(item, dict):
            continue
        labels = [display_graph_label(str(label)) for label in (item.get("labels") or []) if str(label).strip()]
        resolved_label = preferred_graph_label(labels)
        inferred_label = infer_generic_graph_label(
            current_label=resolved_label,
            name=str(item.get("name") or ""),
            summary=str(item.get("summary") or ""),
            attributes=item.get("attributes") or {},
        )
        if inferred_label:
            labels = [inferred_label]
            resolved_label = inferred_label
        nodes.append(
            {
                "uuid": str(item.get("uuid") or ""),
                "name": str(item.get("name") or "Unnamed Entity"),
                "label": resolved_label,
                "labels": labels,
                "summary": str(item.get("summary") or ""),
                "attributes": item.get("attributes") or {},
                "created_at": item.get("created_at"),
            }
        )

    edges: list[dict[str, Any]] = []
    for item in raw_edges:
        if not isinstance(item, dict):
            continue
        relation_type = str(item.get("name") or item.get("relation_type") or "related_to").strip() or "related_to"
        edges.append(
            {
                "uuid": str(item.get("uuid") or ""),
                "name": relation_type,
                "relation_type": relation_type,
                "fact": str(item.get("fact") or ""),
                "source_uuid": str(item.get("source_node_uuid") or item.get("source_uuid") or ""),
                "target_uuid": str(item.get("target_node_uuid") or item.get("target_uuid") or ""),
                "source_name": item.get("source_node_name"),
                "target_name": item.get("target_node_name"),
                "attributes": item.get("attributes") or {},
                "created_at": item.get("created_at"),
                "valid_at": item.get("valid_at"),
                "invalid_at": item.get("invalid_at"),
                "expired_at": item.get("expired_at"),
            }
        )

    entity_types = sorted({node["label"] for node in nodes if node.get("label") not in _GENERIC_NODE_LABELS})
    edge_types = sorted({edge["relation_type"] for edge in edges if edge.get("relation_type")})

    return {
        "graph_id": graph_id,
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "graph_id": graph_id,
            "node_count": int(raw_payload.get("node_count") or len(nodes)),
            "edge_count": int(raw_payload.get("edge_count") or len(edges)),
            "entity_types": entity_types,
            "edge_types": edge_types,
        },
    }


def sanitize_graphiti_ontology(ontology: dict[str, Any]) -> dict[str, Any]:
    """Normalize ontology names into identifiers accepted by Graphiti."""
    sanitized = dict(ontology)
    entity_types = []
    label_map: dict[str, str] = {}

    for item in ontology.get("entity_types", []):
        if not isinstance(item, dict):
            continue
        original_name = str(item.get("name") or "").strip()
        safe_name = graphiti_safe_identifier(original_name)
        label_map[original_name] = safe_name
        entity_types.append({**item, "name": safe_name})

    edge_types = []
    for item in ontology.get("edge_types", []):
        if not isinstance(item, dict):
            continue
        source_targets = []
        for relation in item.get("source_targets", []):
            if not isinstance(relation, dict):
                continue
            source_targets.append(
                {
                    "source": label_map.get(str(relation.get("source") or ""), graphiti_safe_identifier(str(relation.get("source") or ""))),
                    "target": label_map.get(str(relation.get("target") or ""), graphiti_safe_identifier(str(relation.get("target") or ""))),
                }
            )
        edge_types.append(
            {
                **item,
                "name": graphiti_safe_identifier(str(item.get("name") or "")),
                "source_targets": source_targets,
            }
        )

    sanitized["entity_types"] = entity_types
    sanitized["edge_types"] = edge_types
    return sanitized


@dataclass
class GraphitiClient:
    """Small sync Graphiti client for clean-room graph ingestion."""

    settings: Settings

    def __post_init__(self) -> None:
        base_url = self.settings.graphiti_base_url.rstrip("/")
        if not base_url:
            raise RuntimeError("Graphiti base URL is not configured.")

        headers: dict[str, str] = {}
        if self.settings.graphiti_api_key:
            headers["Authorization"] = f"Bearer {self.settings.graphiti_api_key}"

        self._client = httpx.Client(
            base_url=base_url,
            timeout=self.settings.graphiti_timeout_seconds,
            headers=headers,
        )
        self._connect_retry_attempts = 4
        self._connect_retry_delay_seconds = 1.0
        self._batch_heartbeat_seconds = 15.0

    def close(self) -> None:
        """Release the underlying HTTP client."""
        self._client.close()

    def delete_graph(self, graph_id: str, *, ignore_missing: bool = True) -> None:
        """Delete a graph if it already exists."""
        try:
            self._request("DELETE", f"/graphs/{graph_id}")
        except httpx.HTTPStatusError as exc:
            if ignore_missing and exc.response.status_code == 404:
                return
            raise

    def create_graph(self, *, graph_id: str, name: str, description: str) -> str:
        """Create a Graphiti graph namespace."""
        data = self._request(
            "POST",
            "/graphs",
            json={
                "graph_id": graph_id,
                "name": name,
                "description": description,
            },
        )
        return str(data.get("graph_id") or graph_id)

    def set_ontology(self, graph_id: str, ontology: dict[str, Any]) -> None:
        """Register the ontology for a graph."""
        self._request("PUT", f"/graphs/{graph_id}/ontology", json={"ontology": ontology})

    def _request_with_heartbeat(
        self,
        method: str,
        path: str,
        *,
        progress_callback: GraphitiProgressCallback | None,
        progress_fraction: float,
        heartbeat_message: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Keep graph-build tasks visibly alive while a slow Graphiti request is still running."""
        if progress_callback is None:
            return self._request(method, path, **kwargs)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._request, method, path, **kwargs)
            started_at = time.monotonic()
            while True:
                try:
                    return future.result(timeout=self._batch_heartbeat_seconds)
                except FutureTimeoutError:
                    elapsed_seconds = int(time.monotonic() - started_at)
                    progress_callback(
                        f"{heartbeat_message} Graphiti is still processing ({elapsed_seconds}s elapsed).",
                        progress_fraction,
                    )

    def ingest_episodes(
        self,
        graph_id: str,
        episodes: list[dict[str, Any]],
        *,
        batch_size: int = 1,
        custom_extraction_instructions: str | None = None,
        progress_callback: GraphitiProgressCallback | None = None,
    ) -> None:
        """Send document episodes to Graphiti in small batches."""
        total = len(episodes)
        if total == 0:
            return

        processed = 0
        total_batches = (total + max(batch_size, 1) - 1) // max(batch_size, 1)
        for batch_index in range(0, total, max(batch_size, 1)):
            batch = episodes[batch_index:batch_index + max(batch_size, 1)]
            batch_number = batch_index // max(batch_size, 1) + 1
            if progress_callback:
                progress_callback(
                    f"Sending Graphiti batch {batch_number}/{total_batches}.",
                    processed / total if total else 1.0,
                )
            payload: dict[str, Any] = {"episodes": batch, "update_communities": False}
            if custom_extraction_instructions:
                payload["custom_extraction_instructions"] = custom_extraction_instructions
            response = self._ingest_batch_with_retry(
                graph_id,
                payload=payload,
                batch=batch,
                batch_number=batch_number,
                total_batches=total_batches,
                progress_callback=progress_callback,
                progress_fraction=processed / total if total else 1.0,
            )
            processed += int(response.get("ingested_count") or len(batch))

        if progress_callback:
            progress_callback("Fetching materialized Graphiti graph.", 1.0)

    def _ingest_batch_with_retry(
        self,
        graph_id: str,
        *,
        payload: dict[str, Any],
        batch: list[dict[str, Any]],
        batch_number: int,
        total_batches: int,
        progress_callback: GraphitiProgressCallback | None,
        progress_fraction: float,
        split_depth: int = 0,
        max_split_depth: int = 2,
    ) -> dict[str, Any]:
        """Retry a slow Graphiti episode ingestion by splitting oversized episodes into smaller chunks."""
        try:
            heartbeat_message = (
                f"Sending Graphiti batch {batch_number}/{total_batches}."
                if split_depth == 0
                else f"Retrying Graphiti sub-chunk for batch {batch_number}/{total_batches}."
            )
            return self._request_with_heartbeat(
                "POST",
                f"/graphs/{graph_id}/episodes",
                json=payload,
                progress_callback=progress_callback,
                progress_fraction=progress_fraction,
                heartbeat_message=heartbeat_message,
            )
        except Exception as exc:
            if split_depth >= max_split_depth or not self._is_timeout_like_error(exc):
                raise

            split_batch: list[dict[str, Any]] = []
            for episode in batch:
                split_episodes = self._split_episode_for_retry(episode)
                if not split_episodes:
                    split_batch = []
                    break
                split_batch.extend(split_episodes)

            if not split_batch:
                raise

            if progress_callback:
                progress_callback(
                    (
                        f"Graphiti batch {batch_number}/{total_batches} timed out; "
                        f"retrying as {len(split_batch)} smaller chunks."
                    ),
                    progress_fraction,
                )

            ingested_count = 0
            for sub_index, split_episode in enumerate(split_batch, start=1):
                if progress_callback:
                    progress_callback(
                        (
                            f"Retrying Graphiti sub-chunk {sub_index}/{len(split_batch)} "
                            f"for batch {batch_number}/{total_batches}."
                        ),
                        progress_fraction,
                    )
                result = self._ingest_batch_with_retry(
                    graph_id,
                    payload={
                        "episodes": [split_episode],
                        "update_communities": False,
                        **(
                            {"custom_extraction_instructions": payload["custom_extraction_instructions"]}
                            if payload.get("custom_extraction_instructions")
                            else {}
                        ),
                    },
                    batch=[split_episode],
                    batch_number=batch_number,
                    total_batches=total_batches,
                    progress_callback=progress_callback,
                    progress_fraction=progress_fraction,
                    split_depth=split_depth + 1,
                    max_split_depth=max_split_depth,
                )
                ingested_count += int(result.get("ingested_count") or 1)
            return {"ingested_count": ingested_count}

    def _is_timeout_like_error(self, exc: Exception) -> bool:
        """Return True when an ingestion failure looks like a timeout and should be retried with smaller chunks."""
        if isinstance(exc, httpx.TimeoutException):
            return True
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {408, 504, 524}:
            return True
        message = str(exc).lower()
        return "timed out" in message or "timeout" in message

    def _split_episode_for_retry(self, episode: dict[str, Any]) -> list[dict[str, Any]]:
        """Split an oversized episode body into smaller retries when Graphiti times out."""
        body = str(episode.get("episode_body") or "").strip()
        if len(body) < 500:
            return []

        chunk_size = max(280, min(700, len(body) // 2))
        overlap = min(80, max(40, chunk_size // 8))
        chunks = split_text_chunks(body, chunk_size=chunk_size, overlap=overlap)
        if len(chunks) <= 1:
            return []

        base_name = str(episode.get("name") or "episode")
        split_episodes: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks, start=1):
            split_episodes.append(
                {
                    **episode,
                    "name": f"{base_name}-part-{index}",
                    "episode_body": chunk,
                }
            )
        return split_episodes

    def get_graph_payload(self, graph_id: str) -> dict[str, Any]:
        """Fetch and normalize a graph payload from Graphiti."""
        payload = self._request("GET", f"/graphs/{graph_id}")
        raw_nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
        raw_edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
        node_count = int(payload.get("node_count") or len(raw_nodes))
        edge_count = int(payload.get("edge_count") or len(raw_edges))
        if len(raw_nodes) < node_count:
            payload["nodes"] = self._paginate(f"/graphs/{graph_id}/nodes", item_key="items")
        if len(raw_edges) < edge_count:
            payload["edges"] = self._paginate(f"/graphs/{graph_id}/edges", item_key="items")
        return normalize_graphiti_payload(payload, graph_id)

    def wait_for_graph_settle(
        self,
        graph_id: str,
        *,
        progress_callback: GraphitiProgressCallback | None = None,
        timeout_seconds: float = 240.0,
        poll_interval_seconds: float = 10.0,
        min_wait_seconds: float = 60.0,
        stable_polls_required: int = 4,
        require_non_empty: bool = True,
    ) -> dict[str, Any]:
        """Poll Graphiti until node and edge counts stop changing for a short window."""
        deadline = time.monotonic() + max(timeout_seconds, poll_interval_seconds)
        first_poll_at = time.monotonic()
        last_counts: tuple[int, int] | None = None
        stable_polls = 0

        while True:
            payload = self._request("GET", f"/graphs/{graph_id}")
            node_count = int(payload.get("node_count") or 0)
            edge_count = int(payload.get("edge_count") or 0)
            elapsed = time.monotonic() - first_poll_at
            if progress_callback is not None:
                progress_callback(
                    f"Waiting for Graphiti graph to settle ({node_count} nodes / {edge_count} edges).",
                    min(elapsed / max(timeout_seconds, 1.0), 1.0),
                )

            current_counts = (node_count, edge_count)
            if current_counts == last_counts and sum(current_counts) > 0:
                stable_polls += 1
            else:
                stable_polls = 0
            last_counts = current_counts

            if elapsed >= min_wait_seconds and stable_polls >= stable_polls_required:
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(poll_interval_seconds)

        payload = self.get_graph_payload(graph_id)
        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        node_count = int(metadata.get("node_count") or 0)
        edge_count = int(metadata.get("edge_count") or 0)
        if require_non_empty and node_count <= 0 and edge_count <= 0:
            raise RuntimeError(
                "Graphiti returned an empty graph after ingesting episodes. "
                "Treating this as a failed build instead of a completed graph."
            )
        return payload

    def _paginate(self, path: str, *, item_key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            page = self._request("GET", path, params=params)
            batch = page.get(item_key) or page.get("nodes") or page.get("edges") or []
            if isinstance(batch, list):
                items.extend(item for item in batch if isinstance(item, dict))
            cursor = page.get("next_cursor")
            if not cursor:
                break
        return items

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self._connect_retry_attempts):
            try:
                response = self._client.request(method, path, **kwargs)
                response.raise_for_status()
                if not response.content:
                    return {}

                payload = response.json()
                if isinstance(payload, dict) and payload.get("success") is False:
                    raise RuntimeError(payload.get("error") or payload.get("message") or "Graphiti request failed")
                if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                    return payload["data"]
                if isinstance(payload, dict):
                    return payload
                raise RuntimeError(f"Unexpected Graphiti response shape for {method} {path}")
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status_code = exc.response.status_code
                if status_code in {429, 502, 503} and attempt < self._connect_retry_attempts - 1:
                    time.sleep(self._connect_retry_delay_seconds * (attempt + 1) * 2)
                    continue
                raise
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_exc = exc
                if attempt >= self._connect_retry_attempts - 1:
                    raise
                time.sleep(self._connect_retry_delay_seconds * (attempt + 1))

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Graphiti request failed unexpectedly for {method} {path}")
