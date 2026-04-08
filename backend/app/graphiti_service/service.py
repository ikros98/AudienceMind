from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import HTTPException, status
import openai

from graphiti_core.edges import EntityEdge
from graphiti_core.errors import NodeNotFoundError
from graphiti_core.graphiti import Graphiti
from graphiti_core.llm_client.errors import RateLimitError as GraphitiRateLimitError
from graphiti_core.nodes import EntityNode, EpisodeType
from graphiti_core.search.search_config_recipes import (
    COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
    COMBINED_HYBRID_SEARCH_RRF,
    EDGE_HYBRID_SEARCH_CROSS_ENCODER,
    EDGE_HYBRID_SEARCH_RRF,
    NODE_HYBRID_SEARCH_CROSS_ENCODER,
    NODE_HYBRID_SEARCH_RRF,
)
from graphiti_core.search.search_filters import SearchFilters

from .config import Settings
from .metadata_store import GraphMetadataStore
from .models import (
    CreateGraphRequest,
    CreateGraphResponse,
    DeleteGraphResponse,
    GraphMetadata,
    IngestEpisodesRequest,
    IngestEpisodesResponse,
    SearchRequest,
    SearchResponse,
    SetOntologyRequest,
    SetOntologyResponse,
)
from .normalization import normalize_edge, normalize_node
from .ontology import OntologyTranslation, translate_ontology

logger = logging.getLogger(__name__)


