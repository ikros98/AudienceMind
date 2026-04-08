"""Focused tests for generation helpers used by the glass compatibility path."""

import json
from pathlib import Path

from app.config import Settings
from app.models import Project, Report, Simulation
from app.services.generation import (
    build_glass_graph_snapshot,
    build_glass_ontology,
    build_glass_profiles,
    build_glass_report_chat_response,
    build_glass_simulation_config,
    build_glass_report_package,
    build_graphiti_extraction_instructions,
    detect_social_brand_simulation_submode,
    extract_named_entity_candidates,
)
from app.services.glass_compat import (
    graph_entities_for_preparation,
    graph_payload_is_synthetic,
    load_graph_payload,
    save_graph_payload,
)
from app.services.glass_compat import compact_graph_payload_for_display
from app.services.oasis_runtime import choose_active_agent_ids


class StubJsonLLM:
    """Simple stub that returns a fixed JSON payload."""

    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def generate(self, **_: object) -> str:
        return json.dumps(self.payload)


class StubTextLLM:
    """Simple stub that returns a fixed text payload."""

    def __init__(self, response: str):
        self.response = response

    def generate(self, **_: object) -> str:
        return self.response


def test_build_glass_graph_snapshot_creates_realish_sports_partnership_graph() -> None:
    """Deterministic test-mode graphs should be concrete enough for the glass workflow."""
    project = Project(
        name="Ralph Lauren Gen Z Loyalty Scenario",
        scenario_brief=(
            "Simulate social media reaction to Ralph Lauren unveiling the Team USA parade uniforms for the upcoming "
            "Olympic Games. Include patriotic consumers, fashion critics, competing sportswear brands (Nike, Adidas, "
            "Under Armour), sustainability advocates questioning textile sourcing, international fashion media, and "
            "athletes as brand ambassadors."
        ),
    )
    ontology, _ = build_glass_ontology(
        None,
        project_name=project.name,
        requirement=project.scenario_brief,
        additional_context="Predict viral potential, sentiment split, and whether the Olympic moment converts to impact.",
        source_texts=[
            "Ralph Lauren unveiled Team USA parade uniforms ahead of the Olympic Games while fashion media debated fit, "
            "patriotism, and sustainability claims. Nike, Adidas, and Under Armour remain the comparison set."
        ],
    )

    payload = build_glass_graph_snapshot(
        project=project,
        source_digest="ralph lauren, team usa, olympic games, nike, sustainability",
        ontology=ontology,
        source_texts=[
            "Ralph Lauren unveiled Team USA parade uniforms ahead of the Olympic Games while fashion media debated fit, "
            "patriotism, and sustainability claims. Nike, Adidas, and Under Armour remain the comparison set."
        ],
        node_budget=18,
    )

    names = {str(node["name"]) for node in payload["nodes"]}
    labels = {str(node["label"]) for node in payload["nodes"]}
    edge_types = {str(edge["relation_type"]) for edge in payload["edges"]}

    assert graph_payload_is_synthetic(payload) is False
    assert {"Ralph Lauren", "Team USA", "Nike", "Adidas", "Under Armour"} <= names
    assert "Fashion Brand" in labels
    assert "Sportswear Competitor" in labels
    assert payload["metadata"]["node_count"] == len(payload["nodes"])
    assert payload["metadata"]["edge_count"] == len(payload["edges"])
    assert {"competes_with", "reacts_to", "covers"} & edge_types


def test_build_glass_report_package_handles_sparse_runtime_actions() -> None:
    """Real worker actions can omit topic labels and should still generate a report."""
    project = Project(name="Parity Project", scenario_brief="Trust is shifting around a sustainability claim.")
    package = build_glass_report_package(
        project=project,
        focus="What should analysts monitor next?",
        config={
            "event_config": {
                "hot_topics": ["Trust", "Credibility"],
                "scheduled_events": [{"name": "Creator reaction"}],
            }
        },
        actions=[
            {
                "round_num": 1,
                "platform": "twitter",
                "agent_id": "agent_001",
                "agent_name": "Creator Watcher",
                "action_type": "CREATE_POST",
                "content": "The sustainability proof still feels thin, and trust is wobbling.",
            },
            {
                "round_num": 2,
                "platform": "reddit",
                "agent_id": "agent_002",
                "agent_name": "Policy Skeptic",
                "action_type": "COMMENT",
                "body": "Evidence quality matters more than fast messaging here.",
            },
        ],
        interviews=[
            {
                "agent_id": "agent_001",
                "agent_name": "Creator Watcher",
                "response": "I need proof before the narrative settles.",
            }
        ],
        posts_by_platform={
            "twitter": [{"content": "Trust is slipping until evidence catches up."}],
            "reddit": [{"title": "Sustainability claim under pressure", "body": "People want receipts."}],
        },
        comments=[{"content": "Still waiting for more proof."}],
        graph_metadata={"node_count": 12, "edge_count": 18, "entity_types": ["Audience Segment", "Narrative"]},
        graph_facts=["Twitter is amplifying early skepticism."],
        llm=None,
    )

    assert package["sections"]
    assert "## Platform Split: Velocity Versus Scrutiny" in package["markdown_body"]
    assert "creator watcher" in package["markdown_body"].lower()
    assert "sustainability criticism" in package["executive_summary"].lower()



def test_graph_entities_for_preparation_filters_context_nodes() -> None:
    """Preparation should prioritize actor-like entities over every context node in the graph."""
    payload = {
        "nodes": [
            {"uuid": "brand_1", "name": "Ralph Lauren Corporation", "label": "Brand", "summary": "Luxury brand"},
            {"uuid": "person_1", "name": "Ralph Lauren", "label": "Person", "summary": "Founder"},
            {"uuid": "segment_1", "name": "Gen Z", "label": "Audience Segment", "summary": "Target audience"},
            {"uuid": "platform_1", "name": "TikTok", "label": "Platform", "summary": "Viral channel"},
            {"uuid": "event_1", "name": "Met Gala", "label": "Event", "summary": "Fashion event"},
            {"uuid": "location_1", "name": "London", "label": "Location", "summary": "Pop-up city"},
        ],
        "edges": [
            {"uuid": "e1", "source_uuid": "brand_1", "target_uuid": "person_1", "relation_type": "founded_by"},
            {"uuid": "e2", "source_uuid": "brand_1", "target_uuid": "segment_1", "relation_type": "targets"},
            {"uuid": "e3", "source_uuid": "brand_1", "target_uuid": "platform_1", "relation_type": "amplifies_on"},
            {"uuid": "e4", "source_uuid": "brand_1", "target_uuid": "event_1", "relation_type": "appears_in"},
            {"uuid": "e5", "source_uuid": "brand_1", "target_uuid": "location_1", "relation_type": "located_in"},
        ],
    }

    entities = graph_entities_for_preparation(
        payload,
        scenario_text="Simulate how Gen Z reacts to Ralph Lauren's TikTok push and whether it becomes loyalty.",
    )

    names = [item["name"] for item in entities["entities"]]
    assert "Ralph Lauren Corporation" in names
    assert "Ralph Lauren" in names
    assert "Gen Z" in names
    assert "London" not in names
    assert entities["filtered_count"] < entities["total_count"]


