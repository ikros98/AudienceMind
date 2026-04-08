from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, create_model

from .models import OntologyTranslationMetadata


_GRAPHITI_ENTITY_RESERVED_NAMES = {
    "uuid",
    "name",
    "group_id",
    "labels",
    "summary",
    "attributes",
    "created_at",
    "name_embedding",
}


def _safe_identifier(raw_name: str, *, prefix: str, reserved_names: set[str]) -> str:
    sanitized = re.sub(r"[^0-9a-zA-Z_]+", "_", raw_name.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        sanitized = prefix
    if sanitized[0].isdigit():
        sanitized = f"{prefix}_{sanitized}"
    if keyword.iskeyword(sanitized) or sanitized.lower() in reserved_names:
        sanitized = f"{prefix}_{sanitized}"
    return sanitized


def _edge_model_class_name(edge_name: str) -> str:
    parts = re.split(r"[^0-9a-zA-Z]+", edge_name)
    tokens = [part.capitalize() for part in parts if part]
    return "".join(tokens) or "Relation"


@dataclass(slots=True)
class OntologyTranslation:
    entity_types: dict[str, type[BaseModel]]
    edge_types: dict[str, type[BaseModel]]
    edge_type_map: dict[tuple[str, str], list[str]]
    metadata: OntologyTranslationMetadata


def translate_ontology(ontology: dict[str, Any]) -> OntologyTranslation:
    entity_models: dict[str, type[BaseModel]] = {}
    entity_aliases: dict[str, dict[str, str]] = {}
    edge_models: dict[str, type[BaseModel]] = {}
    edge_aliases: dict[str, dict[str, str]] = {}
    edge_type_map: dict[tuple[str, str], list[str]] = {}
    edge_type_map_metadata: dict[str, list[str]] = {}

    entity_names = [item["name"] for item in ontology.get("entity_types", []) if item.get("name")]
    all_entity_names = entity_names or ["Entity"]

    for entity_def in ontology.get("entity_types", []):
        entity_name = entity_def["name"]
        alias_map: dict[str, str] = {}
        fields: dict[str, tuple[type[str] | None, Field]] = {}
        used_names: set[str] = set()
        for attribute in entity_def.get("attributes", []):
            original_name = attribute["name"]
            safe_name = _safe_identifier(
                original_name,
                prefix="entity",
                reserved_names=_GRAPHITI_ENTITY_RESERVED_NAMES | {name.lower() for name in used_names},
            )
            while safe_name in used_names:
                safe_name = f"entity_{safe_name}"
            used_names.add(safe_name)
            alias_map[safe_name] = original_name
            fields[safe_name] = (
                str | None,
                Field(default=None, description=attribute.get("description", original_name)),
            )

        model = create_model(entity_name, __base__=BaseModel, **fields)
        model.__doc__ = entity_def.get("description", f"Ontology entity type {entity_name}.")
        entity_models[entity_name] = model
        entity_aliases[entity_name] = alias_map

    for edge_def in ontology.get("edge_types", []):
        edge_name = edge_def["name"]
        class_name = _edge_model_class_name(edge_name)
        alias_map: dict[str, str] = {}
        fields: dict[str, tuple[type[str] | None, Field]] = {}
        used_names: set[str] = set()
        for attribute in edge_def.get("attributes", []):
            original_name = attribute["name"]
            safe_name = _safe_identifier(
                original_name,
                prefix="edge",
                reserved_names={name.lower() for name in used_names},
            )
            while safe_name in used_names:
                safe_name = f"edge_{safe_name}"
            used_names.add(safe_name)
            alias_map[safe_name] = original_name
            fields[safe_name] = (
                str | None,
                Field(default=None, description=attribute.get("description", original_name)),
            )

        model = create_model(class_name, __base__=BaseModel, **fields)
        model.__doc__ = edge_def.get("description", f"Ontology relationship type {edge_name}.")
        edge_models[edge_name] = model
        edge_aliases[edge_name] = alias_map

        source_targets = edge_def.get("source_targets") or []
        if not source_targets:
            source_targets = [
                {"source": source_name, "target": target_name}
                for source_name in all_entity_names
                for target_name in all_entity_names
            ]

        metadata_key = f"{edge_name}"
        edge_type_map_metadata[metadata_key] = []
        for source_target in source_targets:
            source_name = source_target.get("source") or "Entity"
            target_name = source_target.get("target") or "Entity"
            key = (source_name, target_name)
            edge_type_map.setdefault(key, [])
            if edge_name not in edge_type_map[key]:
                edge_type_map[key].append(edge_name)
            serialized_key = f"{source_name}::{target_name}"
            edge_type_map_metadata.setdefault(serialized_key, [])
            if edge_name not in edge_type_map_metadata[serialized_key]:
                edge_type_map_metadata[serialized_key].append(edge_name)

    return OntologyTranslation(
        entity_types=entity_models,
        edge_types=edge_models,
        edge_type_map=edge_type_map,
        metadata=OntologyTranslationMetadata(
            entity_attribute_aliases=entity_aliases,
            edge_attribute_aliases=edge_aliases,
            edge_type_map=edge_type_map_metadata,
        ),
    )


def restore_entity_attributes(
    labels: list[str],
    attributes: dict[str, Any],
    metadata: OntologyTranslationMetadata | None,
) -> dict[str, Any]:
    if metadata is None or not attributes:
        return attributes

    alias_map: dict[str, str] = {}
    for label in labels:
        alias_map.update(metadata.entity_attribute_aliases.get(label, {}))

    return {alias_map.get(key, key): value for key, value in attributes.items()}


def restore_edge_attributes(
    edge_name: str,
    attributes: dict[str, Any],
    metadata: OntologyTranslationMetadata | None,
) -> dict[str, Any]:
    if metadata is None or not attributes:
        return attributes
    alias_map = metadata.edge_attribute_aliases.get(edge_name, {})
    return {alias_map.get(key, key): value for key, value in attributes.items()}

