from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class OntologyTranslationMetadata(BaseModel):
    entity_attribute_aliases: dict[str, dict[str, str]] = Field(default_factory=dict)
    edge_attribute_aliases: dict[str, dict[str, str]] = Field(default_factory=dict)
    edge_type_map: dict[str, list[str]] = Field(default_factory=dict)


class GraphMetadata(BaseModel):
    graph_id: str
    name: str
    description: str = ""
    created_at: datetime
    updated_at: datetime
    ontology: dict[str, Any] | None = None
    ontology_translation: OntologyTranslationMetadata | None = None
    episode_count: int = 0
    last_episode_uuid: str | None = None
    default_saga: str | None = None


class CreateGraphRequest(BaseModel):
    graph_id: str | None = None
    name: str
    description: str = ""


class CreateGraphResponse(BaseModel):
    graph_id: str
    name: str
    description: str
    created_at: datetime


class SetOntologyRequest(BaseModel):
    ontology: dict[str, Any]


class SetOntologyResponse(BaseModel):
    graph_id: str
    entity_type_count: int
    edge_type_count: int
    updated_at: datetime


class EpisodeInput(BaseModel):
    name: str
    episode_body: str
    source_description: str = "PersonaGraph document chunk"
    reference_time: datetime | None = None
    source: str = "message"
    uuid: str | None = None


class IngestEpisodesRequest(BaseModel):
    episodes: list[EpisodeInput]
    update_communities: bool = False
    custom_extraction_instructions: str | None = None
    saga: str | None = None


class IngestEpisodesResponse(BaseModel):
    graph_id: str
    ingested_count: int
    episode_uuids: list[str] = Field(default_factory=list)
    node_count: int
    edge_count: int
    last_episode_uuid: str | None = None


class NodeResponse(BaseModel):
    uuid: str
    name: str
    labels: list[str]
    summary: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class EdgeResponse(BaseModel):
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: str | None = None
    target_node_name: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    expired_at: datetime | None = None


class NodeListResponse(BaseModel):
    graph_id: str
    items: list[NodeResponse]
    next_cursor: str | None = None


class EdgeListResponse(BaseModel):
    graph_id: str
    items: list[EdgeResponse]
    next_cursor: str | None = None


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    scope: Literal["edges", "nodes", "both"] = "edges"
    center_node_uuid: str | None = None
    node_labels: list[str] | None = None
    edge_types: list[str] | None = None


class SearchResponse(BaseModel):
    query: str
    total_count: int
    facts: list[str]
    nodes: list[NodeResponse]
    edges: list[EdgeResponse]


class DeleteGraphResponse(BaseModel):
    graph_id: str
    deleted: bool


class HealthResponse(BaseModel):
    status: str
    service: str
    neo4j: str
    metadata_dir: str
    reasoning_force_off: bool