def test_graph_entities_for_preparation_keeps_institutional_nodes() -> None:
    """Preparation should retain organizational and campaign actors that drive scenario behavior."""
    payload = {
        "nodes": [
            {"uuid": "brand_1", "name": "Ralph Lauren Corporation", "label": "Brand", "summary": "Luxury brand"},
            {"uuid": "org_1", "name": "Sustainability Office", "label": "Organization", "summary": "Internal team reviewing claims"},
            {"uuid": "campaign_1", "name": "Holiday Heritage Campaign", "label": "Campaign", "summary": "Seasonal campaign"},
            {"uuid": "creator_1", "name": "Creator Partners", "label": "Creator Group", "summary": "Creators shaping reach"},
            {"uuid": "theme_1", "name": "Brand Relevance", "label": "Theme", "summary": "Theme node"},
        ],
        "edges": [
            {"uuid": "e1", "source_uuid": "org_1", "target_uuid": "brand_1", "relation_type": "advises"},
            {"uuid": "e2", "source_uuid": "campaign_1", "target_uuid": "brand_1", "relation_type": "amplifies"},
            {"uuid": "e3", "source_uuid": "creator_1", "target_uuid": "campaign_1", "relation_type": "supports"},
            {"uuid": "e4", "source_uuid": "theme_1", "target_uuid": "brand_1", "relation_type": "describes"},
        ],
    }

    entities = graph_entities_for_preparation(
        payload,
        scenario_text="Simulate how creator reaction and campaign positioning affect Ralph Lauren among younger audiences.",
    )

    names = [item["name"] for item in entities["entities"]]
    assert "Sustainability Office" in names
    assert "Holiday Heritage Campaign" in names
    assert "Creator Partners" in names
    assert "Brand Relevance" not in names


def test_graph_entities_for_preparation_infers_generic_actor_entities() -> None:
    """Generic Graphiti entities should be promoted into actor-like simulation nodes when they look social."""
    payload = {
        "nodes": [
            {"uuid": "generic_1", "name": "Haworth Lifestyle Design", "label": "Entity", "summary": "Design partner expanding the brand's home line"},
            {"uuid": "generic_2", "name": "Belk", "label": "Entity", "summary": "Retail partner carrying the brand"},
            {"uuid": "generic_3", "name": "France", "label": "Entity", "summary": "Country market"},
            {"uuid": "brand_1", "name": "Ralph Lauren Corporation", "label": "Luxury Brand", "summary": "Luxury brand"},
        ],
        "edges": [
            {"uuid": "e1", "source_uuid": "generic_1", "target_uuid": "brand_1", "relation_type": "partners_with"},
            {"uuid": "e2", "source_uuid": "generic_2", "target_uuid": "brand_1", "relation_type": "retails"},
            {"uuid": "e3", "source_uuid": "generic_3", "target_uuid": "brand_1", "relation_type": "market_for"},
        ],
    }

    entities = graph_entities_for_preparation(
        payload,
        scenario_text="Simulate how retail and partner signals affect Ralph Lauren loyalty.",
    )

    by_name = {item["name"]: item for item in entities["entities"]}
    assert by_name["Haworth Lifestyle Design"]["labels"] == ["Organization"]
    assert by_name["Belk"]["labels"] == ["Organization"]
    assert "France" not in by_name


def test_build_glass_profiles_honors_expected_count_cap() -> None:
    """Graph-linked profiles should respect the requested target count instead of expanding to every node."""
    project = Project(name="Parity Project", scenario_brief="Test scenario about pricing and loyalty.")
    entities = [
        {
            "uuid": f"entity_{index}",
            "name": f"Entity {index}",
            "labels": ["Brand" if index % 2 == 0 else "Audience Segment"],
            "summary": "A graph-backed entity.",
            "attributes": {},
            "related_edges": [{"edge_name": "targets"} for _ in range(3)],
            "related_nodes": [{"name": "Gen Z", "labels": ["Audience Segment"], "summary": "Audience", "attributes": {}}],
        }
        for index in range(30)
    ]

    payload = build_glass_profiles(
        project=project,
        source_digest="pricing, loyalty, authenticity",
        ontology={"entity_types": [{"name": "Brand"}, {"name": "Audience Segment"}]},
        expected_count=12,
        entities=entities,
        llm=None,
    )

    assert payload["expected_count"] == 12
    assert len(payload["reddit_profiles"]) == 12


def test_build_glass_profiles_do_not_pad_beyond_graph_entities() -> None:
    """Graph-backed preparation should not invent extra personas when the filtered entity set is small."""
    project = Project(name="Parity Project", scenario_brief="Test scenario about pricing and loyalty.")
    entities = [
        {
            "uuid": f"entity_{index}",
            "name": f"Entity {index}",
            "labels": ["Brand" if index % 2 == 0 else "Audience Segment"],
            "summary": "A graph-backed entity.",
            "attributes": {},
            "related_edges": [{"edge_name": "targets"} for _ in range(3)],
            "related_nodes": [{"name": "Gen Z", "labels": ["Audience Segment"], "summary": "Audience", "attributes": {}}],
        }
        for index in range(4)
    ]

    payload = build_glass_profiles(
        project=project,
        source_digest="pricing, loyalty, authenticity",
        ontology={"entity_types": [{"name": "Brand"}, {"name": "Audience Segment"}]},
        expected_count=12,
        entities=entities,
        llm=None,
    )

    assert payload["expected_count"] == 4
    assert len(payload["reddit_profiles"]) == 4
    assert {item["source_entity_uuid"] for item in payload["reddit_profiles"]} == {item["uuid"] for item in entities}


def test_build_glass_profiles_supports_large_graph_linked_sets() -> None:
    """Graph-backed preparation should no longer hard-cap at the old small persona limit."""
    project = Project(name="Parity Project", scenario_brief="Test scenario about pricing and loyalty.")
    entities = [
        {
            "uuid": f"entity_{index}",
            "name": f"Entity {index}",
            "labels": ["Brand" if index % 3 == 0 else "Audience Segment"],
            "summary": "A graph-backed entity.",
            "attributes": {},
            "related_edges": [{"edge_name": "targets"} for _ in range(3)],
            "related_nodes": [{"name": "Gen Z", "labels": ["Audience Segment"], "summary": "Audience", "attributes": {}}],
            "centrality_score": 100 - index,
        }
        for index in range(72)
    ]

    payload = build_glass_profiles(
        project=project,
        source_digest="pricing, loyalty, authenticity",
        ontology={"entity_types": [{"name": "Brand"}, {"name": "Audience Segment"}]},
        expected_count=72,
        entities=entities,
        llm=None,
    )

    assert payload["expected_count"] == 72
    assert len(payload["reddit_profiles"]) == 72


