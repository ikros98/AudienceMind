from __future__ import annotations

from typing import Any

from .models import EdgeResponse, NodeResponse, OntologyTranslationMetadata
from .ontology import restore_edge_attributes, restore_entity_attributes


def normalize_node(node: Any, metadata: OntologyTranslationMetadata | None) -> NodeResponse:
    labels = list(getattr(node, "labels", []) or [])
    attributes = dict(getattr(node, "attributes", {}) or {})
    return NodeResponse(
        uuid=str(getattr(node, "uuid", "")),
        name=str(getattr(node, "name", "") or ""),
        labels=labels,
        summary=str(getattr(node, "summary", "") or ""),
        attributes=restore_entity_attributes(labels, attributes, metadata),
        created_at=getattr(node, "created_at", None),
    )


def normalize_edge(
    edge: Any,
    metadata: OntologyTranslationMetadata | None,
    node_name_map: dict[str, str] | None = None,
) -> EdgeResponse:
    node_name_map = node_name_map or {}
    source_uuid = str(getattr(edge, "source_node_uuid", "") or "")
    target_uuid = str(getattr(edge, "target_node_uuid", "") or "")
    edge_name = str(getattr(edge, "name", "") or "")
    attributes = dict(getattr(edge, "attributes", {}) or {})
    return EdgeResponse(
        uuid=str(getattr(edge, "uuid", "")),
        name=edge_name,
        fact=str(getattr(edge, "fact", "") or ""),
        source_node_uuid=source_uuid,
        target_node_uuid=target_uuid,
        source_node_name=node_name_map.get(source_uuid),
        target_node_name=node_name_map.get(target_uuid),
        attributes=restore_edge_attributes(edge_name, attributes, metadata),
        created_at=getattr(edge, "created_at", None),
        valid_at=getattr(edge, "valid_at", None),
        invalid_at=getattr(edge, "invalid_at", None),
        expired_at=getattr(edge, "expired_at", None),
    )

