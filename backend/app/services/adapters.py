"""Adapter interfaces for external providers and engines."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from ..config import Settings
from ..models import GraphJob, Project, Report, Simulation, SourceDocument
from .generation import (
    GraphArtifacts,
    ReportArtifacts,
    SimulationArtifacts,
    TextGenerator,
    build_chat_response,
    build_graph_artifacts,
    build_glass_ontology,
    build_report_artifacts,
    build_simulation_artifacts,
    infer_project_name,
)
from .graphiti import GraphitiClient, sanitize_graphiti_ontology, split_text_chunks


GraphBuildProgress = Callable[[float, str], None]


class LLMProvider(Protocol):
    """Interface for the active LLM provider."""

    name: str

    def describe(self) -> str:
        """Return a human-readable description of the configured provider."""

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 700,
    ) -> str:
        """Generate text from a prompt pair."""


class GraphBackendAdapter(Protocol):
    """Interface for the active graph backend."""

    name: str

    def describe(self) -> str:
        """Return a human-readable description of the graph backend."""

    def build_artifacts(
        self,
        *,
        llm: TextGenerator,
        project: Project,
        documents: list[SourceDocument],
        objective: str,
        ontology: dict[str, Any] | None = None,
        graph_id: str | None = None,
        progress_callback: GraphBuildProgress | None = None,
    ) -> GraphArtifacts:
        """Build graph preparation artifacts for a project."""


class SimulationEngine(Protocol):
    """Interface for the active simulation runtime."""

    name: str

    def describe(self) -> str:
        """Return a human-readable description of the simulation engine."""

    def build_artifacts(
        self,
        *,
        llm: TextGenerator,
        project: Project,
        graph_job: GraphJob | None,
        mode: str,
        cohort_size: int,
    ) -> SimulationArtifacts:
        """Build simulation artifacts for a project."""


class ReportingService(Protocol):
    """Interface for report generation and grounded analysis responses."""

    name: str

    def describe(self) -> str:
        """Return a human-readable description of the reporting service."""

    def build_report_artifacts(
        self,
        *,
        llm: TextGenerator,
        project: Project,
        simulation: Simulation,
        focus: str,
    ) -> ReportArtifacts:
        """Build report artifacts for a completed simulation."""

    def answer_question(
        self,
        *,
        llm: TextGenerator,
        project: Project,
        simulation: Simulation,
        report: Report | None,
        message: str,
    ) -> tuple[str, list[str]]:
        """Build a grounded chat response."""


@dataclass(frozen=True)
class HeuristicGraphBackend:
    """Local graph adapter that preserves the integration boundary."""

    name: str
    label: str

    def describe(self) -> str:
        """Return the configured label."""
        return self.label

    def build_artifacts(
        self,
        *,
        llm: TextGenerator,
        project: Project,
        documents: list[SourceDocument],
        objective: str,
        ontology: dict[str, Any] | None = None,
        graph_id: str | None = None,
        progress_callback: GraphBuildProgress | None = None,
    ) -> GraphArtifacts:
        """Build graph artifacts using the local heuristic generator."""
        if progress_callback is not None:
            progress_callback(42.0, "Generating local graph artifacts.")
        return build_graph_artifacts(llm, project, documents, objective)


@dataclass
class GraphitiGraphBackend:
    """Graph backend that materializes a real graph through the Graphiti service."""

    settings: Settings
    name: str
    label: str

    def describe(self) -> str:
        """Return the configured label."""
        return self.label

    def _resolve_ingest_batch_size(self) -> int:
        """Match the stable legacy Graphiti path and ingest one episode per request."""
        del self
        return 1

    def _uses_slow_openrouter_free_model(self) -> bool:
        """Identify hosted free-tier OpenRouter paths that need smaller first-pass Graphiti episodes."""
        llm_base_url = (self.settings.llm_base_url or "").lower()
        llm_model = (self.settings.llm_model or "").lower()
        return "openrouter.ai" in llm_base_url and ":free" in llm_model

    def _resolve_episode_chunk_floor(self) -> int:
        """Choose the minimum first-pass episode size for the active provider path."""
        if self._uses_slow_openrouter_free_model():
            return 500
        return max(1000, self.settings.graph_chunk_size)

    def _resolve_episode_chunk_cap(self) -> int:
        """Avoid oversized first-pass Graphiti episodes on slow hosted OpenAI-compatible endpoints."""
        if self._uses_slow_openrouter_free_model():
            return 650
        return 2400

    def build_artifacts(
        self,
        *,
        llm: TextGenerator,
        project: Project,
        documents: list[SourceDocument],
        objective: str,
        ontology: dict[str, Any] | None = None,
        graph_id: str | None = None,
        progress_callback: GraphBuildProgress | None = None,
    ) -> GraphArtifacts:
        """Build real graph artifacts with Graphiti and normalize them for PersonaGraph."""
        base_artifacts = build_graph_artifacts(llm, project, documents, objective)
        source_documents = [item for item in documents if (item.extracted_text or "").strip()]
        if not source_documents:
            raise RuntimeError("No extracted source text is available for graph materialization.")

        if progress_callback is not None:
            progress_callback(8.0, "Preparing ontology for real entity extraction.")

        resolved_ontology = ontology if isinstance(ontology, dict) and ontology else self._build_ontology(
            llm=llm,
            project=project,
            documents=source_documents,
            objective=objective,
        )
        graphiti_ontology = sanitize_graphiti_ontology(resolved_ontology)
        resolved_graph_id = str(graph_id or project.id)
        episodes = self._build_episodes(project, source_documents)
        if not episodes:
            raise RuntimeError("Graphiti ingestion produced no document episodes.")
        source_texts = [item.extracted_text for item in source_documents if item.extracted_text]
        resolved_project_name = infer_project_name(
            project.name,
            requirement=objective or project.scenario_brief,
            additional_context=project.description,
            source_texts=source_texts,
        )
        if progress_callback is not None:
            progress_callback(16.0, "Connecting to Graphiti service.")

        client = GraphitiClient(self.settings)
        try:
            client.delete_graph(resolved_graph_id, ignore_missing=True)
            client.create_graph(
                graph_id=resolved_graph_id,
                name=resolved_project_name or "PersonaGraph Graph",
                description=objective or project.scenario_brief or "PersonaGraph graph materialization",
            )
            if progress_callback is not None:
                progress_callback(24.0, "Registering ontology with Graphiti.")
            client.set_ontology(resolved_graph_id, graphiti_ontology)
            if progress_callback is not None:
                progress_callback(30.0, f"Prepared {len(episodes)} Graphiti episodes.")
            client.ingest_episodes(
                resolved_graph_id,
                episodes,
                batch_size=self._resolve_ingest_batch_size(),
                custom_extraction_instructions=None,
                progress_callback=(
                    None
                    if progress_callback is None
                    else lambda message, fraction: progress_callback(30.0 + (fraction * 58.0), message)
                ),
            )
            if progress_callback is not None:
                progress_callback(88.0, "Waiting for Graphiti graph counts to settle.")
            payload = client.wait_for_graph_settle(
                resolved_graph_id,
                progress_callback=(
                    None
                    if progress_callback is None
                    else lambda message, fraction: progress_callback(88.0 + (fraction * 10.0), message)
                ),
            )
        finally:
            client.close()

        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        node_count = int(metadata.get("node_count") or 0)
        edge_count = int(metadata.get("edge_count") or 0)
        entity_types = metadata.get("entity_types") if isinstance(metadata.get("entity_types"), list) else []
        summary = (
            f"Materialized a real graph with {node_count} nodes and {edge_count} edges"
            f" across {len(entity_types)} entity types."
        )
        if progress_callback is not None:
            progress_callback(98.0, "Real entity graph materialized.")

        return GraphArtifacts(
            summary=summary,
            source_digest=base_artifacts.source_digest,
            schema_markdown=base_artifacts.schema_markdown,
            evidence_markdown=base_artifacts.evidence_markdown,
            node_count=node_count,
            edge_count=edge_count,
            graph_id=resolved_graph_id,
            graph_payload=payload,
        )

    def _build_ontology(
        self,
        *,
        llm: TextGenerator,
        project: Project,
        documents: list[SourceDocument],
        objective: str,
    ) -> dict[str, Any]:
        source_texts = [item.extracted_text for item in documents if item.extracted_text]
        ontology, _summary = build_glass_ontology(
            llm,
            project_name=project.name,
            requirement=objective or project.scenario_brief,
            additional_context=project.description,
            source_texts=source_texts,
        )
        return ontology

    def _build_episodes(self, project: Project, documents: list[SourceDocument]) -> list[dict[str, Any]]:
        episodes: list[dict[str, Any]] = []
        source_texts = [item.extracted_text for item in documents if item.extracted_text]
        project_label = infer_project_name(
            project.name,
            requirement=project.scenario_brief,
            additional_context=project.description,
            source_texts=source_texts,
        )
        for document in documents:
            text = (document.extracted_text or "").strip()
            if not text:
                continue
            configured_chunk_size = self._resolve_episode_chunk_floor()
            chunk_cap = self._resolve_episode_chunk_cap()
            if len(text) > 6500:
                target_chunk_count = 4
            elif len(text) > 3200:
                target_chunk_count = 3
            else:
                target_chunk_count = 2
            adaptive_chunk_size = (len(text) + target_chunk_count - 1) // target_chunk_count
            chunk_size = max(configured_chunk_size, min(adaptive_chunk_size, chunk_cap))
            chunk_overlap = min(max(60, self.settings.graph_chunk_overlap), max(120, chunk_size // 12))
            chunks = split_text_chunks(
                text,
                chunk_size=chunk_size,
                overlap=chunk_overlap,
            )
            source_label = Path(document.filename).stem or "document"
            for index, chunk in enumerate(chunks, start=1):
                episodes.append(
                    {
                        "name": f"{source_label}-{index}",
                        "episode_body": chunk,
                        "source_description": f"{project_label or 'PersonaGraph'} document chunk",
                    }
                )
        return episodes


@dataclass(frozen=True)
class HeuristicSimulationEngine:
    """Local simulation adapter that preserves the integration boundary."""

    name: str
    label: str

    def describe(self) -> str:
        """Return the configured label."""
        return self.label

    def build_artifacts(
        self,
        *,
        llm: TextGenerator,
        project: Project,
        graph_job: GraphJob | None,
        mode: str,
        cohort_size: int,
    ) -> SimulationArtifacts:
        """Build simulation artifacts using the local heuristic generator."""
        return build_simulation_artifacts(llm, project, graph_job, mode, cohort_size)


@dataclass(frozen=True)
class HeuristicReportingService:
    """Local reporting adapter that preserves the integration boundary."""

    name: str
    label: str

    def describe(self) -> str:
        """Return the configured label."""
        return self.label

    def build_report_artifacts(
        self,
        *,
        llm: TextGenerator,
        project: Project,
        simulation: Simulation,
        focus: str,
    ) -> ReportArtifacts:
        """Build report artifacts using the local heuristic generator."""
        return build_report_artifacts(llm, project, simulation, focus)

    def answer_question(
        self,
        *,
        llm: TextGenerator,
        project: Project,
        simulation: Simulation,
        report: Report | None,
        message: str,
    ) -> tuple[str, list[str]]:
        """Build a grounded answer using the local heuristic generator."""
        return build_chat_response(llm, project, simulation, report, message)