def test_build_glass_ontology_prefers_social_simulation_mode_for_brand_reaction_prompts() -> None:
    """Brand-reaction prompts should produce a role-oriented simulation ontology."""
    ontology, _summary = build_glass_ontology(
        None,
        project_name="Unnamed Project",
        requirement="Simulate how Gen Z reacts to Ralph Lauren on Twitter and Reddit and whether the buzz becomes loyalty.",
        additional_context="Focus on creators, media pressure, competitors, and institutional scrutiny.",
        source_texts=["Ralph Lauren faces media coverage, influencer reaction, and competitor comparisons."],
    )

    names = {item["name"] for item in ontology["entity_types"]}
    assert "Luxury Brand" in names
    assert "Fashion Influencer" in names
    assert "Consumer Cohort" in names
    assert "Fashion Media Outlet" in names


def test_build_glass_ontology_rejects_broad_llm_brand_schema_for_social_brand_prompts() -> None:
    """Social-brand scenarios should not accept a broad brand taxonomy from the LLM path."""
    llm = StubJsonLLM(
        {
            "analysis_summary": "Prepared a brand-focused ontology.",
            "description": "Brand taxonomy",
            "entity_types": [
                {"name": "Brand", "description": "Brand"},
                {"name": "Product Line", "description": "Line"},
                {"name": "Person", "description": "Person"},
                {"name": "Audience Segment", "description": "Audience"},
                {"name": "Competitor Brand", "description": "Competitor"},
                {"name": "Media Outlet", "description": "Media"},
                {"name": "Platform", "description": "Platform"},
                {"name": "Event", "description": "Event"},
            ],
            "edge_types": [
                {
                    "name": "competes_with",
                    "description": "Competition",
                    "source_targets": [{"source": "Brand", "target": "Competitor Brand"}],
                },
                {
                    "name": "targets",
                    "description": "Targets audience",
                    "source_targets": [{"source": "Brand", "target": "Audience Segment"}],
                },
                {
                    "name": "covers",
                    "description": "Media coverage",
                    "source_targets": [{"source": "Media Outlet", "target": "Brand"}],
                },
                {
                    "name": "appears_in",
                    "description": "Appears in event",
                    "source_targets": [{"source": "Brand", "target": "Event"}],
                },
                {
                    "name": "amplifies_on",
                    "description": "Amplifies on platform",
                    "source_targets": [{"source": "Media Outlet", "target": "Platform"}],
                },
            ],
        }
    )

    ontology, summary = build_glass_ontology(
        llm,
        project_name="Ralph Lauren Gen Z Loyalty Scenario",
        requirement="Simulate how Gen Z reacts to Ralph Lauren on Twitter and Reddit and whether the buzz becomes loyalty.",
        additional_context="Focus on creators, media pressure, competitors, and institutional scrutiny.",
        source_texts=["Ralph Lauren faces media coverage, influencer reaction, and competitor comparisons."],
    )

    names = {item["name"] for item in ontology["entity_types"]}
    assert "Luxury Brand" in names
    assert "Fashion Influencer" in names
    assert "Consumer Cohort" in names
    assert "Brand" not in names
    assert summary.startswith("Prepared a compact social-simulation ontology")


def test_detect_social_brand_simulation_submode_identifies_market_expansion() -> None:
    """China expansion prompts should route to the market-expansion ontology path."""
    prompt = (
        "Predict social media reactions to Ralph Lauren's expansion into Tier 1 and Tier 2 Chinese cities "
        "with new flagship stores and WeChat commerce, including western market analysts, geopolitical commentators, "
        "domestic brand advocates, and sustainability critics."
    )

    assert detect_social_brand_simulation_submode(prompt) == "market_expansion"


def test_build_glass_ontology_specializes_market_expansion_prompts() -> None:
    """Market-expansion prompts should no longer collapse to the generic brand-social ontology."""
    ontology, summary = build_glass_ontology(
        None,
        project_name="Unnamed Project",
        requirement=(
            "Predict social media reactions to Ralph Lauren's aggressive expansion into Tier 1 and Tier 2 Chinese cities "
            "with new flagship stores and WeChat commerce."
        ),
        additional_context=(
            "Simulate western market analysts, geopolitical commentators, domestic brand advocates, "
            "sustainability critics, and Chinese luxury consumers."
        ),
        source_texts=["Ralph Lauren, Li-Ning, and Anta are competing for attention as geopolitical scrutiny rises."],
    )

    names = {item["name"] for item in ontology["entity_types"]}
    assert names == {
        "Luxury Brand",
        "Luxury Consumer",
        "Market Analyst",
        "Competitor Brand",
        "Sustainability Activist",
        "Person",
        "Organization",
    }
    assert summary.startswith("Prepared a market-expansion ontology")


