from __future__ import annotations

import json
import threading
from pathlib import Path

from .models import GraphMetadata


class GraphMetadataStore:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _graph_path(self, graph_id: str) -> Path:
        return self.root_dir / f"{graph_id}.json"

    def get(self, graph_id: str) -> GraphMetadata | None:
        path = self._graph_path(graph_id)
        if not path.exists():
            return None
        with self._lock:
            return GraphMetadata.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, metadata: GraphMetadata) -> GraphMetadata:
        path = self._graph_path(metadata.graph_id)
        tmp_path = path.with_suffix(".json.tmp")
        payload = metadata.model_dump(mode="json", exclude_none=False)
        with self._lock:
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        return metadata

    def delete(self, graph_id: str) -> None:
        path = self._graph_path(graph_id)
        with self._lock:
            if path.exists():
                path.unlink()