class GraphitiCompatibilityService:
    def __init__(self, settings: Settings, graphiti: Graphiti, metadata_store: GraphMetadataStore):
        self.settings = settings
        self.graphiti = graphiti
        self.metadata_store = metadata_store

    async def startup(self) -> None:
        self.settings.metadata_dir.mkdir(parents=True, exist_ok=True)
        await self.graphiti.build_indices_and_constraints(delete_existing=False)
        logger.info("Graphiti indices and constraints ensured")

    async def check_neo4j(self) -> None:
        await self.graphiti.driver.execute_query("RETURN 1 AS ok", routing_="r")

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _get_graph_metadata(self, graph_id: str) -> GraphMetadata:
        metadata = self.metadata_store.get(graph_id)
        if metadata is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Graph not found: {graph_id}",
            )
        return metadata

    def _require_ontology(self, metadata: GraphMetadata) -> OntologyTranslation:
        if metadata.ontology is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Graph ontology has not been set",
            )
        return translate_ontology(metadata.ontology)

    def create_graph(self, request: CreateGraphRequest) -> CreateGraphResponse:
        graph_id = request.graph_id or f"personagraph_{uuid.uuid4().hex[:16]}"
        if self.metadata_store.get(graph_id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Graph already exists: {graph_id}",
            )

        now = self._now()
        metadata = GraphMetadata(
            graph_id=graph_id,
            name=request.name,
            description=request.description,
            created_at=now,
            updated_at=now,
            default_saga=graph_id,
        )
        self.metadata_store.save(metadata)
        return CreateGraphResponse(
            graph_id=graph_id,
            name=metadata.name,
            description=metadata.description,
            created_at=metadata.created_at,
        )

    def set_ontology(self, graph_id: str, request: SetOntologyRequest) -> SetOntologyResponse:
        metadata = self._get_graph_metadata(graph_id)
        translation = translate_ontology(request.ontology)
        metadata.ontology = request.ontology
        metadata.ontology_translation = translation.metadata
        metadata.updated_at = self._now()
        self.metadata_store.save(metadata)
        return SetOntologyResponse(
            graph_id=graph_id,
            entity_type_count=len(request.ontology.get("entity_types", [])),
            edge_type_count=len(request.ontology.get("edge_types", [])),
            updated_at=metadata.updated_at,
        )

    async def ingest_episodes(
        self,
        graph_id: str,
        request: IngestEpisodesRequest,
    ) -> IngestEpisodesResponse:
        metadata = self._get_graph_metadata(graph_id)
        ontology = self._require_ontology(metadata)
        saga_name = request.saga or metadata.default_saga or graph_id
        previous_episode_uuid = metadata.last_episode_uuid
        ingested_episode_uuids: list[str] = []

        for episode in request.episodes:
            try:
                result = await self.graphiti.add_episode(
                    name=episode.name,
                    episode_body=episode.episode_body,
                    source_description=episode.source_description,
                    reference_time=episode.reference_time or self._now(),
                    source=EpisodeType(episode.source),
                    group_id=graph_id,
                    uuid=episode.uuid,
                    update_communities=request.update_communities,
                    entity_types=ontology.entity_types,
                    edge_types=ontology.edge_types,
                    edge_type_map=ontology.edge_type_map,
                    custom_extraction_instructions=request.custom_extraction_instructions,
                    saga=saga_name,
                    saga_previous_episode_uuid=previous_episode_uuid,
                )
            except openai.APITimeoutError as exc:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Graphiti LLM request timed out while ingesting an episode.",
                ) from exc
            except openai.APIConnectionError as exc:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Graphiti LLM connection failed while ingesting an episode.",
                ) from exc
            except GraphitiRateLimitError as exc:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Graphiti LLM provider is rate-limiting requests. Retry shortly or use a higher-throughput provider.",
                ) from exc
            previous_episode_uuid = result.episode.uuid
            ingested_episode_uuids.append(result.episode.uuid)

        metadata.episode_count += len(ingested_episode_uuids)
        metadata.last_episode_uuid = previous_episode_uuid
        metadata.updated_at = self._now()
        self.metadata_store.save(metadata)

        return IngestEpisodesResponse(
            graph_id=graph_id,
            ingested_count=len(ingested_episode_uuids),
            episode_uuids=ingested_episode_uuids,
            node_count=0,
            edge_count=0,
            last_episode_uuid=previous_episode_uuid,
        )

    async def get_graph(self, graph_id: str):
        all_nodes = []
        node_cursor: str | None = None
        while True:
            nodes = await self.list_nodes(graph_id, limit=self.settings.max_page_size, cursor=node_cursor)
            all_nodes.extend(nodes.items)
            if not nodes.next_cursor:
                break
            node_cursor = nodes.next_cursor

        all_edges = []
        edge_cursor: str | None = None
        while True:
            edges = await self.list_edges(graph_id, limit=self.settings.max_page_size, cursor=edge_cursor)
            all_edges.extend(edges.items)
            if not edges.next_cursor:
                break
            edge_cursor = edges.next_cursor

        return {
            "graph_id": graph_id,
            "nodes": [item.model_dump(mode="json") for item in all_nodes],
            "edges": [item.model_dump(mode="json") for item in all_edges],
            "node_count": len(all_nodes),
            "edge_count": len(all_edges),
        }

    async def list_nodes(self, graph_id: str, *, limit: int, cursor: str | None):
        metadata = self._get_graph_metadata(graph_id)
        page_limit = min(limit, self.settings.max_page_size)
        raw_nodes = await EntityNode.get_by_group_ids(
            self.graphiti.driver,
            [graph_id],
            limit=page_limit + 1,
            uuid_cursor=cursor,
        )
        items = raw_nodes[:page_limit]
        next_cursor = items[-1].uuid if len(raw_nodes) > page_limit and items else None
        from .models import NodeListResponse

        return NodeListResponse(
            graph_id=graph_id,
            items=[normalize_node(node, metadata.ontology_translation) for node in items],
            next_cursor=next_cursor,
        )

    async def list_edges(self, graph_id: str, *, limit: int, cursor: str | None):
        metadata = self._get_graph_metadata(graph_id)
        page_limit = min(limit, self.settings.max_page_size)
        try:
            raw_edges = await EntityEdge.get_by_group_ids(
                self.graphiti.driver,
                [graph_id],
                limit=page_limit + 1,
                uuid_cursor=cursor,
            )
        except Exception:
            raw_edges = []
        items = raw_edges[:page_limit]
        node_name_map = await self._node_name_map_for_edges(items)
        next_cursor = items[-1].uuid if len(raw_edges) > page_limit and items else None
        from .models import EdgeListResponse

        return EdgeListResponse(
            graph_id=graph_id,
            items=[
                normalize_edge(edge, metadata.ontology_translation, node_name_map)
                for edge in items
            ],
            next_cursor=next_cursor,
        )

    async def get_node(self, graph_id: str, node_uuid: str):
        metadata = self._get_graph_metadata(graph_id)
        try:
            node = await EntityNode.get_by_uuid(self.graphiti.driver, node_uuid)
        except NodeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Node not found: {node_uuid}") from exc

        if node.group_id != graph_id:
            raise HTTPException(status_code=404, detail=f"Node not found in graph: {node_uuid}")
        return normalize_node(node, metadata.ontology_translation)

    async def get_edge(self, graph_id: str, edge_uuid: str):
        metadata = self._get_graph_metadata(graph_id)
        try:
            edge = await EntityEdge.get_by_uuid(self.graphiti.driver, edge_uuid)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Edge not found: {edge_uuid}") from exc

        if edge.group_id != graph_id:
            raise HTTPException(status_code=404, detail=f"Edge not found in graph: {edge_uuid}")
        node_name_map = await self._node_name_map_for_edges([edge])
        return normalize_edge(edge, metadata.ontology_translation, node_name_map)

    async def get_node_edges(self, graph_id: str, node_uuid: str):
        metadata = self._get_graph_metadata(graph_id)
        node = await self.get_node(graph_id, node_uuid)
        raw_edges = await EntityEdge.get_by_node_uuid(self.graphiti.driver, node_uuid)
        filtered_edges = [edge for edge in raw_edges if edge.group_id == graph_id]
        node_name_map = await self._node_name_map_for_edges(filtered_edges)
        from .models import EdgeListResponse

        return EdgeListResponse(
            graph_id=graph_id,
            items=[
                normalize_edge(edge, metadata.ontology_translation, node_name_map)
                for edge in filtered_edges
            ],
            next_cursor=None,
        )

    async def search(self, graph_id: str, request: SearchRequest) -> SearchResponse:
        metadata = self._get_graph_metadata(graph_id)
        config = self._search_config_for_scope(request.scope)
        config.limit = request.limit
        results = await self.graphiti.search_(
            query=request.query,
            config=config,
            group_ids=[graph_id],
            center_node_uuid=request.center_node_uuid,
            search_filter=SearchFilters(
                node_labels=request.node_labels,
                edge_types=request.edge_types,
            ),
        )
        node_name_map = {node.uuid: node.name for node in results.nodes}
        node_name_map.update(await self._node_name_map_for_edges(results.edges))
        edges = [normalize_edge(edge, metadata.ontology_translation, node_name_map) for edge in results.edges]
        nodes = [normalize_node(node, metadata.ontology_translation) for node in results.nodes]
        facts = [edge.fact for edge in edges if edge.fact]
        for node in nodes:
            if node.summary:
                facts.append(f"[{node.name}]: {node.summary}")
        return SearchResponse(
            query=request.query,
            total_count=len(facts),
            facts=facts,
            nodes=nodes,
            edges=edges,
        )

    async def delete_graph(self, graph_id: str) -> DeleteGraphResponse:
        self._get_graph_metadata(graph_id)
        await self.graphiti.driver.execute_query(
            """
            MATCH (n)
            WHERE n.group_id = $group_id
            DETACH DELETE n
            """,
            group_id=graph_id,
        )
        self.metadata_store.delete(graph_id)
        return DeleteGraphResponse(graph_id=graph_id, deleted=True)

    def _search_config_for_scope(self, scope: str):
        use_cross_encoder = self.settings.search_reranker == "cross_encoder"
        if scope == "nodes":
            return deepcopy(
                NODE_HYBRID_SEARCH_CROSS_ENCODER if use_cross_encoder else NODE_HYBRID_SEARCH_RRF
            )
        if scope == "both":
            return deepcopy(
                COMBINED_HYBRID_SEARCH_CROSS_ENCODER
                if use_cross_encoder
                else COMBINED_HYBRID_SEARCH_RRF
            )
        return deepcopy(
            EDGE_HYBRID_SEARCH_CROSS_ENCODER if use_cross_encoder else EDGE_HYBRID_SEARCH_RRF
        )

    async def _node_name_map_for_edges(self, edges: list[EntityEdge]) -> dict[str, str]:
        uuids = {
            edge.source_node_uuid
            for edge in edges
            if edge.source_node_uuid
        } | {
            edge.target_node_uuid
            for edge in edges
            if edge.target_node_uuid
        }
        if not uuids:
            return {}
        nodes = await EntityNode.get_by_uuids(self.graphiti.driver, sorted(uuids))
        return {node.uuid: node.name for node in nodes}