def test_graph_entities_for_preparation_uses_market_expansion_role_caps() -> None:
    """Market-expansion prompts should keep a focused actor mix instead of the generic social-brand cast."""
    payload = {
        "nodes": [
            {"uuid": "brand_1", "name": "Ralph Lauren Corporation", "label": "Fashion Brand", "summary": "American heritage brand expanding in China"},
            {"uuid": "brand_2", "name": "Li-Ning", "label": "Entity", "summary": "Domestic sportswear brand championed by Chinese consumers"},
            {"uuid": "brand_3", "name": "Anta", "label": "Entity", "summary": "Domestic competitor benefiting from nationalist sentiment"},
            {"uuid": "analyst_1", "name": "Western retail analysts", "label": "Entity", "summary": "Market analysts tracking pricing power and demand"},
            {"uuid": "commentator_1", "name": "Geopolitical commentators", "label": "Entity", "summary": "Commentators linking the move to geopolitical backlash"},
            {"uuid": "activist_1", "name": "Sustainability critics", "label": "Entity", "summary": "Critics questioning sourcing and labor proof"},
            {"uuid": "person_1", "name": "Chinese luxury shoppers", "label": "Entity", "summary": "Consumers weighing heritage appeal and WeChat convenience"},
            {"uuid": "org_1", "name": "WeChat", "label": "Location", "summary": "Commerce platform and local distribution surface in the China market"},
            {"uuid": "location_1", "name": "Shanghai", "label": "Location", "summary": "Tier 1 city"},
        ],
        "edges": [
            {"uuid": "e1", "source_uuid": "brand_1", "target_uuid": "brand_2", "relation_type": "competes_with"},
            {"uuid": "e2", "source_uuid": "brand_1", "target_uuid": "brand_3", "relation_type": "competes_with"},
            {"uuid": "e3", "source_uuid": "analyst_1", "target_uuid": "brand_1", "relation_type": "comments_on"},
            {"uuid": "e4", "source_uuid": "commentator_1", "target_uuid": "brand_1", "relation_type": "questions"},
            {"uuid": "e5", "source_uuid": "activist_1", "target_uuid": "brand_1", "relation_type": "questions"},
            {"uuid": "e6", "source_uuid": "person_1", "target_uuid": "brand_1", "relation_type": "reacts_to"},
            {"uuid": "e7", "source_uuid": "org_1", "target_uuid": "brand_1", "relation_type": "expands_in"},
            {"uuid": "e8", "source_uuid": "location_1", "target_uuid": "brand_1", "relation_type": "market_for"},
        ],
    }

    entities = graph_entities_for_preparation(
        payload,
        scenario_text=(
            "Predict western and Chinese social reactions to Ralph Lauren's China expansion with WeChat commerce, "
            "including market analysts, geopolitical commentators, sustainability critics, and domestic brand advocates."
        ),
    )

    by_name = {item["name"]: item for item in entities["entities"]}
    assert by_name["Li-Ning"]["labels"] == ["Competitor Brand"]
    assert by_name["Anta"]["labels"] == ["Competitor Brand"]
    assert by_name["Western retail analysts"]["labels"] == ["Market Analyst"]
    assert by_name["Geopolitical commentators"]["labels"] == ["Organization"]
    assert by_name["Sustainability critics"]["labels"] == ["Sustainability Activist"]
    assert by_name["Chinese luxury shoppers"]["labels"] == ["Luxury Consumer"]
    assert by_name["WeChat"]["labels"] == ["Organization"]
    assert "Shanghai" not in by_name
    assert entities["filtered_count"] <= 64


def test_graph_entities_for_preparation_specializes_market_expansion_fallback_organizations() -> None:
    """Broad Organization labels should be specialized before market-expansion caps are applied."""
    payload = {
        "nodes": [
            {"uuid": "brand_1", "name": "Ralph Lauren Corporation", "label": "Fashion Brand", "summary": "American heritage brand expanding in China"},
            {"uuid": "analyst_1", "name": "Western retail analysts", "label": "Organization", "summary": "Analysts tracking pricing power and demand"},
            {"uuid": "commentator_1", "name": "State media commentators", "label": "Organization", "summary": "Commentators linking expansion to nationalist backlash"},
            {"uuid": "activist_1", "name": "Sustainability watchdogs", "label": "Organization", "summary": "Critics questioning sourcing and labor proof"},
            {"uuid": "platform_1", "name": "WeChat", "label": "Organization", "summary": "Commerce platform and local distribution surface in the China market"},
        ],
        "edges": [
            {"uuid": "e1", "source_uuid": "analyst_1", "target_uuid": "brand_1", "relation_type": "comments_on"},
            {"uuid": "e2", "source_uuid": "commentator_1", "target_uuid": "brand_1", "relation_type": "questions"},
            {"uuid": "e3", "source_uuid": "activist_1", "target_uuid": "brand_1", "relation_type": "questions"},
            {"uuid": "e4", "source_uuid": "platform_1", "target_uuid": "brand_1", "relation_type": "expands_in"},
        ],
    }

    entities = graph_entities_for_preparation(
        payload,
        scenario_text=(
            "Predict western and Chinese social reactions to Ralph Lauren's China expansion with WeChat commerce, "
            "including market analysts, geopolitical commentators, sustainability critics, and domestic brand advocates."
        ),
    )

    by_name = {item["name"]: item for item in entities["entities"]}
    assert by_name["Western retail analysts"]["labels"] == ["Market Analyst"]
    assert by_name["State media commentators"]["labels"] == ["Organization"]
    assert by_name["Sustainability watchdogs"]["labels"] == ["Sustainability Activist"]
    assert by_name["WeChat"]["labels"] == ["Organization"]


def test_graph_entities_for_preparation_keeps_market_expansion_stable_labels() -> None:
    """Stable Organization and Person nodes should not be reclassified into brands on weak Ralph Lauren summary mentions."""
    payload = {
        "nodes": [
            {"uuid": "brand_1", "name": "Ralph Lauren Corporation", "label": "Fashion Brand", "summary": "American heritage brand expanding in China"},
            {"uuid": "platform_1", "name": "WeChat", "label": "Organization", "summary": "Platform used by Ralph Lauren to support local commerce in China"},
            {"uuid": "partner_1", "name": "Haworth Lifestyle Design", "label": "Organization", "summary": "Design partner helping Ralph Lauren expand the home category"},
            {"uuid": "person_1", "name": "David Lauren", "label": "Person", "summary": "Executive helping Ralph Lauren shape digital storytelling"},
            {"uuid": "location_1", "name": "London", "label": "Consumer Cohort", "summary": "City market mentioned in the expansion brief"},
        ],
        "edges": [
            {"uuid": "e1", "source_uuid": "platform_1", "target_uuid": "brand_1", "relation_type": "expands_in"},
            {"uuid": "e2", "source_uuid": "partner_1", "target_uuid": "brand_1", "relation_type": "partners_with"},
            {"uuid": "e3", "source_uuid": "person_1", "target_uuid": "brand_1", "relation_type": "represents"},
            {"uuid": "e4", "source_uuid": "location_1", "target_uuid": "brand_1", "relation_type": "market_for"},
        ],
    }

    entities = graph_entities_for_preparation(
        payload,
        scenario_text=(
            "Predict reactions to Ralph Lauren's China expansion with WeChat commerce, including domestic competitors, "
            "market analysts, and geopolitical commentary."
        ),
    )

    by_name = {item["name"]: item for item in entities["entities"]}
    assert by_name["WeChat"]["labels"] == ["Organization"]
    assert by_name["Haworth Lifestyle Design"]["labels"] == ["Organization"]
    assert by_name["David Lauren"]["labels"] == ["Person"]
    assert "London" not in by_name


def test_build_glass_simulation_config_scales_preview_activity_for_larger_casts() -> None:
    """Larger casts should still seed multiple turns without using the older overactive preview envelope."""
    project = Project(name="Parity Project", scenario_brief="Simulate how Gen Z reacts to a luxury brand campaign across Twitter and Reddit.")
    profiles = [
        {
            "agent_id": f"agent_{index:03d}",
            "oasis_user_id": index,
            "name": f"Agent {index}",
            "entity_type": "Consumer Cohort" if index % 3 == 0 else "Fashion Media Outlet" if index % 3 == 1 else "Competitor Brand",
            "interested_topics": ["Gen Z Authenticity", "Premium Value Debate", "Luxury Competition"],
            "profession": "Analyst",
            "narrative_role": "amplifier",
            "platform_behavior": "Posts actively when the narrative turns.",
            "trust_lens": "Judges the scenario through authenticity and value.",
            "source_entity_uuid": f"entity_{index:03d}",
            "follower_count": 1000 + (index * 20),
        }
        for index in range(42)
    ]
    entities = [
        {
            "uuid": f"entity_{index:03d}",
            "name": f"Entity {index}",
            "labels": [profiles[index]["entity_type"]],
            "summary": "Graph-backed entity context.",
            "attributes": {},
            "related_edges": [{"edge_name": "reacts_to"} for _ in range(4)],
            "related_nodes": [],
        }
        for index in range(42)
    ]

    config = build_glass_simulation_config(
        project=project,
        source_digest="Gen Z, loyalty, pricing, influencers, competitors",
        profiles=profiles,
        entities=entities,
        llm=None,
    )

    assert 4 <= config["time_config"]["agents_per_hour_min"] <= 6
    assert 8 <= config["time_config"]["agents_per_hour_max"] <= 10
    assert config["time_config"]["peak_activity_multiplier"] <= 1.65
    assert config["time_config"]["work_activity_multiplier"] <= 0.8
    assert config["time_config"]["off_peak_activity_multiplier"] <= 0.08
    assert len(config["event_config"]["initial_posts"]) >= 8
    assert len(config["event_config"]["scheduled_events"]) >= 4


def test_build_glass_report_package_derives_non_generic_title() -> None:
    """Report titles should use the scenario when the saved project name is blank."""
    project = Project(name="Unnamed Project", scenario_brief="Simulate how Gen Z reacts to Ralph Lauren and whether Christmas aesthetic buzz becomes loyalty.")
    package = build_glass_report_package(
        project=project,
        focus="Decision support",
        config={"event_config": {"hot_topics": ["Gen Z Loyalty", "Brand Authenticity"], "scheduled_events": []}, "agent_configs": []},
        actions=[],
        interviews=[],
        posts_by_platform={"twitter": [], "reddit": []},
        comments=[],
        graph_metadata={"node_count": 0, "edge_count": 0, "entity_types": []},
        graph_facts=[],
        llm=None,
    )

    assert package["title"] == "Future Prediction Report: Ralph Lauren Gen Z Loyalty Simulation"


def test_build_glass_simulation_config_keeps_market_expansion_topics_specific() -> None:
    """Market-expansion configs should stay anchored to localization and competition topics."""
    project = Project(
        name="Parity Project",
        scenario_brief=(
            "Predict social media reactions to Ralph Lauren's aggressive expansion into Tier 1 and Tier 2 Chinese cities "
            "with new flagship stores and WeChat commerce. Simulate Chinese luxury consumers, domestic brand advocates, "
            "Western market analysts, geopolitical commentators, sustainability critics, and fashion journalists."
        ),
    )
    profiles = [
        {
            "agent_id": f"agent_{index:03d}",
            "oasis_user_id": index,
            "name": name,
            "entity_type": entity_type,
            "interested_topics": topics,
            "profession": profession,
            "narrative_role": "market watcher",
            "platform_behavior": "Posts when the China expansion narrative turns.",
            "trust_lens": "Judges whether market entry builds demand or backlash.",
            "source_entity_uuid": f"entity_{index:03d}",
            "follower_count": 2000 + (index * 100),
        }
        for index, (name, entity_type, topics, profession) in enumerate(
            [
                ("Ralph Lauren Corporation", "Fashion Brand", ["Market Localization", "American Heritage Branding"], "Brand Marketing Lead"),
                ("Li-Ning", "Competitor Brand", ["Domestic Brand Competition", "Competitive Positioning"], "Competitor Brand Lead"),
                ("Chinese luxury shoppers", "Consumer Cohort", ["Market Localization", "WeChat Commerce Strategy"], "Consumer Research Lead"),
                ("Western retail analysts", "Market Analyst", ["Competitive Positioning", "Geopolitical Risk"], "Market Analyst"),
                ("WeChat", "Organization", ["WeChat Commerce Strategy", "Market Localization"], "Platform Strategist"),
                ("State media commentators", "Organization", ["Geopolitical Risk", "American Heritage Branding"], "Media Group"),
            ]
        )
    ]
    entities = [
        {
            "uuid": f"entity_{index:03d}",
            "name": profile["name"],
            "labels": [profile["entity_type"]],
            "summary": f"{profile['name']} shapes China expansion reaction through {', '.join(profile['interested_topics'])}.",
            "attributes": {},
            "related_edges": [{"edge_name": "comments_on"} for _ in range(3)],
            "related_nodes": [],
        }
        for index, profile in enumerate(profiles)
    ]

    config = build_glass_simulation_config(
        project=project,
        source_digest="Ralph Lauren, China, WeChat, Li-Ning, Anta, geopolitical backlash, domestic brand advocates",
        profiles=profiles,
        entities=entities,
        llm=None,
    )

    hot_topics = config["event_config"]["hot_topics"]
    assert "Market Localization" in hot_topics
    assert "WeChat Commerce Strategy" in hot_topics
    assert "Domestic Brand Competition" in hot_topics
    assert "Geopolitical Risk" in hot_topics
    assert "Holiday Campaign Virality" not in hot_topics
    assert "Brand Relevance" not in hot_topics
    assert "Pricing vs Fast Fashion" not in hot_topics
    assert "Premium Value Debate" not in hot_topics
    assert config["time_config"]["agents_per_hour_min"] >= 3
    assert config["time_config"]["agents_per_hour_max"] >= 5
    assert len(config["event_config"]["initial_posts"]) >= 6


def test_extract_named_entity_candidates_skips_heading_fragments() -> None:
    """Named-entity extraction should prefer real entities over markdown headings and UI-like labels."""
    text = """
    # Ralph Lauren Corporation - Marketing Strategy & Brand Overview
    ## Company Profile
    Ralph Lauren Corporation partnered with Haworth Lifestyle Design and expanded on WeChat.
    """

    candidates = extract_named_entity_candidates(text, limit=10)

    assert "Ralph Lauren Corporation" in candidates
    assert "Haworth Lifestyle Design" in candidates
    assert "WeChat" in candidates
    assert "Marketing Strategy" not in candidates
    assert "Brand Overview" not in candidates
    assert "Company Profile" not in candidates


def test_build_graphiti_extraction_instructions_sample_across_document() -> None:
    """Graphiti instructions should preserve later-chunk entities instead of only early document names."""
    text = Path("../seed_documents/ralph_lauren_marketing_brief.md").read_text()
    instructions = build_graphiti_extraction_instructions(
        project_name="Ralph Lauren Gen Z Loyalty Scenario",
        requirement=(
            "Simulate how Gen Z consumers on Twitter and Reddit react to Ralph Lauren's cultural relevance push."
        ),
        additional_context="",
        source_texts=[text],
        ontology={
            "entity_types": [{"name": "Brand"}, {"name": "Product Line"}, {"name": "Person"}],
            "edge_types": [{"name": "launches"}, {"name": "appears_in"}],
        },
    )

    assert "Haworth Lifestyle Design" in instructions
    assert "Club Monaco" in instructions
    assert "Company Profile" not in instructions


def test_load_graph_payload_normalizes_cached_generic_locations(tmp_path) -> None:
    """Older cached graph payloads should refresh obvious geography nodes away from the raw Entity label."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'personagraph-test.db'}",
        data_dir=str(tmp_path / "data"),
    )
    save_graph_payload(
        settings,
        "graph_1",
        {
            "nodes": [
                {
                    "uuid": "node_1",
                    "name": "Tokyo",
                    "label": "Entity",
                    "labels": ["Entity"],
                    "summary": "",
                    "attributes": {},
                }
            ],
            "edges": [],
            "metadata": {"entity_types": ["Entity"]},
        },
    )

    payload = load_graph_payload(settings, "graph_1")

    assert payload["nodes"][0]["label"] == "Location"
    assert payload["nodes"][0]["labels"] == ["Location"]
    assert payload["metadata"]["entity_types"] == ["Location"]


def test_compact_graph_payload_for_display_limits_dense_relation_families() -> None:
    """Canvas payloads should collapse dense raw Graphiti relation families into a thinner display graph."""
    nodes = [
        {"uuid": "brand_a", "name": "Ralph Lauren Corporation", "label": "Fashion Brand"},
        {"uuid": "brand_b", "name": "Li-Ning", "label": "Fashion Brand"},
        {"uuid": "brand_c", "name": "Anta", "label": "Fashion Brand"},
        {"uuid": "brand_d", "name": "Burberry", "label": "Fashion Brand"},
        {"uuid": "org_a", "name": "WeChat", "label": "Organization"},
        {"uuid": "org_b", "name": "Instagram", "label": "Organization"},
        {"uuid": "org_c", "name": "Richemont", "label": "Organization"},
        {"uuid": "person_a", "name": "Patrice Louvet", "label": "Person"},
    ]
    edges = []
    for index in range(12):
        source_uuid = ["brand_a", "brand_b", "brand_c", "brand_d"][index % 4]
        target_uuid = ["brand_b", "brand_c", "brand_d", "brand_a"][index % 4]
        edges.append(
            {
                "uuid": f"compete_{index}",
                "source_uuid": source_uuid,
                "target_uuid": target_uuid,
                "relation_type": "competes_with",
                "fact": "Brands compete for local relevance.",
            }
        )
    for index, relation in enumerate(
        [
            "expands_in",
            "EXPANDS_IN",
            "OPERATES_POP_UP_IN",
            "USES_PLATFORM",
            "PARTNERED_WITH",
            "LISTED_ON",
            "HEADQUARTERED_IN",
            "LAUNCHED_STORES_WITH",
            "expands_in",
            "EXPANDS_IN",
            "USES_PLATFORM",
            "PARTNERED_WITH",
        ]
    ):
        edges.append(
            {
                "uuid": f"expand_{index}",
                "source_uuid": "brand_a",
                "target_uuid": ["org_a", "org_b", "org_c"][index % 3],
                "relation_type": relation,
                "fact": "Brand expands or activates through an organizational surface.",
            }
        )
    for index, relation in enumerate(["HOLDS_POSITION", "FOUNDED", "PREVIOUSLY_WORKED_AT", "WORKS_FOR"] * 3):
        edges.append(
            {
                "uuid": f"rep_{index}",
                "source_uuid": "person_a",
                "target_uuid": "brand_a" if index % 2 == 0 else "org_c",
                "relation_type": relation,
                "fact": "Executive role relation.",
            }
        )

    compacted = compact_graph_payload_for_display(
        {
            "nodes": nodes,
            "edges": edges,
            "metadata": {"node_count": len(nodes), "edge_count": len(edges), "entity_types": ["Fashion Brand", "Organization", "Person"]},
        }
    )

    relation_counts = {}
    for edge in compacted["edges"]:
        relation = edge["relation_type"]
        relation_counts[relation] = relation_counts.get(relation, 0) + 1
    node_ids = {item["uuid"] for item in compacted["nodes"]}
    edge_node_ids = {item["source_uuid"] for item in compacted["edges"]} | {item["target_uuid"] for item in compacted["edges"]}
    assert compacted["metadata"]["raw_node_count"] == len(nodes)
    assert compacted["metadata"]["raw_edge_count"] == len(edges)
    assert compacted["metadata"]["node_count"] == len(compacted["nodes"])
    assert compacted["metadata"]["edge_count"] == len(compacted["edges"])
    assert compacted["metadata"]["edge_count"] < len(edges)
    assert node_ids == edge_node_ids
    assert relation_counts["competes_with"] <= 16
    assert relation_counts["expands_in"] <= 22
    assert relation_counts["represents"] <= 12


def test_build_glass_report_package_persists_named_entity_inventory_from_broad_graph_labels() -> None:
    """Report packaging should surface concrete entities even when the raw graph uses broad fallback labels."""
    project = Project(
        name="Ralph Lauren Gen Z Loyalty Scenario",
        scenario_brief="Simulate whether Ralph Lauren's viral Christmas aesthetic becomes durable Gen Z loyalty.",
    )

    package = build_glass_report_package(
        project=project,
        focus="Decision support and scenario implications",
        config={"event_config": {"hot_topics": ["Gen Z Loyalty", "Pricing Sensitivity"], "scheduled_events": []}, "agent_configs": []},
        actions=[
            {
                "round_num": 1,
                "platform": "twitter",
                "agent_id": "agent_001",
                "agent_name": "Lacoste",
                "action_type": "CREATE_POST",
                "content": "Pricing pressure is still the biggest barrier to durable loyalty.",
            }
        ],
        interviews=[
            {
                "agent_id": "agent_002",
                "agent_name": "Instagram",
                "response": "The campaign travels fast, but trust only sticks if price and authenticity are defended.",
            }
        ],
        posts_by_platform={
            "twitter": [{"content": "TikTok and Instagram turned the aesthetic into a fast global signal.", "score": 12}],
            "reddit": [{"title": "Europe and Japan still question the price", "body": "Heritage alone is not enough.", "score": 9}],
        },
        comments=[{"content": "London and Tokyo reacted, but conversion is still uncertain."}],
        graph_metadata={
            "node_count": 8,
            "edge_count": 6,
            "entity_types": ["Luxury Brand", "Organization", "Consumer Cohort", "Fashion Media Outlet"],
            "nodes": [
                {"uuid": "brand_1", "name": "Ralph Lauren Corporation", "label": "Luxury Brand", "summary": "Lead brand"},
                {"uuid": "brand_2", "name": "Double RL (RRL)", "label": "Luxury Brand", "summary": "Sub-line"},
                {"uuid": "platform_1", "name": "TikTok", "label": "Fashion Media Outlet", "summary": "Fast-moving social platform"},
                {"uuid": "platform_2", "name": "Instagram", "label": "Fashion Media Outlet", "summary": "Image-led social platform"},
                {"uuid": "location_1", "name": "Japan", "label": "Organization", "summary": "Country market with strong engagement"},
                {"uuid": "location_2", "name": "London", "label": "Organization", "summary": "City market for flagship activity"},
                {"uuid": "event_1", "name": "Wimbledon", "label": "Organization", "summary": "Cultural event association"},
                {"uuid": "audience_1", "name": "Gen Z", "label": "Consumer Cohort", "summary": "Young audience segment"},
            ],
        },
        graph_facts=[
            "Ralph Lauren Corporation mentions TikTok.",
            "Ralph Lauren Corporation mentions Japan.",
        ],
        llm=None,
    )

    evidence = package["evidence_summary"]
    named_entities = evidence["graph"]["named_entities"]
    assert "Ralph Lauren Corporation" in named_entities["brands"]
    assert "Double RL (RRL)" in named_entities["products"]
    assert "TikTok" in named_entities["platforms"]
    assert "Japan" in named_entities["locations"]
    assert "Wimbledon" in named_entities["events"]
    assert "Key named entities in scope: Ralph Lauren Corporation" in package["markdown_body"]


def test_build_glass_report_chat_response_strips_hidden_reasoning_but_keeps_depth() -> None:
    """Report chat should remove hidden reasoning artifacts without collapsing to a one-line answer."""
    llm = StubTextLLM(
        "<think>I should plan the answer first.</think>\n\n"
        "Conclusion: This looks more like a fleeting viral moment than durable Gen Z loyalty because pricing skepticism and authenticity checks harden once the conversation leaves first-wave hype.\n\n"
        "The strongest reasons are that TikTok and Instagram amplified attention faster than conversion, competitors such as Lacoste stayed active in the same narrative, and markets like Japan kept the discussion focused on value rather than repeat purchase intent."
    )
    project = Project(name="Ralph Lauren", scenario_brief="Test brand relevance scenario.")
    simulation = Simulation(project_id="proj_1", summary="Ten-round preview run")
    report = Report(simulation_id="sim_1", executive_summary="The run points to fleeting momentum rather than durable loyalty.")

    answer, sources, tool_calls = build_glass_report_chat_response(
        llm,
        project=project,
        simulation=simulation,
        report=report,
        message="Is this durable loyalty or a fleeting viral moment?",
        sections=[
            {
                "title": "Executive Summary",
                "content": "The run points to a fleeting moment because pricing skepticism and authenticity scrutiny keep returning.",
            },
            {
                "title": "Platform Split: Velocity Versus Scrutiny",
                "content": "Twitter moved first, while Reddit pushed value and trust checks harder.",
            },
        ],
        evidence={
            "topics": ["Pricing Sensitivity", "Gen Z Authenticity"],
            "graph": {
                "node_count": 59,
                "edge_count": 32,
                "named_entities": {
                    "brands": ["Ralph Lauren Corporation", "Lacoste"],
                    "platforms": ["TikTok", "Instagram"],
                    "locations": ["Japan", "London"],
                },
            },
            "runtime": {
                "actions": 121,
                "twitter_posts": 26,
                "reddit_posts": 5,
                "comments": 14,
                "quotes": ["TikTok and Instagram turned the aesthetic into a fast global signal."],
            },
            "interviews": [
                {"agent_name": "Instagram", "response": "Attention came easily, but trust still needs proof."}
            ],
        },
    )

    assert "<think>" not in answer
    assert "Conclusion:" in answer
    assert "TikTok" in answer
    assert len(answer) > 160
    assert any("Named entities:" in item for item in sources)
    assert {item["name"] for item in tool_calls} >= {"report_context", "report_outline", "report_sections", "report_evidence"}


def test_build_glass_report_chat_response_discards_prompt_scaffolding_preamble() -> None:
    """Report chat should remove prompt scaffolding preambles and keep only the grounded analyst answer."""
    llm = StubTextLLM(
        "Analyze the Request:\n"
        "Role: Senior Analyst\n"
        "Available Evidence:\n"
        "Graph stats: 59 nodes / 24 edges\n"
        "Runtime stats: 128 total actions\n"
        "Instructions: Write two short paragraphs.\n\n"
        "Conclusion: This still looks more like a fleeting viral moment than durable loyalty because attention outran trust.\n\n"
        "The strongest reasons are that TikTok, Instagram, and Japan kept the conversation focused on visibility and value checks, while Lacoste stayed active enough to prevent Ralph Lauren from owning the narrative."
    )
    project = Project(name="Ralph Lauren", scenario_brief="Test brand relevance scenario.")
    simulation = Simulation(project_id="proj_1", summary="Ten-round preview run")
    report = Report(simulation_id="sim_1", executive_summary="The run points to fleeting momentum rather than durable loyalty.")

    answer, _sources, _tool_calls = build_glass_report_chat_response(
        llm,
        project=project,
        simulation=simulation,
        report=report,
        message="Does this indicate durable loyalty?",
        chat_history=[
            {"role": "user", "content": "Summarize the main risk first."},
            {"role": "assistant", "content": "The risk is that attention stays shallow."},
        ],
        sections=[
            {
                "title": "Executive Summary",
                "content": "The run points to a fleeting moment because pricing skepticism and authenticity scrutiny keep returning.",
            }
        ],
        evidence={
            "topics": ["Pricing Sensitivity", "Gen Z Authenticity"],
            "graph": {
                "node_count": 59,
                "edge_count": 24,
                "named_entities": {
                    "brands": ["Ralph Lauren", "Lacoste"],
                    "platforms": ["TikTok", "Instagram"],
                    "locations": ["Japan"],
                },
            },
            "runtime": {
                "actions": 128,
                "twitter_posts": 29,
                "reddit_posts": 5,
                "comments": 14,
                "quotes": ["Attention outran trust once value questions surfaced."],
            },
            "interviews": [],
        },
    )

    assert "Analyze the Request" not in answer
    assert "Role: Senior Analyst" not in answer
    assert "Instructions:" not in answer
    assert "Conclusion:" in answer
    assert "TikTok" in answer


def test_build_glass_report_chat_response_discards_paragraph_template_echo() -> None:
    """Report chat should strip output-template echoes like paragraph labels and input-data restatements."""
    llm = StubTextLLM(
        "Paragraph 1: State the conclusion. Paragraph 2: Explain the strongest reasons and named entities. "
        "Input Data: A simulation report summary with TikTok, Instagram, Lacoste, and Japan.\n\n"
        "Conclusion: This still reads as a fleeting viral moment rather than durable loyalty because attention outran trust.\n\n"
        "The strongest reasons are that TikTok and Instagram accelerated attention faster than conversion, Lacoste kept the category comparison alive, and Japan remained focused on pricing credibility rather than repeat purchase intent."
    )
    project = Project(name="Ralph Lauren", scenario_brief="Test brand relevance scenario.")
    simulation = Simulation(project_id="proj_1", summary="Ten-round preview run")

    answer, _sources, _tool_calls = build_glass_report_chat_response(
        llm,
        project=project,
        simulation=simulation,
        report=None,
        message="Does this indicate durable loyalty?",
        sections=[],
        evidence={
            "topics": ["Pricing Sensitivity"],
            "graph": {"named_entities": {"platforms": ["TikTok", "Instagram"], "brands": ["Lacoste"], "locations": ["Japan"]}},
            "runtime": {"actions": 22, "twitter_posts": 6, "reddit_posts": 2, "comments": 2, "quotes": []},
            "interviews": [],
        },
    )

    assert "Paragraph 1:" not in answer
    assert "Input Data:" not in answer
    assert answer.startswith("Conclusion:")
    assert "TikTok" in answer


def test_build_glass_report_chat_response_discards_briefing_echo_and_keeps_draft_body() -> None:
    """Report chat should strip briefing-style planning notes and keep only the drafted analyst answer."""
    llm = StubTextLLM(
        "Format: Two short paragraphs. Key Entities: Ralph Lauren, Lacoste, TikTok, Instagram. "
        "Key Topics: Pricing vs Fast Fashion, Gen Z Authenticity. Key Findings: Attention outran trust.\n\n"
        "Need to state clearly: fleeting viral moment versus sustained loyalty. "
        "Evidence suggests: fleeting. Draft: The simulation indicates that this still looks more like a fleeting viral moment than sustained Gen Z loyalty because pricing and authenticity scrutiny harden once the trend leaves first-wave platform excitement.\n\n"
        "The strongest reasons are that TikTok and Instagram drove visibility faster than conversion, Lacoste kept the comparison set alive, and Japan stayed focused on value credibility rather than repeat purchase intent."
    )

    answer, _sources, _tool_calls = build_glass_report_chat_response(
        llm,
        project=Project(name="Ralph Lauren", scenario_brief="Test brand relevance scenario."),
        simulation=Simulation(project_id="proj_1", summary="Ten-round preview run"),
        report=None,
        message="Is this durable loyalty or a fleeting viral moment?",
        sections=[],
        evidence={
            "topics": ["Pricing vs Fast Fashion", "Gen Z Authenticity"],
            "graph": {"named_entities": {"platforms": ["TikTok", "Instagram"], "brands": ["Lacoste"], "locations": ["Japan"]}},
            "runtime": {"actions": 31, "twitter_posts": 8, "reddit_posts": 4, "comments": 3, "quotes": []},
            "interviews": [],
        },
    )

    assert "Format:" not in answer
    assert "Key Entities:" not in answer
    assert "Need to state clearly" not in answer
    assert "Draft:" not in answer
    assert answer.startswith("The simulation indicates")
    assert "TikTok" in answer


def test_build_glass_report_chat_response_falls_back_from_placeholder_output() -> None:
    """Report chat should replace useless placeholder output with a grounded fallback answer."""
    llm = StubTextLLM("<final_answer>...</final_answer>")

    answer, _sources, _tool_calls = build_glass_report_chat_response(
        llm,
        project=Project(name="Ralph Lauren", scenario_brief="Test brand relevance scenario."),
        simulation=Simulation(project_id="proj_1", summary="Ten-round preview run"),
        report=Report(simulation_id="sim_1", executive_summary="The run points to fleeting momentum rather than durable loyalty."),
        message="Is this durable loyalty or a fleeting viral moment?",
        sections=[],
        evidence={
            "topics": ["Pricing vs Fast Fashion", "Gen Z Authenticity"],
            "graph": {
                "named_entities": {
                    "brands": ["Ralph Lauren Corporation", "Lacoste"],
                    "platforms": ["TikTok"],
                    "locations": ["Japan"],
                }
            },
            "runtime": {"actions": 54, "twitter_posts": 14, "reddit_posts": 4, "comments": 7, "quotes": []},
            "interviews": [],
        },
    )

    assert answer != "..."
    assert "Conclusion:" in answer
    assert "Ralph Lauren Corporation" in answer or "TikTok" in answer


def test_choose_active_agent_ids_preview_parallel_does_not_downscale_by_platform_mix(monkeypatch) -> None:
    """Preview runs should keep short-run parallel activation close to the legacy reference instead of shrinking per platform."""
    monkeypatch.setattr("app.services.oasis_runtime.random.uniform", lambda _a, _b: 4.0)
    monkeypatch.setattr("app.services.oasis_runtime.random.random", lambda: 0.0)

    config = {
        "time_config": {
            "agents_per_hour_min": 4,
            "agents_per_hour_max": 4,
            "peak_hours": [],
            "morning_hours": [],
            "work_hours": [],
            "off_peak_hours": [],
            "platform_mix": {"twitter": 0.58, "reddit": 0.62},
        },
        "agent_configs": [
            {
                "agent_id": index,
                "active_hours": [12],
                "activity_level": 0.8,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.8,
                "preferred_platform": "twitter" if index % 2 == 0 else "reddit",
                "cross_platform_affinity": 0.3,
                "influence_weight": 1.5,
            }
            for index in range(1, 9)
        ],
    }

    twitter_ids = choose_active_agent_ids(
        config,
        12,
        platform="twitter",
        preview_run=True,
        platform_count=2,
    )
    reddit_ids = choose_active_agent_ids(
        config,
        12,
        platform="reddit",
        preview_run=True,
        platform_count=2,
    )

    assert len(twitter_ids) == 4
    assert len(reddit_ids) == 4
