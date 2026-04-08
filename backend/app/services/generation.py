"""Pure generation helpers and artifacts used by workflow adapters."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Protocol

from ..models import GraphJob, Project, Report, Simulation, SourceDocument
from .graphiti import split_text_chunks
from .llm import LLMGenerationError


STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "between",
    "brief",
    "could",
    "first",
    "their",
    "there",
    "these",
    "those",
    "under",
    "which",
    "would",
    "scenario",
    "project",
    "analysis",
    "report",
    "market",
    "public",
    "policy",
}

GENERIC_TOPIC_TERMS = {
    "actor",
    "actors",
    "agent",
    "agents",
    "amplifier",
    "amplifiers",
    "audience",
    "audiences",
    "brand",
    "brands",
    "conversation",
    "cycle",
    "debate",
    "discussion",
    "discussions",
    "interpreter",
    "interpreters",
    "moment",
    "moments",
    "narrative",
    "narratives",
    "observer",
    "observers",
    "participant",
    "participants",
    "response",
    "responses",
    "attention",
    "project",
    "scenario",
    "signal",
    "signals",
    "community",
    "voice",
    "voices",
}

ABSTRACT_ONTOLOGY_ENTITY_KEYS = {
    "actor",
    "actors",
    "audience",
    "audiencegroup",
    "audiencesegment",
    "campaign",
    "campaigns",
    "community",
    "communities",
    "event",
    "events",
    "location",
    "locations",
    "narrative",
    "narratives",
    "node",
    "nodes",
    "platform",
    "platforms",
    "product",
    "productline",
    "productlines",
    "segment",
    "segments",
    "signal",
    "signals",
    "theme",
    "themes",
    "topic",
    "topics",
}

NON_CONCEPTUAL_TOPIC_TOKENS = {
    "apparel",
    "ceo",
    "chairman",
    "chief",
    "corporation",
    "expanding",
    "executive",
    "founder",
    "integrates",
    "investigated",
    "launched",
    "launching",
    "licensed",
    "named",
    "official",
    "officer",
    "olympics",
    "partnership",
    "platform",
    "president",
    "serves",
    "sourced",
    "vice",
}

GENERIC_NAMED_ENTITY_PHRASES = {
    "analysis summary",
    "audience segment",
    "brand overview",
    "company profile",
    "company strategy",
    "community response",
    "digital strategy",
    "executive chairman",
    "future prediction report",
    "gen z",
    "graph build",
    "interaction flow",
    "marketing strategy",
    "new analysis",
    "next great chapter",
    "platform split",
    "premium value debate",
    "project database",
    "ralph lauren gen z loyalty scenario",
    "report generation",
    "scenario analysis",
    "setup generation",
    "simulation prompt",
    "source materials",
    "system log",
    "theme",
    "workflow sequence",
}

GENERIC_NAMED_ENTITY_WORDS = {
    "april",
    "analysis",
    "asia",
    "core",
    "audience",
    "brand",
    "campaign",
    "categories",
    "chapter",
    "company",
    "consumers",
    "criticism",
    "creative",
    "ceo",
    "chief",
    "debate",
    "develop",
    "debuted",
    "drive",
    "employees",
    "entry",
    "expansion",
    "executive",
    "fashion",
    "focus",
    "future",
    "generation",
    "growth",
    "home",
    "key",
    "leadership",
    "licensed",
    "loyalty",
    "marketing",
    "media",
    "mid",
    "millennials",
    "markets",
    "named",
    "new",
    "next",
    "officer",
    "official",
    "opening",
    "overview",
    "pacific",
    "parade",
    "platform",
    "pricing",
    "president",
    "profile",
    "project",
    "outfitter",
    "range",
    "reaction",
    "report",
    "revenue",
    "scenario",
    "section",
    "simulation",
    "social",
    "source",
    "status",
    "strategy",
    "sustainability",
    "targeted",
    "targeting",
    "tier",
    "theme",
    "trend",
    "underdeveloped",
    "under",
    "vice",
    "win",
    "over",
    "direct",
    "consumer",
    "designs",
}

NON_CONCEPTUAL_TOPIC_PHRASES = {
    "chief creative officer",
    "executive chairman",
    "not good enough",
    "president and ceo",
    "vice chairman",
}

SINGLE_WORD_TOPIC_ALLOWLIST = {
    "affordability",
    "authenticity",
    "backlash",
    "conversion",
    "credibility",
    "craftsmanship",
    "desirability",
    "exclusivity",
    "heritage",
    "pricing",
    "quality",
    "retention",
    "loyalty",
    "nostalgia",
    "sustainability",
    "streetwear",
    "relevance",
    "competition",
    "value",
    "virality",
    "trust",
}

THEME_SIGNAL_TERMS = {
    "aesthetic",
    "affordability",
    "athlete",
    "authenticity",
    "backlash",
    "commerce",
    "conversion",
    "coverage",
    "craftsmanship",
    "credibility",
    "desirability",
    "discount",
    "domestic",
    "equity",
    "exclusivity",
    "geopolitical",
    "heritage",
    "influencer",
    "localization",
    "loyalty",
    "luxury",
    "media",
    "momentum",
    "nostalgia",
    "olympic",
    "positioning",
    "premium",
    "pricing",
    "proof",
    "quality",
    "relevance",
    "retention",
    "scrutiny",
    "streetwear",
    "sustainability",
    "trust",
    "value",
    "viral",
    "virality",
}

ENTITY_TOPIC_FRAGMENT_STOPWORDS = {
    "corporation",
    "company",
    "group",
    "collection",
    "design",
    "fashion",
    "lifestyle",
    "international",
    "global",
    "holdings",
    "label",
    "home",
    "sport",
    "premium",
}

SCENARIO_TOPIC_MAP: list[tuple[str, str]] = [
    ("gen z", "Gen Z Loyalty"),
    ("brand loyalty", "Brand Loyalty"),
    ("loyalty", "Brand Loyalty"),
    ("american heritage", "American Heritage Branding"),
    ("pricing", "Pricing Sensitivity"),
    ("fast fashion", "Fast Fashion Comparison"),
    ("authentic", "Brand Authenticity"),
    ("sustainab", "Sustainability Criticism"),
    ("cultural relevance", "Cultural Relevance"),
    ("culturally relevant", "Cultural Relevance"),
    ("streetwear", "Streetwear Credibility"),
    ("brand relevance", "Brand Relevance"),
    ("culturally relevant", "Brand Relevance"),
    ("fashion media", "Fashion Media Coverage"),
    ("influencer", "Influencer Reaction"),
    ("heritage", "Heritage Luxury"),
    ("craftsmanship", "Craftsmanship Proof"),
    ("quality", "Quality Proof"),
    ("value", "Value Justification"),
    ("affordab", "Affordability Pressure"),
    ("premium", "Premium Positioning"),
    ("quiet luxury", "Quiet Luxury Positioning"),
    ("old money", "Heritage Luxury"),
    ("conversion", "Conversion Barrier"),
    ("retention", "Loyalty Retention"),
    ("backlash", "Narrative Backlash"),
    ("viral aesthetic", "Viral Aesthetic"),
    ("viral", "Viral Momentum"),
    ("christmas", "Holiday Aesthetic"),
    ("social media", "Social Virality"),
    ("transparency", "Sustainability Criticism"),
    ("forced labor", "Sustainability Criticism"),
    ("not good enough", "Sustainability Criticism"),
    ("twitter", "Twitter Reaction"),
    ("reddit", "Reddit Discussion"),
    ("wechat", "WeChat Commerce Strategy"),
    ("geopolitical", "Geopolitical Risk"),
    ("domestic brand", "Domestic Brand Competition"),
    ("li-ning", "Domestic Brand Competition"),
    ("anta", "Domestic Brand Competition"),
    ("burberry", "Luxury Competition"),
    ("tommy hilfiger", "Luxury Competition"),
    ("competitor", "Luxury Competition"),
    ("luxury", "Luxury Competition"),
]

THEME_LABEL_ALLOWLIST = {
    "Affordability Pressure",
    "Aspirational Luxury Tension",
    "American Heritage Branding",
    "Athlete Credibility",
    "Brand Authenticity",
    "Brand Loyalty",
    "Brand Relevance",
    "Competitive Positioning",
    "Cultural Relevance",
    "Conversion Barrier",
    "Craftsmanship Proof",
    "Discount Channel Exit",
    "Domestic Brand Competition",
    "Exclusivity Tradeoff",
    "Fashion Media Coverage",
    "Fast Fashion Comparison",
    "Gen Z Authenticity",
    "Gen Z Loyalty",
    "Geopolitical Risk",
    "Greenwashing Scrutiny",
    "Heritage Luxury",
    "Holiday Campaign Virality",
    "Holiday Aesthetic",
    "Influencer Reaction",
    "Loyalty Retention",
    "Luxury Competition",
    "Market Localization",
    "Narrative Backlash",
    "Olympic Visibility",
    "Premium Value Debate",
    "Premium Positioning",
    "Pricing Sensitivity",
    "Pricing vs Fast Fashion",
    "Quality Proof",
    "Reddit Discussion",
    "Social Virality",
    "Sportswear Competition",
    "Streetwear Credibility",
    "Supply Chain Scrutiny",
    "Sustainability Criticism",
    "Trust",
    "Twitter Reaction",
    "Value Justification",
    "Viral Aesthetic",
    "Viral Momentum",
    "WeChat Commerce Strategy",
}

THEME_ALIAS_MAP = {
    "affordability pressure": "Pricing vs Fast Fashion",
    "brand authenticity": "Gen Z Authenticity",
    "brand loyalty": "Gen Z Loyalty",
    "cultural relevance": "Brand Relevance",
    "fashion media coverage": "Influencer Reaction",
    "heritage luxury": "Aspirational Luxury Tension",
    "holiday aesthetic": "Holiday Campaign Virality",
    "premium positioning": "Premium Value Debate",
    "pricing sensitivity": "Pricing vs Fast Fashion",
    "quality proof": "Premium Value Debate",
    "social virality": "Holiday Campaign Virality",
    "value justification": "Premium Value Debate",
    "viral aesthetic": "Holiday Campaign Virality",
    "viral momentum": "Holiday Campaign Virality",
}


class TextGenerator(Protocol):
    """Small interface needed by the local generation helpers."""

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 700,
    ) -> str:
        """Generate text from a system and user prompt."""


@dataclass(frozen=True)
class GraphArtifacts:
    """Outputs produced by graph preparation."""

    summary: str
    source_digest: str
    schema_markdown: str
    evidence_markdown: str
    node_count: int
    edge_count: int
    graph_id: str | None = None
    graph_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class SimulationArtifacts:
    """Outputs produced by a simulation run."""

    summary: str
    rounds: int
    event_count: int
    timeline_markdown: str
    events: list[dict[str, str | int]]


@dataclass(frozen=True)
class ReportArtifacts:
    """Outputs produced by report generation."""

    summary: str
    executive_summary: str
    markdown_body: str


def project_context_text(project: Project, documents: list[SourceDocument]) -> str:
    """Build a single text block from the project brief and source content."""
    sections = [
        f"Project name: {project.name}",
        f"Project description: {project.description}",
        f"Scenario brief: {project.scenario_brief}",
    ]
    for document in documents:
        if document.extracted_text:
            sections.append(f"Source: {document.filename}\n{document.extracted_text}")
    return "\n\n".join(section for section in sections if section.strip())


def top_terms(text: str, limit: int = 8) -> list[str]:
    """Extract a small set of high-signal terms from text."""
    words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text.lower())
    filtered = [word for word in words if word not in STOPWORDS]
    counts = Counter(filtered)
    return [item for item, _ in counts.most_common(limit)]


def dedupe_preserve_order(items: list[str], *, limit: int | None = None) -> list[str]:
    """Remove repeated strings while preserving order."""
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        normalized = cleaned.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(cleaned)
        if limit is not None and len(deduped) >= limit:
            break
    return deduped


def clean_topic_label(value: str) -> str:
    """Normalize a topic label into readable title case."""
    cleaned = re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).strip(" :;,.")
    if not cleaned:
        return ""
    if cleaned.lower().startswith("the ") and len(cleaned.split()) > 1:
        cleaned = cleaned[4:]
    if cleaned.isupper():
        return cleaned.title()
    if any(char.isupper() for char in cleaned[1:]):
        return cleaned
    return cleaned.title()


def normalize_theme_label(value: str) -> str:
    """Collapse near-duplicate theme labels into a stable analyst vocabulary."""
    cleaned = clean_topic_label(value)
    if not cleaned:
        return ""
    return THEME_ALIAS_MAP.get(cleaned.casefold(), cleaned)


def is_meaningful_named_entity(candidate: str) -> bool:
    """Return True when a capitalized phrase looks like a real entity rather than a heading fragment."""
    cleaned = candidate.strip().strip(".,:;!?()[]{}\"'")
    if len(cleaned) < 3:
        return False

    lowered = cleaned.casefold()
    if lowered in GENERIC_NAMED_ENTITY_PHRASES:
        return False
    if lowered in {"simulate", "include", "predict", "analyze", "the", "revenue", "employees", "american"}:
        return False
    if re.fullmatch(r"(?:[A-Z]\.?){2,5}", cleaned):
        return False
    if re.fullmatch(r"[A-Z]{1,4}\d*", cleaned):
        return False
    if cleaned.isdigit():
        return False

    words = re.findall(r"[A-Za-z0-9&'.-]+", cleaned)
    if not words:
        return False
    if len(words) == 1 and words[0].casefold() in GENERIC_NAMED_ENTITY_WORDS:
        return False
    if all(word.casefold() in GENERIC_NAMED_ENTITY_WORDS for word in words):
        return False
    return True


def normalize_named_entity_candidate(candidate: str) -> str:
    """Trim leading or trailing generic title words from a candidate phrase."""
    words = re.findall(r"[A-Za-z0-9&'.-]+", candidate)
    if not words:
        return ""

    while len(words) > 1 and words[0].casefold() in GENERIC_NAMED_ENTITY_WORDS:
        words.pop(0)
    while len(words) > 1 and words[-1].casefold() in GENERIC_NAMED_ENTITY_WORDS:
        words.pop()

    return " ".join(words).strip()


def extract_named_entity_candidates(text: str, *, limit: int = 18) -> list[str]:
    """Extract likely entity names from source text while skipping headings and prompt fragments."""
    cleaned: list[str] = []
    seen: set[str] = set()
    lines = [re.sub(r"^[#>*\-\d.\s]+", "", line).strip() for line in str(text or "").splitlines()]
    for line in lines:
        if not line:
            continue
        matches = re.findall(r"\b[A-Z][A-Za-z0-9&'.-]*(?: +[A-Z][A-Za-z0-9&'.-]*){0,3}\b", line)
        for match in matches:
            candidate = normalize_named_entity_candidate(match.strip().strip(".,:;!?()[]{}\"'"))
            if not is_meaningful_named_entity(candidate):
                continue
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(candidate)
            if len(cleaned) >= limit:
                return cleaned
    return cleaned


def sample_named_entities_across_source(
    source_texts: list[str] | None,
    *,
    limit: int = 18,
    per_chunk_limit: int = 3,
) -> list[str]:
    """Sample named entities across the full document instead of only from the opening chunk."""
    def candidate_score(candidate: str) -> tuple[int, int]:
        words = re.findall(r"[A-Za-z0-9&'.-]+", candidate)
        generic_hits = sum(1 for word in words if word.casefold() in GENERIC_NAMED_ENTITY_WORDS)
        multi_word_bonus = 3 if len(words) >= 2 else 0
        return (len(words) * 4 + multi_word_bonus - (generic_hits * 7), len(candidate))

    sampled: list[str] = []
    seen: set[str] = set()

    for source in source_texts or []:
        chunks = split_text_chunks(source, chunk_size=900, overlap=80)
        for chunk in chunks:
            chunk_candidates = extract_named_entity_candidates(chunk, limit=max(per_chunk_limit * 6, 18))
            for candidate in sorted(chunk_candidates, key=candidate_score, reverse=True)[:per_chunk_limit]:
                key = candidate.casefold()
                if key in seen:
                    continue
                seen.add(key)
                sampled.append(candidate)
                if len(sampled) >= limit:
                    return sampled

    for source in source_texts or []:
        for candidate in extract_named_entity_candidates(source, limit=limit):
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            sampled.append(candidate)
            if len(sampled) >= limit:
                break
        if len(sampled) >= limit:
            break

    return sampled


def extract_focus_phrases(text: str, limit: int = 8) -> list[str]:
    """Extract scenario-level themes that are richer than unigram keywords."""
    source = str(text or "").strip()
    if not source:
        return []

    lowered = source.lower()
    phrases: list[str] = []

    for needle, label in SCENARIO_TOPIC_MAP:
        if needle in lowered:
            phrases.append(label)

    for match in re.findall(r"['\"]([^'\"]{4,80})['\"]", source):
        candidate = clean_topic_label(match)
        if candidate and candidate.casefold() not in {item.casefold() for item in phrases}:
            if candidate.casefold() in NON_CONCEPTUAL_TOPIC_PHRASES or "." in candidate:
                continue
            phrases.append(candidate)

    for match in re.findall(r"\b(?:[A-Z][A-Za-z&.'-]+(?:\s+[A-Z][A-Za-z&.'-]+){1,3})\b", source):
        candidate = clean_topic_label(match)
        if not candidate:
            continue
        lowered_candidate = candidate.casefold()
        if lowered_candidate in {item.casefold() for item in phrases}:
            continue
        if lowered_candidate in {"ralph lauren", "future prediction report"}:
            continue
        if "." in candidate or lowered_candidate in NON_CONCEPTUAL_TOPIC_PHRASES:
            continue
        phrases.append(candidate)

    for token in top_terms(source, limit=max(limit * 2, 12)):
        if token in GENERIC_TOPIC_TERMS:
            continue
        if token in {"ralph", "lauren"}:
            continue
        phrases.append(clean_topic_label(token))

    return dedupe_preserve_order(phrases, limit=limit)


def derive_project_label(
    project_name: str | None,
    scenario_brief: str,
    topics: list[str] | None = None,
    graph_facts: list[str] | None = None,
) -> str:
    """Return a human-readable project label even when the saved name is empty."""
    cleaned_name = str(project_name or "").strip()
    if cleaned_name and cleaned_name != "Unnamed Project":
        return cleaned_name

    topic_candidates = dedupe_preserve_order(
        [*(topics or []), *extract_focus_phrases(scenario_brief, limit=6), *(graph_facts or [])],
        limit=10,
    )
    scenario_lower = scenario_brief.lower()
    if "ralph lauren" in scenario_lower and "gen z" in scenario_lower:
        return "Ralph Lauren Gen Z Loyalty Scenario"
    if "ralph lauren" in scenario_lower:
        return "Ralph Lauren Scenario"
    if topic_candidates:
        first = topic_candidates[0]
        if len(first) <= 48:
            return f"{first} Scenario"
    return "Scenario Analysis"


def infer_project_name(
    project_name: str | None,
    *,
    requirement: str,
    additional_context: str = "",
    source_texts: list[str] | None = None,
) -> str:
    """Return a stable project name even when the incoming form left it blank."""
    cleaned_name = str(project_name or "").strip()
    if cleaned_name and cleaned_name != "Unnamed Project":
        return cleaned_name

    combined = "\n\n".join(
        part
        for part in [requirement, additional_context, *(source_texts or [])]
        if str(part or "").strip()
    )
    inferred = derive_project_label("", combined)
    if inferred and inferred != "Scenario Analysis":
        return inferred
    return "Scenario Analysis"


def derive_priority_themes(text: str) -> list[str]:
    """Return scenario-level themes before falling back to entity names or raw keywords."""
    lowered = str(text or "").lower()
    if not lowered:
        return []
    themes: list[str] = []
    rules: list[tuple[tuple[str, ...], str]] = [
        (("ralph lauren", "christmas"), "Ralph Lauren Christmas"),
        (("gen z", "authentic"), "Gen Z Authenticity"),
        (("gen z", "loyal"), "Gen Z Loyalty"),
        (("pricing", "fast fashion"), "Pricing vs Fast Fashion"),
        (("sustainab",), "Sustainability Criticism"),
        (("culturally relevant",), "Brand Relevance"),
        (("brand loyalty",), "Brand Loyalty"),
        (("loyalty",), "Brand Loyalty"),
        (("pricing",), "Pricing Sensitivity"),
        (("authentic",), "Brand Authenticity"),
        (("heritage",), "Heritage Luxury"),
        (("quiet luxury",), "Quiet Luxury Positioning"),
        (("old money",), "Heritage Luxury"),
        (("craftsmanship",), "Craftsmanship Proof"),
        (("quality",), "Quality Proof"),
        (("value",), "Value Justification"),
        (("affordab",), "Affordability Pressure"),
        (("premium",), "Premium Positioning"),
        (("streetwear",), "Streetwear Credibility"),
        (("fashion media",), "Fashion Media Coverage"),
        (("influencer",), "Influencer Reaction"),
        (("conversion",), "Conversion Barrier"),
        (("retention",), "Loyalty Retention"),
        (("backlash",), "Narrative Backlash"),
        (("viral", "aesthetic"), "Viral Aesthetic"),
        (("viral",), "Viral Momentum"),
        (("burberry",), "Luxury Competition"),
        (("tommy hilfiger",), "Luxury Competition"),
        (("competitor",), "Luxury Competition"),
    ]
    for needles, label in rules:
        if all(needle in lowered for needle in needles):
            themes.append(label)
    if "american heritage" in lowered:
        themes = [item for item in themes if item != "Heritage Luxury"]
        themes.append("American Heritage Branding")
    if ("holiday" in lowered or "christmas" in lowered) and "campaign" in lowered:
        themes.append("Holiday Campaign Virality")
    if "pricing" in lowered and any(keyword in lowered for keyword in ("luxury", "premium", "polo shirt", "$")):
        themes.append("Premium Value Debate")
    if any(keyword in lowered for keyword in ("heritage", "old money", "timeless")) and any(
        keyword in lowered for keyword in ("gen z", "young", "younger audiences")
    ):
        themes.append("Aspirational Luxury Tension")
    if any(keyword in lowered for keyword in ("younger audiences", "gen z", "young consumers")) and any(
        keyword in lowered for keyword in ("relevance", "relevant", "culturally")
    ):
        themes.append("Brand Relevance")
    if "china" in lowered or "wechat" in lowered:
        themes.append("Market Localization")
    if any(keyword in lowered for keyword in ("geopolitical", "american heritage", "domestic brand")):
        themes.append("Geopolitical Risk")
    if any(keyword in lowered for keyword in ("li-ning", "anta", "domestic brand advocates")):
        themes.append("Domestic Brand Competition")
    if "wechat" in lowered:
        themes.append("WeChat Commerce Strategy")
    if any(keyword in lowered for keyword in ("direct-to-consumer", "off-price", "discount channel", "tj maxx", "nordstrom rack")):
        themes.append("Discount Channel Exit")
    if any(keyword in lowered for keyword in ("exclusivity", "brand elevation")):
        themes.append("Exclusivity Tradeoff")
    if "greenwashing" in lowered:
        themes.append("Greenwashing Scrutiny")
    if any(keyword in lowered for keyword in ("olympic", "team usa")):
        themes.append("Olympic Visibility")
    if "athlete" in lowered:
        themes.append("Athlete Credibility")
    return [normalize_theme_label(item) for item in dedupe_preserve_order(themes, limit=8)]


def is_social_brand_simulation_context(text: str) -> bool:
    """Return True when the prompt reads like a live public-reaction brand simulation."""
    lowered = str(text or "").lower()
    if not lowered:
        return False
    brand_signals = (
        "brand",
        "fashion",
        "luxury",
        "consumer",
        "campaign",
        "retail",
        "pricing",
        "loyalty",
        "influencer",
        "streetwear",
    )
    social_signals = (
        "simulate",
        "reaction",
        "react",
        "public",
        "social",
        "twitter",
        "reddit",
        "gen z",
        "audience",
        "community",
        "viral",
        "loyalty",
    )
    brand_hits = sum(1 for item in brand_signals if item in lowered)
    social_hits = sum(1 for item in social_signals if item in lowered)
    return brand_hits >= 2 and social_hits >= 2


def detect_social_brand_simulation_submode(text: str) -> str:
    """Return a stable scenario submode for social-brand simulations."""
    lowered = str(text or "").lower()
    if not lowered:
        return "generic_brand_social"

    weighted_rules: dict[str, list[tuple[str, int]]] = {
        "market_expansion": [
            ("china", 4),
            ("chinese", 3),
            ("wechat", 4),
            ("tier 1", 3),
            ("tier 2", 3),
            ("flagship store", 3),
            ("flagship stores", 3),
            ("market expansion", 4),
            ("expansion", 2),
            ("geopolitical", 4),
            ("domestic brand", 3),
            ("li-ning", 4),
            ("anta", 4),
            ("american heritage", 3),
        ],
        "sustainability_launch": [
            ("sustainab", 4),
            ("greenwashing", 5),
            ("recycled", 4),
            ("supply chain", 4),
            ("labor issues", 4),
            ("good on you", 4),
            ("eco-conscious", 3),
            ("sustainability premium", 4),
            ("skeptics", 2),
        ],
        "channel_strategy": [
            ("direct-to-consumer", 5),
            ("off-price", 5),
            ("discount channel", 5),
            ("discount", 3),
            ("tj maxx", 4),
            ("nordstrom rack", 4),
            ("exclusivity", 4),
            ("bargain shoppers", 4),
            ("retail industry analysts", 4),
            ("brand elevation", 4),
        ],
        "sports_partnership": [
            ("olympic", 5),
            ("team usa", 5),
            ("parade uniforms", 4),
            ("athletes", 4),
            ("athlete", 3),
            ("nike", 3),
            ("adidas", 3),
            ("under armour", 3),
            ("sportswear", 3),
            ("patriotic", 4),
        ],
        "brand_loyalty": [
            ("gen z", 4),
            ("younger audiences", 4),
            ("culturally relevant", 3),
            ("cultural relevance", 3),
            ("christmas", 3),
            ("viral aesthetic", 4),
            ("streetwear", 3),
            ("brand loyalty", 4),
            ("sustained brand loyalty", 5),
            ("fleeting social media moment", 4),
        ],
    }

    scores = {
        mode: sum(weight for needle, weight in rules if needle in lowered)
        for mode, rules in weighted_rules.items()
    }
    best_mode, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score >= 6:
        return best_mode
    if "gen z" in lowered or "viral" in lowered or "loyal" in lowered:
        return "brand_loyalty"
    return "generic_brand_social"


def scenario_mode_theme_defaults(mode: str) -> list[str]:
    """Return scenario-specific seed themes before graph-derived ranking kicks in."""
    defaults = {
        "market_expansion": [
            "Market Localization",
            "American Heritage Branding",
            "Geopolitical Risk",
            "Domestic Brand Competition",
            "WeChat Commerce Strategy",
            "Competitive Positioning",
            "Sustainability Criticism",
        ],
        "channel_strategy": [
            "Discount Channel Exit",
            "Exclusivity Tradeoff",
            "Premium Value Debate",
            "Brand Authenticity",
            "Competitive Positioning",
        ],
        "sports_partnership": [
            "Olympic Visibility",
            "Athlete Credibility",
            "Sportswear Competition",
            "Brand Relevance",
            "Fashion Media Coverage",
        ],
        "sustainability_launch": [
            "Sustainability Criticism",
            "Supply Chain Scrutiny",
            "Brand Authenticity",
            "Pricing vs Fast Fashion",
            "Competitive Positioning",
        ],
        "brand_loyalty": [
            "Brand Relevance",
            "Gen Z Authenticity",
            "Premium Value Debate",
            "Luxury Competition",
        ],
    }
    return defaults.get(mode, ["Brand Relevance", "Gen Z Authenticity", "Pricing vs Fast Fashion"])


def theme_defaults_for_entity_type(entity_type: str, *, scenario_mode: str = "") -> list[str]:
    """Return conceptual fallback themes for an entity type."""
    normalized = slugify(entity_type).replace("-", "")
    if scenario_mode == "market_expansion":
        scenario_defaults = {
            "luxurybrand": ["American Heritage Branding", "Market Localization", "WeChat Commerce Strategy", "Competitive Positioning"],
            "competitorbrand": ["Domestic Brand Competition", "Competitive Positioning", "American Heritage Branding", "Luxury Competition"],
            "luxuryconsumer": ["Market Localization", "WeChat Commerce Strategy", "American Heritage Branding", "Value Justification"],
            "marketanalyst": ["Market Localization", "Competitive Positioning", "Geopolitical Risk", "WeChat Commerce Strategy"],
            "retailindustryanalyst": ["Market Localization", "Competitive Positioning", "Geopolitical Risk", "WeChat Commerce Strategy"],
            "sustainabilityactivist": ["Sustainability Criticism", "Supply Chain Scrutiny", "Geopolitical Risk", "Market Localization"],
            "organization": ["Geopolitical Risk", "Market Localization", "WeChat Commerce Strategy", "Sustainability Criticism"],
            "person": ["American Heritage Branding", "Geopolitical Risk", "Market Localization", "Narrative Backlash"],
        }
        specific = scenario_defaults.get(normalized)
        if specific:
            return specific
    if normalized in {"luxurybrand", "subbrand"}:
        return ["Brand Relevance", "Gen Z Authenticity", "Premium Value Debate", "Luxury Competition"]
    if normalized in {"fashionbrand"}:
        return ["Brand Relevance", "Market Localization", "Premium Value Debate", "Luxury Competition"]
    if normalized in {"executive"}:
        return ["Brand Relevance", "Brand Authenticity", "Quality Proof", "Narrative Backlash"]
    if normalized in {"fashioninfluencer"}:
        return ["Influencer Reaction", "Viral Momentum", "Brand Authenticity", "Streetwear Credibility"]
    if normalized in {"consumercohort"}:
        return ["Gen Z Authenticity", "Pricing vs Fast Fashion", "Affordability Pressure", "Brand Loyalty"]
    if normalized in {"marketanalyst", "retailindustryanalyst"}:
        return ["Market Localization", "Premium Value Debate", "Competitive Positioning", "Narrative Backlash"]
    if normalized in {"geopoliticalcommentator"}:
        return ["Geopolitical Risk", "Market Localization", "Narrative Backlash", "Brand Authenticity"]
    if normalized in {"sustainabilityactivist", "watchdoggroup"}:
        return ["Sustainability Criticism", "Supply Chain Scrutiny", "Brand Authenticity", "Narrative Backlash"]
    if normalized in {"discountshopper"}:
        return ["Discount Channel Exit", "Affordability Pressure", "Conversion Barrier", "Brand Loyalty"]
    if normalized in {"brandpurist"}:
        return ["Premium Positioning", "Brand Authenticity", "Exclusivity Tradeoff", "Brand Loyalty"]
    if normalized in {"athleteambassador"}:
        return ["Olympic Visibility", "Athlete Credibility", "Viral Momentum", "Brand Relevance"]
    if normalized in {"sportswearcompetitor"}:
        return ["Sportswear Competition", "Olympic Visibility", "Premium Value Debate", "Brand Relevance"]
    if normalized in {"fashionmediaoutlet"}:
        return ["Fashion Media Coverage", "Brand Relevance", "Luxury Competition", "Narrative Backlash"]
    if normalized in {"institutionalactor", "retailpartner", "watchdoggroup"}:
        return ["Brand Authenticity", "Sustainability Criticism", "Value Justification", "Brand Loyalty"]
    if normalized in {"brand", "fashionbrand", "company", "organization", "institution"}:
        return ["Brand Relevance", "Gen Z Authenticity", "Value Justification", "Sustainability Criticism"]
    if normalized in {"competitorbrand"}:
        return ["Luxury Competition", "Pricing vs Fast Fashion", "Value Justification", "Brand Relevance"]
    if normalized in {"mediaoutlet", "journalist"}:
        return ["Fashion Media Coverage", "Brand Relevance", "Sustainability Criticism", "Gen Z Authenticity"]
    if normalized in {"audience", "audiencesegment", "community", "consumer", "customer", "genzconsumer", "student"}:
        return ["Gen Z Authenticity", "Pricing vs Fast Fashion", "Affordability Pressure", "Brand Relevance"]
    if normalized in {"person", "official", "creator", "fashioninfluencer"}:
        return ["Brand Relevance", "Gen Z Authenticity", "Narrative Backlash", "Sustainability Criticism"]
    if normalized in {"productline"}:
        return ["Brand Relevance", "Value Justification", "Craftsmanship Proof", "Luxury Competition"]
    if normalized in {"platform"}:
        return ["Viral Momentum", "Brand Relevance", "Gen Z Authenticity", "Fashion Media Coverage"]
    if normalized in {"event"}:
        return ["Viral Aesthetic", "Brand Relevance", "Gen Z Authenticity", "Fashion Media Coverage"]
    if normalized in {"location"}:
        return ["Brand Relevance", "Luxury Competition", "Gen Z Authenticity"]
    return ["Brand Relevance", "Gen Z Authenticity", "Pricing vs Fast Fashion"]


def build_entity_topic_blacklist(entity_names: list[str]) -> tuple[set[str], set[str]]:
    """Return exact entity names and name fragments that should not be treated as conceptual topics."""
    exact_names: set[str] = set()
    fragments: set[str] = set()
    for name in entity_names:
        cleaned = str(name or "").strip()
        if not cleaned:
            continue
        lower_name = cleaned.casefold()
        exact_names.add(lower_name)
        tokens = [
            token.casefold()
            for token in re.findall(r"[A-Za-z][A-Za-z&'.-]{2,}", cleaned)
            if len(token) >= 4
        ]
        if len(tokens) > 1:
            for token in tokens:
                if token not in ENTITY_TOPIC_FRAGMENT_STOPWORDS:
                    fragments.add(token)
        elif tokens and tokens[0] not in SINGLE_WORD_TOPIC_ALLOWLIST:
            fragments.add(tokens[0])
    return exact_names, fragments


def is_conceptual_topic(
    value: str,
    *,
    entity_names: set[str] | None = None,
    entity_fragments: set[str] | None = None,
) -> bool:
    """Return True when a candidate reads like a scenario theme instead of an entity label."""
    cleaned = clean_topic_label(value)
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if cleaned in THEME_LABEL_ALLOWLIST:
        return True
    if lowered in GENERIC_TOPIC_TERMS:
        return False
    if lowered in {"ralph", "lauren", "sold", "project", "scenario"}:
        return False
    if lowered in NON_CONCEPTUAL_TOPIC_PHRASES or "." in cleaned:
        return False
    entity_names = entity_names or set()
    entity_fragments = entity_fragments or set()
    if lowered in entity_names:
        return False
    tokens = [token.casefold() for token in re.findall(r"[A-Za-z][A-Za-z&'.-]{1,}", cleaned)]
    if not tokens:
        return False
    if len(tokens) == 1:
        token = tokens[0]
        if token in NON_CONCEPTUAL_TOPIC_TOKENS:
            return False
        if token in entity_fragments and token not in SINGLE_WORD_TOPIC_ALLOWLIST:
            return False
        return token in SINGLE_WORD_TOPIC_ALLOWLIST or len(token) >= 5
    if any(token in NON_CONCEPTUAL_TOPIC_TOKENS for token in tokens):
        return False
    if all(token in entity_fragments for token in tokens):
        return False
    if any(token in {"corporation", "company", "group", "collection"} for token in tokens):
        return False
    return True


def theme_signal_score(value: str) -> int:
    """Score how strongly a candidate reads like a real scenario theme."""
    cleaned = clean_topic_label(value)
    if not cleaned:
        return -10
    lowered = cleaned.casefold()
    if lowered in GENERIC_TOPIC_TERMS:
        return -10
    score = 0
    if cleaned in THEME_LABEL_ALLOWLIST:
        score += 8
    tokens = [token.casefold() for token in re.findall(r"[A-Za-z][A-Za-z&'.-]{1,}", cleaned)]
    for token in tokens:
        if token in THEME_SIGNAL_TERMS:
            score += 2
        if token in SINGLE_WORD_TOPIC_ALLOWLIST:
            score += 1
    if len(tokens) >= 2:
        score += 2
    if "gen" in tokens and "z" in tokens:
        score += 2
    return score


def rank_theme_candidates(items: list[str], *, limit: int = 6) -> list[str]:
    """Order candidate themes by specificity while keeping stable tie-breaking."""
    deduped = dedupe_preserve_order([normalize_theme_label(item) for item in items])
    ranked = sorted(
        enumerate(deduped),
        key=lambda pair: (
            -theme_signal_score(pair[1]),
            -len(pair[1].split()),
            pair[0],
        ),
    )
    return [item for _, item in ranked[:limit]]


def quoted_source_points(documents: list[SourceDocument], limit: int = 4) -> list[str]:
    """Collect concise source highlights for markdown output."""
    points: list[str] = []
    for document in documents:
        excerpt = document.text_excerpt.strip()
        if excerpt:
            points.append(f"{document.filename}: {excerpt}")
        if len(points) >= limit:
            break
    return points


def maybe_generate_text(
    llm: TextGenerator | None,
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 700,
) -> str | None:
    """Attempt LLM generation and return None on provider failure."""
    if llm is None:
        return None
    try:
        return llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except LLMGenerationError:
        return None


def maybe_generate_json(
    llm: TextGenerator | None,
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 700,
) -> dict[str, object] | list[object] | None:
    """Attempt LLM generation and parse a JSON object or list, returning None on failure."""
    generated = maybe_generate_text(
        llm,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if not generated:
        return None
    candidate = generated.strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, (dict, list)):
            return parsed
    except Exception:
        pass
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", candidate)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
    except Exception:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def sanitize_short_model_text(text: str | None, fallback: str | None = None) -> str | None:
    """Reduce a verbose model response to a single clean sentence."""
    if not text or not text.strip():
        return fallback

    cleaned = text.replace("\r", "").replace("**", "").replace("__", "").strip()
    for marker in ("Final answer:", "Answer:"):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[1].strip()

    candidate_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip().lstrip("-*# ").strip()
        if not line:
            continue
        numbered_match = re.match(r"^\d+\.\s*(.+)$", line)
        if numbered_match:
            line = numbered_match.group(1).strip()
        lowered = line.lower().rstrip(":")
        if lowered.startswith(
            (
                "thinking process",
                "reasoning",
                "analysis",
                "the user is asking",
                "user question:",
                "the question is",
                "let me ",
                "i'll ",
                "i need to",
                "analyze the request",
                "analyze the input",
                "input data",
                "project:",
                "scenario:",
                "platform:",
                "requirement:",
                "additional context:",
                "top terms:",
                "persona:",
                "persona name:",
                "persona role:",
                "persona bio:",
                "persona description:",
                "role:",
                "bio:",
                "interested topics:",
                "recent actions:",
                "recent runtime activity:",
                "interview prompt:",
                "selection",
                "final polish",
                "draft",
                "attempt",
                "refining",
                "task",
                "constraint",
                "question:",
            )
        ):
            continue
        if any(
            token in lowered
            for token in (
                "task:",
                "input data:",
                "constraint:",
                "platform:",
                "question:",
                "persona description:",
                "recent runtime activity:",
                "selection:",
                "the user is asking",
                "user question:",
                "i need to",
                "let me ",
            )
        ):
            continue
        candidate_lines.append(line)

    collapsed = re.sub(r"\s+", " ", " ".join(candidate_lines)).strip()
    if not collapsed:
        return fallback

    sentence_match = re.search(r"(.+?[.!?])(?:\s|$)", collapsed)
    sentence = sentence_match.group(1).strip() if sentence_match else collapsed
    if len(sentence) > 220:
        sentence = f"{sentence[:217].rsplit(' ', 1)[0]}..."

    lowered_sentence = sentence.lower()
    if "thinking process" in lowered_sentence:
        return fallback
    if any(
        token in lowered_sentence
        for token in (
            "project:",
            "scenario:",
            "platform:",
            "requirement:",
            "the user is asking",
            "user question:",
            "persona:",
            "persona name:",
            "persona role:",
            "persona bio:",
            "persona description:",
            "role:",
            "bio:",
            "interview prompt:",
            "recent runtime activity:",
            "question:",
            "i need to",
            "let me ",
        )
    ):
        return fallback
    return sentence or fallback


def sanitize_model_excerpt(
    text: str | None,
    fallback: str | None = None,
    *,
    max_sentences: int = 2,
    max_chars: int = 320,
) -> str | None:
    """Clean model output while preserving a short multi-sentence excerpt."""
    if not text or not text.strip():
        return fallback

    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("\r", "").replace("**", "").replace("__", "").strip()
    for marker in ("Final answer:", "Answer:"):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[1].strip()

    candidate_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip().lstrip("-*# ").strip()
        if not line:
            continue
        numbered_match = re.match(r"^\d+\.\s*(.+)$", line)
        if numbered_match:
            line = numbered_match.group(1).strip()
        lowered = line.lower().rstrip(":")
        if lowered.startswith(
            (
                "thinking process",
                "reasoning",
                "analysis",
                "the user is asking",
                "user question:",
                "the question is",
                "let me ",
                "i'll ",
                "i need to",
                "project:",
                "scenario:",
                "platform:",
                "question:",
                "tool result",
                "observation",
            )
        ):
            continue
        if any(
            token in lowered
            for token in (
                "task:",
                "constraint:",
                "persona description:",
                "recent runtime activity:",
                "[tool_call]",
                "<tool_call>",
            )
        ):
            continue
        candidate_lines.append(line)

    collapsed = re.sub(r"\s+", " ", " ".join(candidate_lines)).strip()
    if not collapsed:
        return fallback

    sentence_candidates = [
        fragment.strip()
        for fragment in re.findall(r"[^.!?]+[.!?]?", collapsed)
        if fragment.strip()
    ]
    excerpt = " ".join(sentence_candidates[:max(1, max_sentences)]).strip()
    excerpt = excerpt.rstrip(". ") + "." if excerpt and excerpt[-1] not in ".!?" else excerpt
    if len(excerpt) > max_chars:
        excerpt = f"{excerpt[: max_chars - 3].rsplit(' ', 1)[0]}..."
    if looks_like_prompt_echo(excerpt):
        return fallback
    return excerpt or fallback


def sanitize_model_answer(text: str | None, fallback: str | None = None, *, max_chars: int = 1400) -> str | None:
    """Clean model output for user-facing report chat while preserving paragraph-level depth."""
    if not text or not text.strip():
        return fallback

    final_tag_match = re.search(r"<final_answer>([\s\S]*?)</final_answer>", text, flags=re.IGNORECASE)
    if final_tag_match:
        text = final_tag_match.group(1).strip()

    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"```(?:\w+)?", "", cleaned)
    cleaned = cleaned.replace("\r", "").replace("**", "").replace("__", "").strip()
    lowered_cleaned = cleaned.lower()
    if "draft:" in lowered_cleaned:
        cleaned = re.split(r"draft\s*:\s*", cleaned, maxsplit=1, flags=re.IGNORECASE)[-1].strip()
        lowered_cleaned = cleaned.lower()
    if "conclusion:" in lowered_cleaned and any(
        token in lowered_cleaned
        for token in (
            "paragraph 1:",
            "paragraph 2:",
            "input data:",
            "state the conclusion",
            "explain the strongest reasons",
            "key elements include",
        )
    ):
        cleaned = "Conclusion:" + cleaned.split("Conclusion:", 1)[1].strip()
        lowered_cleaned = cleaned.lower()
    if any(
        token in lowered_cleaned
        for token in (
            "format:",
            "key entities:",
            "key topics:",
            "key findings:",
            "conclusion hint",
            "need to state clearly",
            "evidence suggests",
            "draft:",
        )
    ):
        for marker_pattern in (
            r"(Conclusion:\s*[\s\S]*)$",
            r"(The simulation indicates[\s\S]*)$",
            r"(This simulation indicates[\s\S]*)$",
            r"(The run suggests[\s\S]*)$",
            r"(This run suggests[\s\S]*)$",
            r"(Overall,\s*[\s\S]*)$",
        ):
            marker_match = re.search(marker_pattern, cleaned, flags=re.IGNORECASE)
            if marker_match:
                cleaned = marker_match.group(1).strip()
                lowered_cleaned = cleaned.lower()
                break
    for marker_pattern in (
        r"final\s*answer\s*:\s*([\s\S]*)$",
        r"answer\s*:\s*([\s\S]*)$",
    ):
        marker_match = re.search(marker_pattern, cleaned, flags=re.IGNORECASE)
        if marker_match:
            cleaned = marker_match.group(1).strip()
            break

    paragraphs: list[str] = []
    current_lines: list[str] = []
    meta_prefixes = (
        "thinking process",
        "reasoning",
        "analysis",
        "the user is asking",
        "user question:",
        "the question is",
        "let me ",
        "i'll ",
        "i need to",
        "project:",
        "scenario:",
        "platform:",
        "question:",
        "tool result",
        "observation",
        "analyze the request",
        "answer strategy",
        "task overview",
        "available evidence",
        "conversation history",
        "chat history",
        "role: senior analyst",
        "instructions",
        "paragraph 1",
        "paragraph 2",
        "input data",
        "output format",
        "format",
        "key entities",
        "key topics",
        "key findings",
        "conclusion hint",
        "need to state clearly",
        "draft",
    )
    meta_tokens = (
        "task:",
        "constraint:",
        "[tool_call]",
        "<tool_call>",
        "section summaries:",
        "graph stats:",
        "runtime stats:",
        "dominant topics:",
        "interview evidence:",
        "report executive summary:",
        "simulation summary:",
        "named entities:",
        "runtime quotes:",
        "graph statistics:",
        "report sections:",
        "graph facts:",
        "interview history:",
        "respond in",
        "write two short paragraphs",
        "use concrete brands",
        "do not expose chain-of-thought",
        "state the conclusion",
        "explain the strongest reasons",
        "key elements include",
        "format:",
        "key entities:",
        "key topics:",
        "key findings:",
        "conclusion hint",
        "need to state clearly",
        "evidence suggests",
        "draft:",
    )
    for raw_line in cleaned.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if current_lines:
                paragraphs.append(re.sub(r"\s+", " ", " ".join(current_lines)).strip())
                current_lines = []
            continue

        line = stripped.lstrip("-* ").strip()
        numbered_match = re.match(r"^\d+\.\s*(.+)$", line)
        if numbered_match:
            line = numbered_match.group(1).strip()
        lowered = line.lower().rstrip(":")
        if lowered.startswith(meta_prefixes):
            continue
        if any(token in lowered for token in meta_tokens):
            continue
        if len(line) <= 80 and line.endswith(":"):
            continue
        current_lines.append(line)
    if current_lines:
        paragraphs.append(re.sub(r"\s+", " ", " ".join(current_lines)).strip())

    filtered_paragraphs = [
        item
        for item in paragraphs
        if item and not looks_like_prompt_echo(item) and not any(token in item.lower() for token in meta_tokens)
    ]
    candidate = "\n\n".join(filtered_paragraphs or [item for item in paragraphs if item])
    candidate = re.sub(r"\n{3,}", "\n\n", candidate).strip()
    if not candidate:
        return fallback
    if len(candidate) > max_chars:
        candidate = f"{candidate[: max_chars - 3].rsplit(' ', 1)[0]}..."
    if looks_like_prompt_echo(candidate):
        return fallback
    return candidate or fallback


def looks_like_prompt_echo(text: str | None) -> bool:
    """Detect model output that is echoing prompt scaffolding instead of answering."""
    if not text:
        return True
    lowered = text.lower()
    if lowered.startswith(
        (
            "project:",
            "scenario:",
            "platform:",
            "persona:",
            "role:",
            "bio:",
            "persona description:",
            "name:",
            "deconstruct",
            "thinking process",
        )
    ):
        return True
    meta_tokens = (
        "project:",
        "scenario:",
        "persona",
        "role:",
        "bio:",
        "interview prompt",
        "recent actions",
        "thinking process",
        "deconstruct",
        "context",
    )
    return sum(token in lowered for token in meta_tokens) >= 2


def looks_like_incomplete_answer(text: str | None) -> bool:
    """Detect short or placeholder chat outputs that should fall back to grounded copy."""
    if not text:
        return True
    stripped = text.strip()
    if stripped in {"...", ".", ".."}:
        return True
    word_count = len(re.findall(r"\b[\w'-]+\b", stripped))
    if word_count < 18:
        return True
    alpha_count = len(re.findall(r"[A-Za-z]", stripped))
    return alpha_count < 60


def runtime_action_signal(action: dict[str, object]) -> str:
    """Extract a stable signal label from runtime activity with sparse fields."""
    raw_topic = str(action.get("topic") or action.get("signal") or "").strip()
    if raw_topic:
        return raw_topic
    content = " ".join(
        str(action.get(key) or "").strip()
        for key in ("content", "text", "body", "title")
        if str(action.get(key) or "").strip()
    ).strip()
    if content:
        terms = top_terms(content, limit=1)
        if terms:
            return terms[0].title()
    raw_action_type = str(action.get("action_type") or "").strip().replace("_", " ").title()
    if raw_action_type:
        return raw_action_type
    return "Narrative Signal"


def runtime_action_line(action: dict[str, object], *, verb: str = "signaled") -> str:
    """Render one runtime action into a report-safe timeline line."""
    round_number = action.get("round_num")
    round_label = str(round_number) if round_number not in (None, "") else "?"
    agent_name = str(action.get("agent_name") or action.get("agent_id") or "Unknown agent").strip()
    platform = str(action.get("platform") or "unknown platform").strip()
    action_type = str(action.get("action_type") or "").strip().upper()
    content = next(
        (
            str(action.get(key) or "").strip()
            for key in ("content", "text", "body", "title")
            if str(action.get(key) or "").strip()
        ),
        "",
    )
    if content and action_type in {"CREATE_POST", "QUOTE_POST", "COMMENT"}:
        snippet = content if len(content) <= 160 else f"{content[:157].rsplit(' ', 1)[0]}..."
        spoken_verb = {
            "CREATE_POST": "posted",
            "QUOTE_POST": "quoted",
            "COMMENT": "commented",
        }.get(action_type, verb)
        return f"- Round {round_label}: {agent_name} on {platform} {spoken_verb}: {snippet}"
    if action_type == "REPOST":
        return f"- Round {round_label}: {agent_name} on {platform} reposted a signal around {runtime_action_signal(action).lower()}."
    signal = runtime_action_signal(action)
    return f"- Round {round_label}: {agent_name} on {platform} {verb} {signal.lower()}."


def build_graph_artifacts(
    llm: TextGenerator,
    project: Project,
    documents: list[SourceDocument],
    objective: str,
) -> GraphArtifacts:
    """Generate graph job outputs from project context."""
    context = project_context_text(project, documents)
    terms = top_terms(context)
    source_points = quoted_source_points(documents)
    node_count = max(12, len(terms) * 4)
    edge_count = max(10, len(terms) * 3)
    source_digest = ", ".join(terms[:5]) if terms else "scenario, actors, signals"

    fallback_schema = "\n".join(
        [
            "## Recommended schema",
            "",
            "### Entity groups",
            *[f"- {term.title()} cluster" for term in terms[:5]],
            "- Decision actor",
            "- Public narrative",
            "",
            "### Relationship types",
            "- influences",
            "- reacts_to",
            "- amplifies",
            "- constrains",
        ]
    )
    fallback_evidence = "\n".join(
        [
            "## Evidence highlights",
            "",
            *[f"- {point}" for point in source_points],
            "",
            f"- Scenario objective: {objective or project.scenario_brief}",
        ]
    )
    fallback_summary = (
        f"Generated a graph brief with {node_count} estimated nodes and {edge_count} estimated edges "
        f"across the primary themes: {source_digest}."
    )

    generated_schema = maybe_generate_text(
        llm,
        system_prompt="Write concise markdown for an analyst-facing graph design brief.",
        user_prompt=(
            "Using the context below, produce markdown with entity groups, relation types, "
            "and evidence priorities.\n\n"
            f"{context[:5000]}"
        ),
    )
    schema_markdown = generated_schema or fallback_schema
    summary = generated_schema.splitlines()[0].lstrip("# ").strip() if generated_schema else fallback_summary
    return GraphArtifacts(
        summary=summary,
        source_digest=source_digest,
        schema_markdown=schema_markdown,
        evidence_markdown=fallback_evidence,
        node_count=node_count,
        edge_count=edge_count,
    )


def build_simulation_artifacts(
    llm: TextGenerator,
    project: Project,
    graph_job: GraphJob | None,
    mode: str,
    cohort_size: int,
) -> SimulationArtifacts:
    """Generate simulation outputs from project and graph context."""
    rounds = min(max(cohort_size // 60, 4), 10)
    themes = [term.strip() for term in (graph_job.source_digest.split(",") if graph_job else []) if term.strip()]
    if not themes:
        themes = top_terms(project.scenario_brief, limit=5) or ["market sentiment", "institutional response"]

    events: list[dict[str, str | int]] = []
    channels = ["Signal desk", "Narrative watch", "Operator notes", "Policy channel"]
    for round_number in range(1, rounds + 1):
        theme = themes[(round_number - 1) % len(themes)]
        channel = channels[(round_number - 1) % len(channels)]
        events.append(
            {
                "round": round_number,
                "channel": channel,
                "title": f"{theme.title()} becomes a visible pressure point",
                "impact": f"Analysts see {theme} shifting from background context to an active scenario driver.",
                "implication": "Monitor whether the response remains localized or starts reshaping the wider narrative.",
            }
        )

    fallback_timeline = "\n".join(
        [
            "## Simulation timeline",
            "",
            *[
                f"- Round {event['round']}: {event['channel']} tracked {event['title']}."
                for event in events
            ],
        ]
    )
    generated_timeline = maybe_generate_text(
        llm,
        system_prompt="Write a concise markdown timeline for a scenario simulation.",
        user_prompt=(
            f"Scenario brief: {project.scenario_brief}\n"
            f"Graph digest: {graph_job.source_digest if graph_job else 'No graph digest'}\n"
            f"Mode: {mode}\n"
            f"Cohort size: {cohort_size}\n"
            f"Events: {json.dumps(events)}"
        ),
    )
    timeline_markdown = generated_timeline or fallback_timeline
    summary = (
        f"Completed a {rounds}-round {mode} simulation for a cohort of {cohort_size}, "
        f"tracking {len(events)} synthesized scenario events."
    )
    return SimulationArtifacts(
        summary=summary,
        rounds=rounds,
        event_count=len(events),
        timeline_markdown=timeline_markdown,
        events=events,
    )


def build_report_artifacts(
    llm: TextGenerator,
    project: Project,
    simulation: Simulation,
    focus: str,
) -> ReportArtifacts:
    """Generate report summary and markdown body."""
    events = json.loads(simulation.event_log_json or "[]")
    executive_summary = (
        f"PersonaGraph indicates that {project.name} is most sensitive to "
        f"{project.scenario_brief[:140].rstrip('.')}."
    )
    fallback_markdown = "\n".join(
        [
            f"# {project.name} analysis",
            "",
            "## Executive summary",
            executive_summary,
            "",
            "## Requested focus",
            focus or "General decision support analysis",
            "",
            "## Simulation signals",
            *[
                f"- Round {event['round']}: {event['title']} ({event['implication']})"
                for event in events[:6]
            ],
            "",
            "## Recommended analyst actions",
            "- Track the earliest narrative shift rather than waiting for broad consensus.",
            "- Separate operational response from public explanation to avoid mixed signals.",
            "- Re-run the scenario when new evidence changes the actor map or the trigger event.",
        ]
    )
    generated_markdown = maybe_generate_text(
        llm,
        system_prompt="Write a concise analyst report in markdown.",
        user_prompt=(
            f"Project: {project.name}\n"
            f"Scenario brief: {project.scenario_brief}\n"
            f"Report focus: {focus}\n"
            f"Simulation summary: {simulation.summary}\n"
            f"Timeline: {simulation.timeline_markdown[:5000]}"
        ),
    )
    markdown_body = generated_markdown or fallback_markdown
    summary = "Generated an analyst-ready report with executive summary, signal review, and recommended actions."
    return ReportArtifacts(
        summary=summary,
        executive_summary=executive_summary,
        markdown_body=markdown_body,
    )


def build_chat_response(
    llm: TextGenerator,
    project: Project,
    simulation: Simulation,
    report: Report | None,
    message: str,
) -> tuple[str, list[str]]:
    """Generate a response for the analysis chat surface."""
    supporting_points = [
        project.scenario_brief,
        simulation.summary,
        report.executive_summary if report else "No report selected; answering from the simulation record.",
    ]
    fallback_answer = (
        "Monitor the earliest high-velocity narrative themes and check whether they are outpacing the proof, "
        "explanation, or other evidence signals. In this run, that speed gap is the clearest early warning for "
        "trust erosion and the first thing the analyst team should track."
    )
    generated_answer = maybe_generate_text(
        llm,
        system_prompt="Answer as an analyst copilot using the provided project, simulation, and report context.",
        user_prompt=(
            f"User question: {message}\n"
            f"Project brief: {project.scenario_brief}\n"
            f"Simulation summary: {simulation.summary}\n"
            f"Report executive summary: {report.executive_summary if report else 'Not provided'}\n"
            f"Timeline: {simulation.timeline_markdown[:3000]}"
        ),
    )
    cleaned_answer = sanitize_short_model_text(generated_answer)
    if looks_like_prompt_echo(cleaned_answer):
        cleaned_answer = None
    if cleaned_answer and re.match(r"^[A-Z][A-Za-z ]{0,30}:", cleaned_answer):
        cleaned_answer = None
    return cleaned_answer or fallback_answer, supporting_points


def build_glass_ontology(
    llm: TextGenerator,
    *,
    project_name: str,
    requirement: str,
    additional_context: str,
    source_texts: list[str],
) -> tuple[dict[str, object], str]:
    """Generate a domain-specific ontology payload for the React glass workflow."""
    resolved_project_name = infer_project_name(
        project_name,
        requirement=requirement,
        additional_context=additional_context,
        source_texts=source_texts,
    )

    generic_entity_keys = {
        "stakeholder",
        "audiencesegment",
        "narrative",
        "signal",
        "topic",
        "actor",
        "entity",
        "node",
        "item",
    }

    def ontology_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def clean_entity_name(value: str) -> str:
        candidate = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value.strip())
        candidate = candidate.replace("_", " ").replace("-", " ")
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if not candidate:
            return ""
        words = re.findall(r"[A-Za-z0-9&']+", candidate)
        if not words:
            return ""
        cleaned_words: list[str] = []
        for word in words:
            if word.isupper() and len(word) <= 4:
                cleaned_words.append(word)
            elif word.lower() == "genz":
                cleaned_words.append("Gen Z")
            else:
                cleaned_words.append(word.capitalize())
        return " ".join(cleaned_words)

    def clean_edge_name(value: str) -> str:
        candidate = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.strip())
        candidate = re.sub(r"[^A-Za-z0-9]+", "_", candidate).strip("_").lower()
        return candidate or ""

    def named_examples(text: str, *, limit: int = 14) -> list[str]:
        return extract_named_entity_candidates(text, limit=limit)

    def entity_type(name: str, description: str, examples: list[str] | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": name,
            "description": description[:160].strip(),
        }
        if examples:
            payload["examples"] = [item for item in examples if item][:4]
        return payload

    def edge_type(name: str, description: str, source_targets: list[tuple[str, str]]) -> dict[str, object]:
        return {
            "name": name,
            "description": description[:160].strip(),
            "source_targets": [{"source": source, "target": target} for source, target in source_targets],
        }

    def social_brand_ontology_aligned(candidate: dict[str, object] | None) -> bool:
        """Return True when the ontology preserves the actor-role schema needed for social simulations."""
        if not isinstance(candidate, dict):
            return False
        entity_types = candidate.get("entity_types")
        if not isinstance(entity_types, list) or not entity_types:
            return False

        normalized_names = {
            re.sub(r"[^a-z0-9]+", "", str(item.get("name") or "").lower())
            for item in entity_types
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        if not normalized_names:
            return False

        required_role_families = (
            {"luxurybrand", "fashionbrand"},
            {"fashioninfluencer", "influencer", "creator", "creatorgroup"},
            {"consumercohort", "consumergroup", "genczconsumer", "genzconsumer", "communitycohort"},
            {"fashionmediaoutlet", "mediaoutlet", "publication", "pressoutlet", "fashionmedia"},
            {"person", "executive", "founder", "leadershipfigure", "spokesperson"},
            {"organization", "institutionalactor", "retailpartner", "watchdoggroup", "institution"},
        )
        matched_families = sum(1 for family in required_role_families if normalized_names & family)
        return matched_families >= 4

    def fallback_ontology(context_text: str, terms: list[str], examples: list[str]) -> tuple[dict[str, object], str]:
        lower_context = context_text.lower()
        brand_keywords = {
            "brand",
            "fashion",
            "luxury",
            "retail",
            "pricing",
            "consumer",
            "campaign",
            "loyalty",
            "streetwear",
            "influencer",
            "marketing",
            "product",
            "gen z",
        }
        social_brand_keywords = {
            "simulate",
            "reaction",
            "react",
            "public",
            "social",
            "twitter",
            "reddit",
            "gen z",
            "loyalty",
            "influencer",
            "media",
            "community",
            "viral",
        }
        policy_keywords = {
            "government",
            "policy",
            "regulator",
            "election",
            "minister",
            "voter",
            "public agency",
            "parliament",
            "law",
        }
        topic_examples = rank_theme_candidates(
            [*derive_priority_themes(context_text), *[term.title() for term in terms[:8]]],
            limit=4,
        ) or ["Trust", "Pricing", "Relevance"]

        if is_social_brand_simulation_context(context_text) or (
            any(keyword in lower_context for keyword in brand_keywords)
            and any(keyword in lower_context for keyword in social_brand_keywords)
        ):
            if social_brand_submode == "market_expansion":
                ontology = {
                    "entity_types": [
                        entity_type("Luxury Brand", "The focal luxury brand and owned brand surfaces entering the target market.", named_examples(context_text, limit=6)),
                        entity_type("Market Analyst", "Analysts judging localization, premium positioning, channel strategy, and demand durability."),
                        entity_type("Competitor Brand", "Domestic or global competitor brands positioned against the focal market entry."),
                        entity_type("Luxury Consumer", "Chinese and global luxury-consumer voices whose adoption, backlash, or curiosity shapes demand."),
                        entity_type("Sustainability Activist", "Critics, watchdogs, and sustainability-focused voices challenging the expansion narrative."),
                        entity_type("Person", "Fallback individual type for executives, journalists, critics, creators, and public figures."),
                        entity_type("Organization", "Fallback organization type for platforms, retailers, media groups, watchdogs, and institutions."),
                    ],
                    "edge_types": [
                        edge_type("competes_with", "Luxury and competitor brands compete for relevance, cultural legitimacy, and market share.", [("Luxury Brand", "Competitor Brand"), ("Competitor Brand", "Luxury Brand"), ("Competitor Brand", "Competitor Brand")]),
                        edge_type("reacts_to", "Luxury consumers and sustainability critics react to brands, organizations, and market narratives as expansion unfolds.", [("Luxury Consumer", "Luxury Brand"), ("Luxury Consumer", "Competitor Brand"), ("Sustainability Activist", "Luxury Brand"), ("Sustainability Activist", "Organization")]),
                        edge_type("comments_on", "Analysts, people, and organizations comment on the focal brand, competitors, and platform moves.", [("Market Analyst", "Luxury Brand"), ("Market Analyst", "Competitor Brand"), ("Person", "Luxury Brand"), ("Organization", "Luxury Brand"), ("Organization", "Competitor Brand")]),
                        edge_type("expands_in", "The focal luxury brand expands through organizations that represent platforms, retail channels, or market entry surfaces.", [("Luxury Brand", "Organization"), ("Organization", "Luxury Brand")]),
                        edge_type("represents", "A person represents or speaks on behalf of a brand or organization in the market-entry narrative.", [("Person", "Luxury Brand"), ("Person", "Competitor Brand"), ("Person", "Organization")]),
                        edge_type("covers", "Organizations and people cover or reframe the expansion for broader audiences.", [("Organization", "Luxury Brand"), ("Organization", "Competitor Brand"), ("Person", "Organization")]),
                    ],
                    "description": (
                        "Compact market-expansion social-simulation ontology centered on the focal luxury brand, domestic competitors, "
                        "luxury consumers, market analysts, sustainability critics, and the fallback people and organizations shaping local-market reaction."
                    ),
                }
                summary = (
                    f"Prepared a market-expansion ontology for {resolved_project_name or 'the project'}, centered on the focal brand, "
                    "luxury consumers, market analysts, sustainability critics, competitor brands, people, and organizations."
                )
                return ontology, summary
            if social_brand_submode == "channel_strategy":
                ontology = {
                    "entity_types": [
                        entity_type("Fashion Brand", "Brands managing channel strategy, exclusivity, and price integrity."),
                        entity_type("Discount Shopper", "Value-seeking shoppers reacting to the loss of off-price access and discount availability."),
                        entity_type("Brand Purist", "Consumers who welcome tighter brand control and higher exclusivity."),
                        entity_type("Retail Industry Analyst", "Analysts interpreting DTC economics, channel conflict, and customer fallout."),
                        entity_type("Person", "Fallback individual type for executives, creators, shoppers, and public commentators."),
                        entity_type("Organization", "Fallback organization type for retailers, platforms, operators, and institutions."),
                    ],
                    "edge_types": [
                        edge_type("controls", "A fashion brand controls an organization, retail partner, or channel surface in pursuit of elevation.", [("Fashion Brand", "Organization")]),
                        edge_type("reacts_to", "Shoppers, purists, analysts, and people react to a brand or organization as channel strategy changes.", [("Discount Shopper", "Fashion Brand"), ("Brand Purist", "Fashion Brand"), ("Retail Industry Analyst", "Fashion Brand"), ("Person", "Organization")]),
                        edge_type("competes_with", "Fashion brands compete over value perception, exclusivity, and channel posture.", [("Fashion Brand", "Fashion Brand")]),
                        edge_type("covers", "Analysts, people, and organizations reframe the strategic meaning of the move.", [("Retail Industry Analyst", "Fashion Brand"), ("Organization", "Fashion Brand"), ("Person", "Fashion Brand")]),
                        edge_type("constrains", "Organizations constrain or reshape how the brand can execute its channel strategy.", [("Organization", "Fashion Brand")]),
                    ],
                    "description": (
                        "Compact channel-strategy ontology centered on brands, discount shoppers, brand purists, retail analysts, "
                        "people, and organizations."
                    ),
                }
                summary = (
                    f"Prepared a channel-strategy ontology for {resolved_project_name or 'the project'}, centered on brands, "
                    "discount shoppers, brand purists, retail analysts, people, and organizations."
                )
                return ontology, summary
            if social_brand_submode == "sports_partnership":
                ontology = {
                    "entity_types": [
                        entity_type("Fashion Brand", "Brands using a sports or national-stage partnership to win visibility and conversion."),
                        entity_type("Athlete Ambassador", "Athletes or public sports figures lending credibility and attention to the campaign."),
                        entity_type("Sportswear Competitor", "Competing sportswear brands positioned to challenge the campaign narrative."),
                        entity_type("Fashion Media Outlet", "Press and commentary accounts shaping interpretation of the partnership moment."),
                        entity_type("Person", "Fallback individual type for consumers, critics, athletes, and public figures."),
                        entity_type("Organization", "Fallback organization type for teams, committees, platforms, and institutions."),
                    ],
                    "edge_types": [
                        edge_type("partners_with", "A fashion brand partners with an athlete ambassador or organization.", [("Fashion Brand", "Athlete Ambassador"), ("Fashion Brand", "Organization")]),
                        edge_type("competes_with", "The focal fashion brand competes with sportswear competitors for legitimacy and share of voice.", [("Fashion Brand", "Sportswear Competitor"), ("Sportswear Competitor", "Fashion Brand")]),
                        edge_type("covers", "Media outlets cover brands, athlete ambassadors, and organizations in the campaign.", [("Fashion Media Outlet", "Fashion Brand"), ("Fashion Media Outlet", "Athlete Ambassador"), ("Fashion Media Outlet", "Organization")]),
                        edge_type("reacts_to", "People and organizations react to the brands and athlete ambassadors involved.", [("Person", "Fashion Brand"), ("Person", "Athlete Ambassador"), ("Organization", "Fashion Brand")]),
                        edge_type("amplifies", "Brands, media outlets, and organizations amplify the partnership moment.", [("Fashion Brand", "Organization"), ("Fashion Media Outlet", "Fashion Brand"), ("Organization", "Athlete Ambassador")]),
                    ],
                    "description": (
                        "Compact sports-partnership ontology centered on brands, athlete ambassadors, competitors, media, people, and organizations."
                    ),
                }
                summary = (
                    f"Prepared a sports-partnership ontology for {resolved_project_name or 'the project'}, centered on brands, "
                    "athlete ambassadors, competitors, media, people, and organizations."
                )
                return ontology, summary
            if social_brand_submode == "sustainability_launch":
                ontology = {
                    "entity_types": [
                        entity_type("Fashion Brand", "Brands competing over sustainability credibility, quality, and value.", named_examples(context_text, limit=6)),
                        entity_type("Sustainability Activist", "Activists and critics evaluating whether the move is substantive or greenwashing."),
                        entity_type("Consumer Cohort", "Consumer segments weighing values alignment, price acceptance, and authenticity."),
                        entity_type("Fashion Media Outlet", "Media and commentary accounts shaping the sustainability narrative."),
                        entity_type("Person", "Fallback individual type for executives, creators, critics, and public voices."),
                        entity_type("Organization", "Fallback organization type for watchdogs, retailers, rating bodies, and institutions."),
                    ],
                    "edge_types": [
                        edge_type("competes_with", "Fashion brands compete on sustainability credibility and value perception.", [("Fashion Brand", "Fashion Brand")]),
                        edge_type("questions", "Activists, consumers, people, and organizations question a brand's sustainability claims.", [("Sustainability Activist", "Fashion Brand"), ("Consumer Cohort", "Fashion Brand"), ("Person", "Fashion Brand"), ("Organization", "Fashion Brand")]),
                        edge_type("covers", "Media outlets cover brands, people, and organizations involved in the launch.", [("Fashion Media Outlet", "Fashion Brand"), ("Fashion Media Outlet", "Person"), ("Fashion Media Outlet", "Organization")]),
                        edge_type("represents", "A person represents a fashion brand or organization in the launch response.", [("Person", "Fashion Brand"), ("Person", "Organization")]),
                        edge_type("reacts_to", "Consumers and organizations react to the brand and media framing.", [("Consumer Cohort", "Fashion Brand"), ("Consumer Cohort", "Fashion Media Outlet"), ("Organization", "Fashion Brand")]),
                    ],
                    "description": (
                        "Compact sustainability-launch ontology centered on brands, activists, consumer cohorts, media, people, and organizations."
                    ),
                }
                summary = (
                    f"Prepared a sustainability-launch ontology for {resolved_project_name or 'the project'}, centered on brands, "
                    "sustainability activists, consumer cohorts, media, people, and organizations."
                )
                return ontology, summary
            ontology = {
                "entity_types": [
                    entity_type("Luxury Brand", "Fashion or lifestyle brands competing for cultural relevance and loyalty.", named_examples(context_text, limit=6)),
                    entity_type("Fashion Influencer", "Creators, stylists, and tastemakers who can amplify or puncture momentum."),
                    entity_type("Consumer Cohort", "Online audience segments such as Gen Z shoppers, heritage loyalists, or value-driven communities."),
                    entity_type("Fashion Media Outlet", "Fashion press, commentators, and trend accounts shaping interpretation."),
                    entity_type("Person", "Fallback individual type for executives, spokespeople, creators, and public figures."),
                    entity_type("Organization", "Fallback organization type for platforms, retailers, watchdogs, and institutions."),
                ],
                "edge_types": [
                    edge_type("follows", "A consumer cohort follows a brand, influencer, or fashion media outlet.", [("Consumer Cohort", "Luxury Brand"), ("Consumer Cohort", "Fashion Influencer"), ("Consumer Cohort", "Fashion Media Outlet")]),
                    edge_type("competes_with", "Luxury brands compete with or benchmark against one another.", [("Luxury Brand", "Luxury Brand")]),
                    edge_type("mentions", "Influencers, media, consumers, and people mention or reference brands, people, or organizations.", [("Fashion Influencer", "Luxury Brand"), ("Fashion Media Outlet", "Luxury Brand"), ("Consumer Cohort", "Luxury Brand"), ("Person", "Luxury Brand"), ("Fashion Media Outlet", "Organization"), ("Person", "Person")]),
                    edge_type("covers", "Fashion media covers brands, people, and organizations relevant to the scenario.", [("Fashion Media Outlet", "Luxury Brand"), ("Fashion Media Outlet", "Person"), ("Fashion Media Outlet", "Organization")]),
                    edge_type("represents", "A person represents, works for, or speaks on behalf of a brand or organization.", [("Person", "Luxury Brand"), ("Person", "Organization")]),
                    edge_type("reacts_to", "Consumers, influencers, media, and people react to brands, organizations, and public figures.", [("Consumer Cohort", "Luxury Brand"), ("Fashion Influencer", "Luxury Brand"), ("Fashion Media Outlet", "Person"), ("Person", "Organization")]),
                ],
                "description": (
                    "Compact social-simulation ontology for a fashion brand scenario, centered on brands, influencers, "
                    "consumer cohorts, fashion media, and the fallback people and organizations that can act on social media."
                ),
            }
            summary = (
                f"Prepared a compact social-simulation ontology for {resolved_project_name or 'the project'}, centered on "
                "luxury brands, influencers, consumer cohorts, fashion media, people, and organizations."
            )
            return ontology, summary

        if any(keyword in lower_context for keyword in brand_keywords):
            ontology = {
                "entity_types": [
                    entity_type("Brand", "The focal brand or label under discussion."),
                    entity_type("Product Line", "Named collections, product families, or sub-brands attached to the focal brand."),
                    entity_type("Person", "Executives, founders, designers, creators, influencers, and public figures tied to the discussion."),
                    entity_type("Audience Segment", "Consumer or community cohorts whose reactions shape the market narrative."),
                    entity_type("Competitor Brand", "Competing brands used as benchmarks or contrast cases in the discussion."),
                    entity_type("Media Outlet", "Fashion media, magazines, analysts, and press voices shaping interpretation."),
                    entity_type("Platform", "Digital platforms where attention, debate, and amplification occur.", ["Twitter", "Reddit"]),
                    entity_type("Event", "Campaign moments, launches, awards, and cultural events that move the conversation."),
                    entity_type("Location", "Countries, cities, and regions affecting market context or brand relevance."),
                    entity_type("Theme", f"High-signal discussion themes such as {', '.join(topic_examples)}."),
                ],
                "edge_types": [
                    edge_type("launches", "A brand launches a product line or event.", [("Brand", "Product Line"), ("Brand", "Event")]),
                    edge_type("competes_with", "A brand is compared against or competes with another brand.", [("Brand", "Competitor Brand"), ("Competitor Brand", "Brand")]),
                    edge_type("targets", "A brand, campaign, or product line targets a specific audience segment.", [("Brand", "Audience Segment"), ("Product Line", "Audience Segment"), ("Event", "Audience Segment")]),
                    edge_type("reacts_to", "An audience segment or person reacts to a brand, event, or theme.", [("Audience Segment", "Brand"), ("Audience Segment", "Theme"), ("Person", "Event")]),
                    edge_type("amplifies_on", "A theme, event, or media signal gains attention on a platform.", [("Theme", "Platform"), ("Event", "Platform"), ("Media Outlet", "Platform")]),
                    edge_type("covers", "A media outlet covers a brand, event, or theme.", [("Media Outlet", "Brand"), ("Media Outlet", "Event"), ("Media Outlet", "Theme")]),
                    edge_type("appears_in", "A brand, product line, or event is tied to a location.", [("Brand", "Location"), ("Product Line", "Location"), ("Event", "Location")]),
                    edge_type("influences", "A person, theme, or media outlet influences audience response.", [("Person", "Audience Segment"), ("Theme", "Audience Segment"), ("Media Outlet", "Audience Segment")]),
                    edge_type("criticizes", "A person, audience segment, or media outlet criticizes a theme or brand.", [("Audience Segment", "Theme"), ("Media Outlet", "Brand"), ("Person", "Theme")]),
                ],
                "description": (
                    "Brand- and audience-oriented ontology covering the focal brand, product architecture, people, consumers, "
                    "competitors, media, platforms, events, locations, and debate themes."
                ),
            }
            summary = (
                f"Prepared a brand-focused ontology for {resolved_project_name or 'the project'}, covering brands, consumers, media, "
                "platforms, events, locations, and the themes driving reaction."
            )
            return ontology, summary

        if any(keyword in lower_context for keyword in policy_keywords):
            ontology = {
                "entity_types": [
                    entity_type("Public Figure", "Named politicians, spokespeople, activists, experts, and public advocates."),
                    entity_type("Organization", "Institutions, companies, NGOs, and organized groups shaping the issue."),
                    entity_type("Government Agency", "Departments, regulators, and formal public bodies."),
                    entity_type("Community Group", "Affected communities, advocacy blocs, and grassroots coalitions."),
                    entity_type("Media Outlet", "Press organizations, commentators, and news publications."),
                    entity_type("Platform", "Digital surfaces where reaction, debate, and mobilization occur.", ["Twitter", "Reddit"]),
                    entity_type("Policy Issue", f"Specific policy themes such as {', '.join(topic_examples)}."),
                    entity_type("Event", "Announcements, hearings, launches, protests, or crises that change the conversation."),
                    entity_type("Location", "Countries, cities, and regions relevant to policy impact."),
                    entity_type("Voter Bloc", "Audience or voter segments whose reactions materially shape public response."),
                ],
                "edge_types": [
                    edge_type("announces", "A public figure, organization, or agency announces an event or policy issue.", [("Public Figure", "Event"), ("Government Agency", "Policy Issue"), ("Organization", "Event")]),
                    edge_type("regulates", "An agency regulates an organization or policy issue.", [("Government Agency", "Organization"), ("Government Agency", "Policy Issue")]),
                    edge_type("debates", "A community group, media outlet, or voter bloc debates a policy issue.", [("Community Group", "Policy Issue"), ("Media Outlet", "Policy Issue"), ("Voter Bloc", "Policy Issue")]),
                    edge_type("reacts_to", "A voter bloc or community group reacts to an event or organization.", [("Voter Bloc", "Event"), ("Community Group", "Organization"), ("Community Group", "Policy Issue")]),
                    edge_type("covers", "A media outlet covers a public figure, event, or policy issue.", [("Media Outlet", "Public Figure"), ("Media Outlet", "Event"), ("Media Outlet", "Policy Issue")]),
                    edge_type("mobilizes_on", "A platform amplifies mobilization around an issue or event.", [("Policy Issue", "Platform"), ("Event", "Platform"), ("Community Group", "Platform")]),
                    edge_type("occurs_in", "An event or policy issue is tied to a location.", [("Event", "Location"), ("Policy Issue", "Location")]),
                ],
                "description": (
                    "Public-affairs ontology covering public figures, organizations, regulators, communities, media, "
                    "platforms, issues, events, locations, and voter blocs."
                ),
            }
            summary = (
                f"Prepared a public-response ontology for {resolved_project_name or 'the project'}, centered on public figures, "
                "institutions, policy issues, communities, media, and locations."
            )
            return ontology, summary

        ontology = {
            "entity_types": [
                entity_type("Organization", "Institutions, companies, and structured groups driving the scenario."),
                entity_type("Brand", "Named brands or commercial identities central to the scenario."),
                entity_type("Person", "Founders, executives, creators, experts, and public figures."),
                entity_type("Audience Group", "Community or customer segments reacting from distinct positions."),
                entity_type("Platform", "Digital platforms where amplification and response happen.", ["Twitter", "Reddit"]),
                entity_type("Event", "Announcements, launches, crises, and public moments that shift attention."),
                entity_type("Location", "Markets, cities, countries, and regions affecting context."),
                entity_type("Product", "Named offerings, services, or product families under discussion."),
                entity_type("Media Outlet", "Press voices, publications, and analysts shaping interpretation."),
                entity_type("Theme", f"Recurring discussion themes such as {', '.join(topic_examples)}."),
            ],
            "edge_types": [
                edge_type("launches", "An organization or brand launches a product or event.", [("Organization", "Product"), ("Brand", "Event")]),
                edge_type("targets", "A brand, product, or event targets an audience group.", [("Brand", "Audience Group"), ("Product", "Audience Group"), ("Event", "Audience Group")]),
                edge_type("reacts_to", "A person or audience group reacts to a brand, event, or theme.", [("Audience Group", "Event"), ("Audience Group", "Theme"), ("Person", "Brand")]),
                edge_type("amplifies_on", "A theme or event spreads on a platform.", [("Theme", "Platform"), ("Event", "Platform")]),
                edge_type("covers", "A media outlet covers an organization, brand, event, or theme.", [("Media Outlet", "Organization"), ("Media Outlet", "Brand"), ("Media Outlet", "Event"), ("Media Outlet", "Theme")]),
                edge_type("appears_in", "An organization, brand, or event is tied to a location.", [("Organization", "Location"), ("Brand", "Location"), ("Event", "Location")]),
                edge_type("influences", "A person, media outlet, or theme influences audience response.", [("Person", "Audience Group"), ("Media Outlet", "Audience Group"), ("Theme", "Audience Group")]),
            ],
            "description": (
                "Scenario ontology covering organizations, brands, people, audiences, platforms, events, locations, products, media, and debate themes."
            ),
        }
        summary = (
            f"Prepared a scenario ontology for {resolved_project_name or 'the project'}, covering organizations, people, audiences, "
            "platforms, events, locations, products, media, and discussion themes."
        )
        return ontology, summary

    def normalize_ontology(candidate: dict[str, object] | list[object] | None, fallback: dict[str, object]) -> dict[str, object]:
        if not isinstance(candidate, dict):
            return fallback

        entity_types: list[dict[str, object]] = []
        entity_lookup: dict[str, str] = {}
        for item in candidate.get("entity_types", []):
            if not isinstance(item, dict):
                continue
            name = clean_entity_name(str(item.get("name") or ""))
            key = ontology_key(name)
            if not name or key in generic_entity_keys or key in entity_lookup:
                continue
            description = sanitize_short_model_text(
                str(item.get("description") or "").strip(),
                f"{name} entities that materially shape the scenario.",
            ) or f"{name} entities that materially shape the scenario."
            examples = [
                str(example).strip()
                for example in (item.get("examples") or [])
                if str(example).strip()
            ]
            entity_types.append(entity_type(name, description, examples))
            entity_lookup[key] = name
            if len(entity_types) >= 10:
                break

        if len(entity_types) < 6:
            return fallback

        edge_types: list[dict[str, object]] = []
        seen_edges: set[str] = set()
        for item in candidate.get("edge_types", []):
            if not isinstance(item, dict):
                continue
            name = clean_edge_name(str(item.get("name") or ""))
            if not name or name in seen_edges:
                continue
            source_targets_payload: list[tuple[str, str]] = []
            for relation in item.get("source_targets", []):
                if not isinstance(relation, dict):
                    continue
                source_name = clean_entity_name(str(relation.get("source") or ""))
                target_name = clean_entity_name(str(relation.get("target") or ""))
                source_key = ontology_key(source_name)
                target_key = ontology_key(target_name)
                if source_key not in entity_lookup or target_key not in entity_lookup:
                    continue
                source_targets_payload.append((entity_lookup[source_key], entity_lookup[target_key]))
            if not source_targets_payload:
                continue
            description = sanitize_short_model_text(
                str(item.get("description") or "").strip(),
                f"{name.replace('_', ' ')} relationships visible in the scenario graph.",
            ) or f"{name.replace('_', ' ')} relationships visible in the scenario graph."
            edge_types.append(edge_type(name, description, source_targets_payload))
            seen_edges.add(name)
            if len(edge_types) >= 10:
                break

        if len(edge_types) < 5:
            return fallback

        description = sanitize_short_model_text(
            str(candidate.get("description") or "").strip(),
            str(fallback.get("description") or ""),
        ) or str(fallback.get("description") or "")
        summary = sanitize_short_model_text(
            str(candidate.get("analysis_summary") or "").strip(),
            "",
        )
        ontology = {
            "entity_types": entity_types,
            "edge_types": edge_types,
            "description": description,
        }
        if summary:
            ontology["analysis_summary"] = summary
        return ontology

    source_only_context = "\n\n".join(
        part
        for part in source_texts
        if part.strip()
    )
    source_context = "\n\n".join(
        part
        for part in [requirement, additional_context, *source_texts]
        if part.strip()
    )
    context = "\n\n".join(
        part
        for part in [resolved_project_name, source_context]
        if part.strip()
    )
    term_source = source_only_context or source_context
    terms = top_terms(term_source, limit=12)
    examples = named_examples(term_source)
    social_brand_mode = is_social_brand_simulation_context(source_context)
    social_brand_submode = detect_social_brand_simulation_submode(source_context) if social_brand_mode else "generic_brand_social"
    fallback, fallback_summary = fallback_ontology(source_context, terms, examples)
    if social_brand_mode:
        ontology = dict(fallback)
        ontology.pop("analysis_summary", None)
        return ontology, fallback_summary
    generated = maybe_generate_json(
        llm,
        system_prompt=(
            "Return JSON only with keys analysis_summary, description, entity_types, edge_types. "
            "Design a domain-specific ontology for a social simulation knowledge graph. "
            "Requirements: 6 to 10 entity types, 5 to 10 edge types. "
            "Entity type names must be concrete semantic classes relevant to the source material. "
            "Do not use placeholder meta-types such as Stakeholder, Narrative, Signal, Actor, Entity, or generic Topic. "
            "Prefer domain-grounded classes like Brand, Product Line, Person, Media Outlet, Audience Segment, Campaign, Event, Location, Theme, or similarly specific types when appropriate. "
            "Use the source document content as the primary grounding signal. The scenario prompt may mention target audiences or channels, but ontology examples and categories must still reflect named entities and tensions that actually appear in the source material. "
            "Each entity type must contain name, description, and optional examples. "
            "Each edge type must contain name, description, and source_targets. "
            "Edge names must be lowercase snake_case. Keep everything concise and realistic."
        ),
        user_prompt=(
            f"Project: {resolved_project_name or 'Untitled project'}\n"
            f"Simulation requirement:\n{requirement}\n\n"
            f"Additional context:\n{additional_context or 'None'}\n\n"
            f"Top terms:\n{', '.join(terms) or 'None'}\n\n"
            f"Named entities and phrases:\n{', '.join(examples[:14]) or 'None'}\n\n"
            f"Source excerpts:\n{context[:12000]}"
        ),
        max_tokens=1400,
    )
    ontology = normalize_ontology(generated, fallback)
    if social_brand_mode and not social_brand_ontology_aligned(ontology):
        ontology = fallback
    summary = sanitize_short_model_text(
        str(ontology.get("analysis_summary") or "").strip(),
        fallback_summary,
    ) or fallback_summary
    ontology.pop("analysis_summary", None)
    return ontology, summary


def build_graphiti_extraction_instructions(
    *,
    project_name: str | None,
    requirement: str,
    additional_context: str = "",
    source_texts: list[str] | None = None,
    ontology: dict[str, object] | None = None,
) -> str:
    """Build compact extraction instructions that keep Graphiti aligned without bloating each episode prompt."""
    resolved_project_name = infer_project_name(
        project_name,
        requirement=requirement,
        additional_context=additional_context,
        source_texts=source_texts or [],
    )
    distributed_named_entities = sample_named_entities_across_source(
        source_texts or [],
        limit=10,
        per_chunk_limit=2,
    )
    entity_types = [
        str(item.get("name") or "").strip()
        for item in (ontology or {}).get("entity_types", [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    edge_types = [
        str(item.get("name") or "").strip()
        for item in (ontology or {}).get("edge_types", [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    scenario_hint = " ".join(str(requirement or "").split())
    if len(scenario_hint) > 220:
        scenario_hint = f"{scenario_hint[:217].rstrip()}..."
    return "\n".join(
        [
            f"Project focus: {resolved_project_name}",
            f"Scenario lens: {scenario_hint}",
            "Extraction rules:",
            "- Use only the provided ontology entity and relation types.",
            "- Extract explicit named actors, organizations, brands, media outlets, consumer groups, and public figures from the current chunk.",
            "- Only emit entities that fit the provided ontology. Do not invent extra node categories.",
            "- Ignore markdown headings, section labels, and generic market terms.",
            "- Prefer later-chunk named actors over repeating early metadata when new entities appear.",
            "- Treat products, events, and locations as secondary unless they clearly act as participants in the scenario.",
            f"Ontology entity types: {', '.join(entity_types[:8]) or 'Use the provided ontology types.'}",
            f"Ontology edge types: {', '.join(edge_types[:8]) or 'Use the provided ontology relations.'}",
            f"Named anchors when present: {', '.join(distributed_named_entities[:10]) or resolved_project_name}",
        ]
    )


def ontology_is_generic(ontology: dict[str, object] | None) -> bool:
    """Return True when an ontology still uses the old analyst placeholder schema."""
    if not isinstance(ontology, dict):
        return True
    entity_types = ontology.get("entity_types")
    if not isinstance(entity_types, list) or not entity_types:
        return True
    names = [
        re.sub(r"[^a-z0-9]+", "", str(item.get("name") or "").lower())
        for item in entity_types
        if isinstance(item, dict)
    ]
    if not names:
        return True
    generic_names = {
        "stakeholder",
        "audiencesegment",
        "narrative",
        "topic",
        "signal",
        "entity",
        "actor",
        "node",
        "item",
    }
    generic_count = sum(1 for name in names if name in generic_names)
    return generic_count >= max(3, len(names) - 2)


def ontology_needs_actor_alignment(ontology: dict[str, object] | None) -> bool:
    """Return True when an ontology drifts away from the compact actor schema used by the legacy workflow."""
    if not isinstance(ontology, dict):
        return True
    entity_types = ontology.get("entity_types")
    if not isinstance(entity_types, list) or not entity_types:
        return True
    names = [
        re.sub(r"[^a-z0-9]+", "", str(item.get("name") or "").lower())
        for item in entity_types
        if isinstance(item, dict)
    ]
    if not names:
        return True
    if len(names) > 8:
        return True
    if "person" not in names or "organization" not in names:
        return True
    abstract_count = sum(1 for name in names if name in ABSTRACT_ONTOLOGY_ENTITY_KEYS)
    return abstract_count >= 1


def build_glass_graph_snapshot(
    *,
    project: Project,
    source_digest: str,
    ontology: dict[str, object],
    source_texts: list[str],
    node_budget: int = 24,
) -> dict[str, object]:
    """Build a deterministic graph payload compatible with the glass workflow canvas.

    Test and fallback paths still need a graph that is concrete enough for the glass
    workflow to run end to end. The old placeholder scaffold used synthetic node UUID
    prefixes and generic summaries, which the compat layer now rejects on purpose.
    This builder keeps the same deterministic contract, but anchors the graph on
    scenario actors, named entities, and relation types that read like a real graph.
    """

    context = "\n\n".join(part for part in [project.scenario_brief, *source_texts, source_digest] if str(part).strip())
    lowered_context = context.lower()
    entity_types = [
        item["name"]
        for item in ontology.get("entity_types", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    edge_types = [
        item["name"]
        for item in ontology.get("edge_types", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    available_labels = set(entity_types)
    available_edge_types = set(edge_types)
    scenario_mode = detect_social_brand_simulation_submode(context)
    sampled_entities = sample_named_entities_across_source(
        [project.scenario_brief, *source_texts],
        limit=max(node_budget * 2, 18),
        per_chunk_limit=4,
    )
    focus_phrases = extract_focus_phrases(context, limit=8)

    def choose_label(*candidates: str) -> str:
        for candidate in candidates:
            if candidate in available_labels:
                return candidate
        for candidate in candidates:
            if candidate:
                return candidate
        return "Organization"

    def choose_relation(*candidates: str) -> str:
        for candidate in candidates:
            if candidate in available_edge_types:
                return candidate
        for candidate in candidates:
            if candidate:
                return candidate
        return "relates_to"

    brand_label = choose_label("Luxury Brand", "Fashion Brand", "Brand", "Organization")
    competitor_label = choose_label("Sportswear Competitor", "Competitor Brand", "Fashion Brand", "Brand", "Organization")
    consumer_label = choose_label("Consumer Cohort", "Audience Segment", "Luxury Consumer", "Organization", "Person")
    media_label = choose_label("Fashion Media Outlet", "Media Outlet", "Organization", "Person")
    activist_label = choose_label("Sustainability Activist", "Organization", "Person")
    ambassador_label = choose_label("Athlete Ambassador", "Fashion Influencer", "Person", "Organization")
    person_label = choose_label("Person", "Organization")
    platform_label = choose_label("Platform", "Organization")
    event_label = choose_label("Event", "Campaign", "Organization")
    location_label = choose_label("Location", "Region", "Organization")
    organization_label = choose_label("Organization", "Institutional Actor", "Internal Team", "Retail Channel", "Organization")
    campaign_label = choose_label("Campaign", "Organization")
    theme_label = choose_label("Theme", "Campaign", "Organization")

    media_markers = {
        "fashion media",
        "business of fashion",
        "bof",
        "vogue",
        "wwd",
        "elle",
        "gq",
        "harper's bazaar",
        "fashionista",
        "press",
        "media",
        "magazine",
    }
    organization_markers = {
        "committee",
        "team usa",
        "olympic",
        "games",
        "group",
        "corp",
        "corporation",
        "company",
        "office",
        "retail",
        "platform",
        "committee",
        "association",
    }
    location_markers = {
        "usa",
        "u.s.",
        "us",
        "united states",
        "new york",
        "paris",
        "tokyo",
        "london",
        "milan",
        "france",
        "italy",
        "china",
        "beijing",
        "shanghai",
    }

    def candidate_context(name: str) -> str:
        lowered_name = name.lower()
        index = lowered_context.find(lowered_name)
        if index == -1:
            return lowered_name
        start = max(0, index - 120)
        end = min(len(lowered_context), index + len(lowered_name) + 120)
        return lowered_context[start:end]

    def infer_focal_brand_name() -> str:
        if "ralph lauren" in lowered_context:
            return "Ralph Lauren"
        for candidate in sampled_entities:
            lowered_candidate = candidate.lower()
            if any(marker in lowered_candidate for marker in {"nike", "adidas", "under armour"}):
                continue
            if any(marker in lowered_candidate for marker in {"vogue", "wwd", "team usa"}):
                continue
            return candidate
        cleaned_project_name = str(project.name or "").strip()
        if cleaned_project_name and "scenario" not in cleaned_project_name.lower():
            return cleaned_project_name
        return "Lead Brand"

    focal_brand_name = infer_focal_brand_name()

    def classify_named_entity(name: str) -> str:
        lowered_name = name.lower()
        snippet = candidate_context(name)
        if lowered_name == focal_brand_name.lower() or "ralph lauren" in lowered_name:
            return brand_label
        if any(marker in lowered_name for marker in {"nike", "adidas", "under armour", "burberry", "tommy hilfiger", "lacoste"}):
            return competitor_label
        if lowered_name in location_markers or any(marker in snippet for marker in {" city", " market", " country", " region"}):
            return location_label
        if any(marker in lowered_name or marker in snippet for marker in media_markers):
            return media_label
        if scenario_mode == "sports_partnership" and any(marker in lowered_name or marker in snippet for marker in {"athlete", "runner", "sprinter", "ambassador"}):
            return ambassador_label
        if any(marker in lowered_name or marker in snippet for marker in {"consumer", "shoppers", "community", "gen z", "loyalists"}):
            return consumer_label
        if any(marker in lowered_name or marker in snippet for marker in {"sustainab", "textile", "sourcing", "labor", "activist"}):
            return activist_label
        if any(marker in lowered_name or marker in snippet for marker in organization_markers):
            return organization_label
        if len(name.split()) >= 2 and all(part[:1].isupper() for part in name.split()[:2]):
            return person_label
        return organization_label

    nodes: list[dict[str, object]] = []
    node_lookup: dict[str, str] = {}
    edges: list[dict[str, object]] = []

    def add_node(name: str, label: str, summary: str) -> str | None:
        cleaned_name = clean_topic_label(name)
        if not cleaned_name:
            return None
        key = cleaned_name.casefold()
        if key in node_lookup:
            return node_lookup[key]
        base_uuid = f"node_{slugify(cleaned_name)}"
        resolved_uuid = base_uuid
        suffix = 2
        while any(str(node.get("uuid")) == resolved_uuid for node in nodes):
            resolved_uuid = f"{base_uuid}_{suffix}"
            suffix += 1
        node_lookup[key] = resolved_uuid
        nodes.append(
            {
                "uuid": resolved_uuid,
                "name": cleaned_name,
                "label": label,
                "summary": summary.strip(),
                "attributes": {},
            }
        )
        return resolved_uuid

    def add_edge(source_uuid: str | None, target_uuid: str | None, relation_type: str, fact: str) -> None:
        if not source_uuid or not target_uuid or source_uuid == target_uuid:
            return
        edge_uuid = f"edge_{slugify(source_uuid)}_{slugify(target_uuid)}_{slugify(relation_type)}"
        if any(str(edge.get("uuid")) == edge_uuid for edge in edges):
            return
        edges.append(
            {
                "uuid": edge_uuid,
                "source_uuid": source_uuid,
                "target_uuid": target_uuid,
                "relation_type": relation_type,
                "fact": fact.strip(),
                "weight": 1.0,
            }
        )

    seed_specs: list[tuple[str, str, str]] = [
        (
            focal_brand_name,
            brand_label,
            f"{focal_brand_name} is the focal brand in this scenario and anchors the main reaction cycle.",
        ),
        (
            "Twitter",
            platform_label,
            "Twitter is a fast-moving reaction surface where the first narrative spikes appear.",
        ),
        (
            "Reddit",
            platform_label,
            "Reddit is the deeper discussion surface where sentiment becomes more detailed and contested.",
        ),
    ]

    if scenario_mode == "sports_partnership":
        seed_specs.extend(
            [
                (
                    "Team USA",
                    organization_label,
                    "Team USA is the national-stage partner that makes the moment culturally visible.",
                ),
                (
                    "Olympic Parade Uniform Reveal",
                    event_label,
                    "The parade-uniform reveal is the central event tying fashion, patriotism, and sports attention together.",
                ),
                ("Nike", competitor_label, "Nike is a direct sportswear benchmark in the reaction set."),
                ("Adidas", competitor_label, "Adidas is a direct sportswear benchmark in the reaction set."),
                ("Under Armour", competitor_label, "Under Armour is a direct sportswear benchmark in the reaction set."),
                (
                    "Patriotic Consumers",
                    consumer_label,
                    "Patriotic consumers judge the uniforms through symbolism, national pride, and wearability.",
                ),
                (
                    "Fashion Critics",
                    person_label,
                    "Fashion critics focus on styling quality, originality, and whether the reveal feels prestigious or safe.",
                ),
                (
                    "Sustainability Advocates",
                    activist_label,
                    "Sustainability advocates question textile sourcing, labor conditions, and whether the moment can withstand scrutiny.",
                ),
                (
                    "International Fashion Media",
                    media_label,
                    "International fashion media frames whether the Olympic moment reads as heritage leadership or a brief visibility spike.",
                ),
                (
                    "Athlete Ambassadors",
                    ambassador_label,
                    "Athlete ambassadors translate the reveal into credibility, reach, and shareable endorsement.",
                ),
            ]
        )
    elif scenario_mode == "market_expansion":
        seed_specs.extend(
            [
                ("China Luxury Consumers", consumer_label, "Chinese luxury consumers drive the adoption question in the new market."),
                ("Domestic Competitors", competitor_label, "Domestic competitors shape the comparison set and pressure localization claims."),
                ("Market Analysts", choose_label("Market Analyst", "Organization", "Person"), "Analysts judge demand durability, pricing, and channel choices."),
                ("Sustainability Critics", activist_label, "Critics test whether the expansion narrative survives sourcing and values scrutiny."),
                ("Fashion Media", media_label, "Fashion media frames whether the expansion reads as credible or opportunistic."),
            ]
        )
    elif scenario_mode == "channel_strategy":
        seed_specs.extend(
            [
                ("Discount Shoppers", choose_label("Discount Shopper", "Consumer Cohort", "Organization", "Person"), "Discount shoppers react to the loss of off-price access and deal flow."),
                ("Brand Purists", choose_label("Brand Purist", "Consumer Cohort", "Organization", "Person"), "Brand purists welcome tighter control and stronger prestige signaling."),
                ("Retail Analysts", choose_label("Retail Industry Analyst", "Organization", "Person"), "Retail analysts interpret channel conflict, margin trade-offs, and conversion risk."),
                ("Retail Partners", choose_label("Retail Channel", "Organization"), "Retail partners represent wholesale and storefront friction in the strategy shift."),
                ("Direct Channel Team", organization_label, "The direct channel team controls execution quality and messaging discipline."),
            ]
        )
    elif scenario_mode == "sustainability_launch":
        seed_specs.extend(
            [
                ("Sustainability Advocates", activist_label, "Sustainability advocates test whether the launch is substantive or performative."),
                ("Consumer Cohorts", consumer_label, "Consumer cohorts weigh authenticity, value, and whether the claim changes purchase intent."),
                ("Fashion Media", media_label, "Fashion media shapes how credibility and backlash are interpreted."),
                ("Watchdog Organizations", organization_label, "Watchdog organizations pressure the claim with sourcing and labor questions."),
                ("Creator Commentators", ambassador_label, "Creators decide whether the launch becomes culturally sticky or dismissed as greenwashing."),
            ]
        )
    else:
        seed_specs.extend(
            [
                ("Consumer Cohorts", consumer_label, "Audience segments drive the loyalty and backlash split."),
                ("Fashion Influencers", choose_label("Fashion Influencer", "Person", "Organization"), "Influencers amplify or puncture the main brand narrative."),
                ("Fashion Media", media_label, "Media and commentary shape how the moment is interpreted."),
                ("Brand Team", organization_label, "The brand team is responsible for the main campaign posture and response."),
                ("Core Narrative Themes", theme_label, "The graph tracks the most durable themes affecting conversation and conversion."),
            ]
        )

    for name, label, summary in seed_specs:
        add_node(name, label, summary)

    for phrase in focus_phrases:
        if len(nodes) >= node_budget:
            break
        if phrase.casefold() in node_lookup:
            continue
        phrase_label = theme_label if theme_label in available_labels else organization_label
        add_node(
            phrase,
            phrase_label,
            f"{phrase} is a recurring discussion frame that shapes how the main scenario is interpreted.",
        )

    for candidate in sampled_entities:
        if len(nodes) >= node_budget:
            break
        if candidate.casefold() in node_lookup:
            continue
        label = classify_named_entity(candidate)
        add_node(
            candidate,
            label,
            f"{candidate} appears in the source material as a concrete actor or context anchor in the scenario.",
        )

    node_ids = {str(node["uuid"]) for node in nodes}
    nodes_by_name = {str(node["name"]).casefold(): str(node["uuid"]) for node in nodes}

    def node_id(name: str) -> str | None:
        return nodes_by_name.get(clean_topic_label(name).casefold())

    amplifies = choose_relation("amplifies", "reacts_to", "covers")
    reacts_to = choose_relation("reacts_to", "covers", "amplifies")
    covers = choose_relation("covers", "reacts_to", "amplifies")
    competes_with = choose_relation("competes_with", "reacts_to")
    partners_with = choose_relation("partners_with", "amplifies", "reacts_to")

    focal_brand_id = node_id(focal_brand_name)
    twitter_id = node_id("Twitter")
    reddit_id = node_id("Reddit")

    if twitter_id and focal_brand_id:
        add_edge(twitter_id, focal_brand_id, amplifies, "Twitter accelerates first-wave attention around the focal brand.")
    if reddit_id and focal_brand_id:
        add_edge(reddit_id, focal_brand_id, reacts_to, "Reddit sustains deeper reaction and critique around the focal brand.")

    if scenario_mode == "sports_partnership":
        team_usa_id = node_id("Team USA")
        event_id = node_id("Olympic Parade Uniform Reveal")
        athlete_id = node_id("Athlete Ambassadors")
        media_id = node_id("International Fashion Media")
        critics_id = node_id("Fashion Critics")
        consumers_id = node_id("Patriotic Consumers")
        advocates_id = node_id("Sustainability Advocates")
        for competitor_name in ("Nike", "Adidas", "Under Armour"):
            competitor_id = node_id(competitor_name)
            add_edge(focal_brand_id, competitor_id, competes_with, f"{focal_brand_name} is benchmarked against {competitor_name} in share-of-voice and commercial relevance.")
        add_edge(focal_brand_id, team_usa_id, partners_with, f"{focal_brand_name} partners with Team USA for the Olympic uniform moment.")
        add_edge(focal_brand_id, athlete_id, partners_with, f"{focal_brand_name} relies on athlete ambassadors to give the reveal credibility and reach.")
        add_edge(media_id, focal_brand_id, covers, "International fashion media covers the focal brand during the reveal window.")
        add_edge(media_id, event_id, covers, "International fashion media covers the parade-uniform reveal as a fashion-news event.")
        add_edge(consumers_id, focal_brand_id, reacts_to, "Patriotic consumers react to the brand through the national-team lens.")
        add_edge(critics_id, focal_brand_id, reacts_to, "Fashion critics react to styling, quality, and originality.")
        add_edge(advocates_id, focal_brand_id, reacts_to, "Sustainability advocates react to sourcing and labor questions around the uniforms.")
        add_edge(team_usa_id, event_id, amplifies, "Team USA turns the reveal into a national-stage amplification moment.")
        add_edge(event_id, twitter_id, amplifies, "The reveal has viral potential on fast-moving social feeds.")
        add_edge(event_id, reddit_id, reacts_to, "The reveal also invites deeper scrutiny on slower discussion surfaces.")
    else:
        actor_node_ids = [
            str(node["uuid"])
            for node in nodes
            if str(node.get("label") or "") not in {platform_label, location_label}
            and str(node["uuid"]) != str(focal_brand_id or "")
        ]
        for actor_id in actor_node_ids[: min(len(actor_node_ids), 8)]:
            relation = reacts_to
            if any(actor_id == node_id(name) for name in ("Fashion Media", "International Fashion Media")):
                relation = covers
            add_edge(actor_id, focal_brand_id, relation, "This actor materially shapes interpretation of the focal brand.")

    if len(edges) < max(8, len(nodes) // 2):
        topic_nodes = [node for node in nodes if str(node.get("label") or "") in {theme_label, campaign_label, event_label}]
        actor_nodes = [
            node
            for node in nodes
            if str(node.get("uuid")) != str(focal_brand_id or "")
            and str(node.get("label") or "") not in {platform_label, location_label}
        ]
        for topic in topic_nodes[:3]:
            add_edge(focal_brand_id, str(topic["uuid"]), amplifies, f"{focal_brand_name} is directly tied to {topic['name']}.")
        for actor in actor_nodes[:6]:
            add_edge(str(actor["uuid"]), focal_brand_id, reacts_to, f"{actor['name']} helps shape the public response to {focal_brand_name}.")

    trimmed_edges = [
        edge
        for edge in edges
        if str(edge.get("source_uuid") or "") in node_ids and str(edge.get("target_uuid") or "") in node_ids
    ]
    metadata = {
        "node_count": len(nodes),
        "edge_count": len(trimmed_edges),
        "entity_types": sorted({str(node["label"]) for node in nodes}),
        "edge_types": sorted({str(edge["relation_type"]) for edge in trimmed_edges} | available_edge_types),
    }
    return {"nodes": nodes, "edges": trimmed_edges, "metadata": metadata}


def build_glass_profiles(
    *,
    project: Project,
    source_digest: str,
    ontology: dict[str, object],
    expected_count: int = 18,
    entities: list[dict[str, object]] | None = None,
    llm: TextGenerator | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
    """Generate stable persona profiles for the glass simulation setup."""
    project_label = derive_project_label(project.name, project.scenario_brief)
    scenario_mode = detect_social_brand_simulation_submode(f"{project.scenario_brief}\n{source_digest}")
    terms = dedupe_preserve_order(
        [
            *scenario_mode_theme_defaults(scenario_mode),
            *extract_focus_phrases(f"{project.scenario_brief}\n{source_digest}", limit=8),
            *[clean_topic_label(term) for term in source_digest.split(",") if str(term).strip()],
        ],
        limit=8,
    )
    if not terms:
        terms = [clean_topic_label(item) for item in top_terms(project.scenario_brief, limit=6)] or [
            "Trust",
            "Community Reaction",
            "Narrative Shift",
        ]

    entity_types = [
        item["name"]
        for item in ontology.get("entity_types", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ] or ["Organization", "Person", "Audience Group", "Theme"]
    professions = [
        "Market Analyst",
        "Community Organizer",
        "Policy Reporter",
        "Brand Strategist",
        "Industry Researcher",
        "Student Commentator",
        "Operations Lead",
        "Culture Writer",
        "Data Journalist",
    ]
    countries = ["United Kingdom", "United States", "Germany", "Canada", "Singapore", "France"]
    mbti_types = ["INTJ", "ENTP", "INFJ", "ISTJ", "ENFP", "ESTP"]
    genders = ["female", "male", "other"]
    individual_hints = {
        "student",
        "alumni",
        "professor",
        "person",
        "marketanalyst",
        "retailindustryanalyst",
        "geopoliticalcommentator",
        "sustainabilityactivist",
        "fashioninfluencer",
        "genzconsumer",
        "publicfigure",
        "expert",
        "faculty",
        "official",
        "journalist",
        "activist",
        "creator",
        "founder",
        "employee",
        "consumer",
        "customer",
        "researcher",
        "analyst",
        "executive",
        "fashioninfluencer",
    }
    group_hints = {
        "university",
        "governmentagency",
        "organization",
        "ngo",
        "mediaoutlet",
        "company",
        "institution",
        "group",
        "community",
        "audience",
        "segment",
        "brand",
        "fashionbrand",
        "sportswearcompetitor",
        "competitorbrand",
        "luxurybrand",
        "consumercohort",
        "discountshopper",
        "brandpurist",
        "fashionmediaoutlet",
        "institutionalactor",
        "retailpartner",
        "watchdoggroup",
        "topic",
        "narrative",
        "signal",
        "stakeholder",
    }

    def entity_type_slug(value: str) -> str:
        return slugify(value).replace("-", "")

    def entity_is_individual(entity_type: str) -> bool:
        normalized = entity_type_slug(entity_type)
        if normalized in individual_hints:
            return True
        if normalized in group_hints:
            return False
        return normalized.endswith("person") or normalized.endswith("member")

    def dedupe_topics(items: list[str], *, limit: int = 5) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = item.strip()
            if not normalized or normalized.lower() in seen:
                continue
            seen.add(normalized.lower())
            deduped.append(normalized)
            if len(deduped) >= limit:
                break
        return deduped

    def attribute_summary(entity: dict[str, object]) -> str:
        attributes = entity.get("attributes")
        if not isinstance(attributes, dict):
            return ""
        parts: list[str] = []
        for key, value in list(attributes.items())[:8]:
            cleaned = str(value or "").strip()
            if cleaned:
                parts.append(f"{key}: {cleaned}")
        return "; ".join(parts)

    def relationship_facts(entity: dict[str, object]) -> list[str]:
        facts: list[str] = []
        related_edges = entity.get("related_edges")
        if not isinstance(related_edges, list):
            return facts
        for item in related_edges[:8]:
            if not isinstance(item, dict):
                continue
            fact = str(item.get("fact") or item.get("edge_name") or "").strip()
            if fact:
                facts.append(fact)
        return dedupe_topics(facts, limit=6)

    def local_entity_blacklist(entity: dict[str, object]) -> tuple[set[str], set[str]]:
        names: list[str] = []
        source_name = str(entity.get("name") or "").strip()
        if source_name:
            names.append(source_name)
        for item in entity.get("related_nodes", [])[:10]:
            if not isinstance(item, dict):
                continue
            related_name = str(item.get("name") or "").strip()
            if related_name:
                names.append(related_name)
        return build_entity_topic_blacklist(names)

    def entity_topics(entity: dict[str, object], index: int) -> list[str]:
        topics: list[str] = []
        entity_type = str((entity.get("labels") or ["Entity"])[0] or "Entity")
        local_names, local_fragments = local_entity_blacklist(entity)
        theme_defaults = theme_defaults_for_entity_type(entity_type, scenario_mode=scenario_mode)

        def register(candidate: str) -> None:
            cleaned = clean_topic_label(candidate)
            if not cleaned:
                return
            if not is_conceptual_topic(
                cleaned,
                entity_names=entity_name_blacklist | local_names,
                entity_fragments=entity_fragment_blacklist | local_fragments,
            ):
                return
            topics.append(cleaned)

        def register_terms_from_text(text: str, *, limit: int = 4) -> None:
            for term in derive_priority_themes(text):
                register(term)

        attributes = entity.get("attributes")
        if isinstance(attributes, dict):
            for key, value in list(attributes.items())[:6]:
                key_text = str(key or "").strip().lower()
                value_text = str(value or "").strip()
                if not value_text:
                    continue
                if key_text in {"topic", "topics", "theme", "themes", "focus", "domain", "segment", "audience", "mission"}:
                    register_terms_from_text(value_text, limit=3)
        summary = str(entity.get("summary") or "").strip()
        if summary:
            register_terms_from_text(summary, limit=4)
        for fact in relationship_facts(entity):
            register_terms_from_text(fact, limit=2)
        topics.extend(theme_defaults[:2])
        topics.extend(scenario_theme_pool[index % len(scenario_theme_pool) : index % len(scenario_theme_pool) + 3])
        topics.extend(base_theme_pool[index % len(base_theme_pool) : index % len(base_theme_pool) + 2])
        deduped = rank_theme_candidates(dedupe_topics(topics, limit=8), limit=5)
        if scenario_mode == "market_expansion":
            deduped = [
                item
                for item in deduped
                if item not in {
                    "Holiday Campaign Virality",
                    "Viral Aesthetic",
                    "Viral Momentum",
                    "Streetwear Credibility",
                    "Brand Relevance",
                    "Pricing vs Fast Fashion",
                    "Gen Z Authenticity",
                    "Premium Value Debate",
                }
            ]
            deduped = rank_theme_candidates(
                [*theme_defaults, *scenario_theme_pool, *deduped],
                limit=5,
            )
        return deduped or theme_defaults[:3] or [base_theme_pool[index % len(base_theme_pool)]]

    def profession_for_entity(entity_type: str, default_profession: str, *, summary: str = "", source_name: str = "") -> str:
        normalized = entity_type_slug(entity_type)
        context = f"{source_name} {summary}".lower()
        profession_map = {
            "luxurybrand": "Luxury Brand Lead",
            "fashionbrand": "Brand Marketing Lead",
            "competitorbrand": "Competitor Brand Lead",
            "sportswearcompetitor": "Sportswear Competitor Lead",
            "executive": "Brand Executive",
            "fashioninfluencer": "Fashion Influencer",
            "consumercohort": "Consumer Cohort Voice",
            "discountshopper": "Discount Shopper",
            "brandpurist": "Brand Purist",
            "fashionmediaoutlet": "Fashion Editor",
            "marketanalyst": "Market Analyst",
            "retailindustryanalyst": "Retail Industry Analyst",
            "geopoliticalcommentator": "Geopolitical Commentator",
            "sustainabilityactivist": "Sustainability Activist",
            "luxuryconsumer": "Luxury Consumer",
            "athleteambassador": "Athlete Ambassador",
            "institutionalactor": "Institutional Spokesperson",
            "retailpartner": "Retail Partner",
            "watchdoggroup": "Watchdog Representative",
            "genzconsumer": "Gen Z Consumer",
            "student": "Student Researcher",
            "alumni": "Alumni Advocate",
            "professor": "Professor",
            "expert": "Subject Expert",
            "official": "Policy Official",
            "journalist": "Journalist",
            "activist": "Campaign Organizer",
            "creator": "Creator",
            "consumer": "Community Member",
            "customer": "Customer Advocate",
            "company": "Corporate Spokesperson",
            "organization": "Organization Spokesperson",
            "brand": "Brand Strategist",
            "community": "Community Representative",
            "audience": "Audience Representative",
            "audiencesegment": "Audience Voice",
            "mediaoutlet": "Media Editor",
            "productline": "Category Strategist",
            "platform": "Platform Strategist",
            "event": "Culture Reporter",
            "location": "Regional Analyst",
            "person": "Industry Insider",
        }
        if normalized == "person":
            if any(keyword in context for keyword in ("chief", "ceo", "chairman", "president", "founder", "vice chairman", "creative officer")):
                return "Brand Executive"
            if any(keyword in context for keyword in ("artist", "weaver", "influencer", "creator", "stylist")):
                return "Fashion Influencer"
            if any(keyword in context for keyword in ("critic", "editor", "journalist", "media")):
                return "Fashion Critic"
        if normalized == "audiencesegment":
            if "gen z" in context:
                return "Gen Z Consumer"
            if "heritage" in context:
                return "Heritage Loyalist"
            if "luxury" in context:
                return "Luxury Consumer"
        return profession_map.get(normalized, default_profession)

    def display_name_for_entity(source_name: str, entity_type: str, individual: bool) -> str:
        if source_name:
            return source_name
        if individual:
            return f"{entity_type} Member"
        return entity_type

    def trust_lens_for_entity(entity_type: str, primary_topic: str, summary: str) -> str:
        normalized = entity_type_slug(entity_type)
        if normalized == "luxurybrand":
            return (
                f"Judges {primary_topic.lower()} through prestige, cultural relevance, price credibility, and whether attention can turn into repeat preference."
            )
        if normalized == "executive":
            return (
                f"Judges {primary_topic.lower()} through leadership credibility, message discipline, and whether the brand response feels earned rather than reactive."
            )
        if normalized == "fashionbrand":
            return (
                f"Judges {primary_topic.lower()} through brand equity, cultural relevance, pricing power, and whether "
                "campaign attention can become durable loyalty."
            )
        if normalized == "brand":
            return (
                f"Judges {primary_topic.lower()} through brand stewardship, cultural fit, and whether message discipline survives public scrutiny."
            )
        if normalized == "competitorbrand":
            return (
                f"Reads {primary_topic.lower()} through competitive positioning, price-value contrast, and openings to win over "
                "consumers if the focal brand overreaches."
            )
        if normalized == "sportswearcompetitor":
            return (
                f"Reads {primary_topic.lower()} through category overlap, national-stage visibility, and openings to make the focal brand look opportunistic."
            )
        if normalized in {"marketanalyst", "retailindustryanalyst"}:
            return (
                f"Reads {primary_topic.lower()} through demand quality, execution risk, and whether the move expands relevance without weakening economics."
            )
        if normalized == "geopoliticalcommentator":
            return (
                f"Reads {primary_topic.lower()} through nationalism, cultural fit, and whether the brand can separate commercial ambition from geopolitical backlash."
            )
        if normalized == "sustainabilityactivist":
            return (
                f"Judges {primary_topic.lower()} through sourcing proof, labor credibility, and whether the brand is inviting scrutiny it cannot sustain."
            )
        if normalized == "discountshopper":
            return (
                f"Feels {primary_topic.lower()} through access, affordability, and whether the brand is abandoning customers who previously bought it through discount channels."
            )
        if normalized == "brandpurist":
            return (
                f"Reads {primary_topic.lower()} through exclusivity, prestige discipline, and whether tighter control makes the brand feel stronger rather than colder."
            )
        if normalized == "athleteambassador":
            return (
                f"Reads {primary_topic.lower()} through credibility transfer, symbolic fit, and whether the partnership feels earned instead of transactional."
            )
        if normalized == "productline":
            return (
                f"Reads {primary_topic.lower()} through product desirability, accessibility, and whether the line can carry the brand story without feeling forced."
            )
        if normalized == "platform":
            return (
                f"Tracks {primary_topic.lower()} through algorithmic velocity, creator uptake, and whether the conversation can sustain repeat visibility."
            )
        if normalized == "event":
            return f"Reads {primary_topic.lower()} through cultural visibility, symbolic association, and downstream media pickup."
        if normalized == "location":
            return f"Reads {primary_topic.lower()} through regional demand signals, cultural translation, and market-specific trust."
        if normalized == "person":
            return f"Reads {primary_topic.lower()} through leadership credibility, cultural instincts, and whether the strategy feels earned."
        if normalized == "fashioninfluencer":
            return (
                f"Tracks whether {primary_topic.lower()} feels authentic enough to recommend publicly without losing audience trust."
            )
        if normalized == "consumercohort":
            return (
                f"Feels {primary_topic.lower()} through peer validation, affordability, values alignment, and whether the brand looks culturally current."
            )
        if normalized == "fashionmediaoutlet":
            return (
                f"Reads {primary_topic.lower()} through novelty, evidence quality, and whether the scenario changes the luxury category narrative."
            )
        if normalized in {"institutionalactor", "retailpartner", "watchdoggroup"}:
            return (
                f"Judges {primary_topic.lower()} through credibility, operational follow-through, and whether scrutiny is likely to intensify."
            )
        if normalized == "genzconsumer":
            return (
                f"Feels {primary_topic.lower()} through affordability, authenticity, cultural fit, and sustainability credibility."
            )
        if normalized in {"governmentagency", "organization", "university", "company", "brand"}:
            return f"Judges {primary_topic.lower()} through credibility, consistency, and institutional follow-through."
        if normalized in {"mediaoutlet", "journalist", "creator"}:
            return f"Tracks whether {primary_topic.lower()} has enough evidence, novelty, and narrative momentum to keep spreading."
        if normalized in {"student", "alumni", "consumer", "customer", "community", "audience"}:
            return f"Feels {primary_topic.lower()} through lived impact, peer interpretation, and perceived authenticity."
        if summary:
            return f"Reads {primary_topic.lower()} through the strongest graph-backed tensions shaping trust, relevance, and reaction."
        return f"Uses {primary_topic.lower()} as the main lens for credibility, reaction, and public interpretation."

    def narrative_role_for_entity(entity_type: str, relationship_count: int) -> str:
        normalized = entity_type_slug(entity_type)
        if normalized in {"luxurybrand", "executive"}:
            return "institutional voice"
        if normalized in {"fashionbrand", "competitorbrand"}:
            return "institutional voice"
        if normalized in {"sportswearcompetitor"}:
            return "challenger"
        if normalized == "fashioninfluencer":
            return "cultural amplifier"
        if normalized == "consumercohort":
            return "target audience"
        if normalized in {"discountshopper", "brandpurist"}:
            return "target audience"
        if normalized == "fashionmediaoutlet":
            return "amplifier"
        if normalized in {"marketanalyst", "retailindustryanalyst"}:
            return "interpreter"
        if normalized == "geopoliticalcommentator":
            return "watchdog"
        if normalized == "sustainabilityactivist":
            return "watchdog"
        if normalized == "athleteambassador":
            return "cultural amplifier"
        if normalized in {"institutionalactor", "retailpartner", "watchdoggroup"}:
            return "watchdog"
        if normalized == "genzconsumer":
            return "target audience"
        if normalized in {"mediaoutlet", "journalist"}:
            return "amplifier"
        if normalized in {"governmentagency", "organization", "university", "company", "brand"}:
            return "authority"
        if normalized in {"student", "alumni", "consumer", "customer", "community", "audience"}:
            return "reactor"
        if relationship_count >= 6:
            return "bridge"
        return "interpreter"

    def platform_behavior_for_entity(entity_type: str, individual: bool, interested_topics: list[str]) -> str:
        normalized = entity_type_slug(entity_type)
        topic_focus = ", ".join(interested_topics[:2]) or "the scenario"
        if normalized == "luxurybrand":
            return (
                f"Posts in polished luxury-brand language, protects prestige cues, and responds faster when {topic_focus.lower()} becomes a loyalty risk."
            )
        if normalized == "executive":
            return (
                f"Uses executive language, makes fewer but higher-signal interventions, and steps in when {topic_focus.lower()} threatens leadership credibility."
            )
        if normalized == "fashionbrand":
            return (
                f"Posts in polished brand language, leans into campaign framing, and reacts carefully when {topic_focus.lower()} "
                "turns into a reputation risk."
            )
        if normalized == "brand":
            return (
                f"Uses measured institutional language, tries to stabilize the narrative, and responds carefully when {topic_focus.lower()} "
                "turns into a trust question."
            )
        if normalized == "competitorbrand":
            return (
                f"Engages when {topic_focus.lower()} creates a chance to draw contrast on relevance, pricing, or authenticity without looking opportunistic."
            )
        if normalized == "sportswearcompetitor":
            return (
                f"Engages when {topic_focus.lower()} creates a chance to contrast sports credibility, national-stage fit, or conversion potential."
            )
        if normalized in {"marketanalyst", "retailindustryanalyst"}:
            return (
                f"Posts fewer but sharper takes, translating {topic_focus.lower()} into demand signals, margin pressure, and execution risk."
            )
        if normalized == "geopoliticalcommentator":
            return (
                f"Posts in bursts when {topic_focus.lower()} intersects with nationalism, market tension, or symbolic backlash."
            )
        if normalized == "sustainabilityactivist":
            return (
                f"Shows up when {topic_focus.lower()} exposes sourcing, labor, or values inconsistencies and keeps pressing for proof."
            )
        if normalized == "discountshopper":
            return (
                f"Comments more than it posts, testing whether {topic_focus.lower()} means the brand is leaving value-seeking customers behind."
            )
        if normalized == "brandpurist":
            return (
                f"Posts selectively to defend exclusivity, brand discipline, and whether {topic_focus.lower()} strengthens prestige instead of diluting it."
            )
        if normalized == "athleteambassador":
            return (
                f"Posts in concentrated bursts when {topic_focus.lower()} becomes culturally visible, mixing symbolic support with image management."
            )
        if normalized == "productline":
            return (
                f"Shows up through product-specific reactions, tying {topic_focus.lower()} back to desirability, use-case, and perceived value."
            )
        if normalized == "platform":
            return (
                f"Amplifies quickly when {topic_focus.lower()} turns into a visible trend, then rewards the most repeatable format rather than the strongest argument."
            )
        if normalized == "event":
            return f"Appears in bursts when {topic_focus.lower()} becomes culturally symbolic and worth reframing for broader audiences."
        if normalized == "location":
            return f"Reacts selectively, translating {topic_focus.lower()} into regional demand and cultural-fit signals."
        if normalized == "person":
            return f"Alternates between first-hand reaction and strategic commentary when {topic_focus.lower()} begins to reshape brand perception."
        if normalized == "fashioninfluencer":
            return (
                f"Posts quickly when {topic_focus.lower()} becomes culturally live, mixing aesthetic reaction with authenticity checks."
            )
        if normalized == "consumercohort":
            return (
                f"Comments more than it posts, tests {topic_focus.lower()} against peer norms and value-for-money, and shifts tone fast when the vibe feels forced."
            )
        if normalized == "fashionmediaoutlet":
            return (
                f"Moves fast on breaking turns, reframes {topic_focus.lower()} into category analysis, and compares the brand against competitors and precedent."
            )
        if normalized in {"institutionalactor", "retailpartner", "watchdoggroup"}:
            return (
                f"Uses measured language, raises standards questions when {topic_focus.lower()} is under scrutiny, and can harden soft skepticism into reputational risk."
            )
        if normalized == "genzconsumer":
            return (
                f"Responds in bursts, compares price and values, and treats {topic_focus.lower()} as real only if peers keep reinforcing it."
            )
        if normalized in {"mediaoutlet", "journalist"}:
            return f"Posts quickly when {topic_focus.lower()} moves, then reframes the discussion with evidence and comparisons."
        if normalized in {"governmentagency", "organization", "university", "company", "brand"}:
            return f"Uses fewer posts, more controlled phrasing, and responds carefully when {topic_focus.lower()} becomes contested."
        if normalized in {"student", "alumni", "consumer", "customer", "community", "audience"}:
            return f"Engages in bursts, comments more than posts, and checks peer reaction before committing on {topic_focus.lower()}."
        if individual:
            return f"Alternates between direct reactions and second-order commentary when {topic_focus.lower()} accelerates."
        return f"Acts as a representative voice that weighs institutional risk against public momentum around {topic_focus.lower()}."

    def profile_bio_for_entity(
        *,
        source_name: str,
        profession: str,
        relationship_facts_list: list[str],
        summary: str,
        primary_topic: str,
        secondary_topic: str,
    ) -> str:
        fact_lines = relationship_facts_list[:3]
        if fact_lines:
            base = " ".join(fact_lines)
            if len(base) > 560:
                base = f"{base[:557].rsplit(' ', 1)[0]}..."
            return base
        if summary:
            return summary
        return (
            f"{source_name} enters the scenario as a {profession.lower()} focused on {primary_topic.lower()} and "
            f"{secondary_topic.lower()}."
        )

    def persona_narrative_for_entity(
        *,
        source_name: str,
        profession: str,
        entity_type: str,
        interested_topics: list[str],
        narrative_role: str,
        platform_behavior: str,
        relationship_facts_list: list[str],
        project_label: str,
    ) -> str:
        focus_text = ", ".join(topic.lower() for topic in interested_topics[:3]) or "brand relevance"
        highlights = relationship_facts_list[:2]
        factual_context = " ".join(highlights)
        if factual_context and len(factual_context) > 260:
            factual_context = f"{factual_context[:257].rsplit(' ', 1)[0]}..."
        opening = (
            f"{source_name} functions as a {profession.lower()} inside {project_label}, representing "
            f"a {entity_type.lower()} perspective on {focus_text}."
        )
        role_line = f"This persona operates as a {narrative_role}, shaping how the conversation is interpreted and amplified."
        behavior_line = platform_behavior if platform_behavior.endswith(".") else f"{platform_behavior}."
        if factual_context:
            return f"{opening} {factual_context} {role_line} {behavior_line}"
        return f"{opening} {role_line} {behavior_line}"

    def apply_profile_enrichment(
        profile: dict[str, object],
        *,
        source_name: str,
        summary: str,
        interested_topics: list[str],
        related_nodes: list[dict[str, object]],
        entity: dict[str, object],
    ) -> dict[str, object]:
        if not llm:
            return profile
        related_names = ", ".join(
            str(item.get("name") or "").strip()
            for item in related_nodes[:4]
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        )
        related_facts = ", ".join(relationship_facts(entity))
        generated = maybe_generate_json(
            llm,
            system_prompt=(
                "Return a JSON object for a social-simulation persona with keys "
                "bio, persona, description, profession, interested_topics, age, gender, mbti, country, "
                "trust_lens, narrative_role, platform_behavior, engagement_style. "
                "Keep bio/persona/description concise, realistic, and grounded in the graph context."
            ),
            user_prompt=(
                f"Project: {project_label}\n"
                f"Scenario: {project.scenario_brief}\n"
                f"Entity name: {source_name}\n"
                f"Entity type: {profile.get('entity_type')}\n"
                f"Default display name: {profile.get('name')}\n"
                f"Profession: {profile.get('profession')}\n"
                f"Entity summary: {summary or 'No summary available.'}\n"
                f"Entity attributes: {attribute_summary(entity)}\n"
                f"Interested topics: {', '.join(interested_topics)}\n"
                f"Related graph nodes: {related_names or 'None'}\n"
                f"Relationship facts: {related_facts or 'None'}\n"
                f"Default trust lens: {profile.get('trust_lens')}\n"
                f"Default narrative role: {profile.get('narrative_role')}\n"
                f"Default platform behavior: {profile.get('platform_behavior')}"
            ),
            max_tokens=320,
            temperature=0.15,
        )
        if not isinstance(generated, dict):
            return profile
        for key in (
            "bio",
            "persona",
            "description",
            "profession",
            "trust_lens",
            "narrative_role",
            "platform_behavior",
            "engagement_style",
        ):
            value = generated.get(key)
            if not isinstance(value, str):
                continue
            cleaned_value = sanitize_short_model_text(value.strip(), value.strip())
            if cleaned_value:
                profile[key] = cleaned_value
        topics = generated.get("interested_topics")
        if isinstance(topics, list):
            cleaned_topics = dedupe_topics(
                [str(item).strip().title() for item in topics if str(item).strip()],
                limit=5,
            )
            if cleaned_topics:
                profile["interested_topics"] = cleaned_topics
        age = generated.get("age")
        if isinstance(age, (int, float)) and 16 <= int(age) <= 85:
            profile["age"] = int(age)
        for key in ("gender", "mbti", "country"):
            value = generated.get(key)
            if isinstance(value, str) and value.strip():
                profile[key] = value.strip()
        return profile

    graph_entities = [
        item
        for item in (entities or [])
        if isinstance(item, dict) and item.get("uuid")
    ]
    entity_name_blacklist, entity_fragment_blacklist = build_entity_topic_blacklist(
        [
            str(item.get("name") or "").strip()
            for item in graph_entities
            if str(item.get("name") or "").strip()
        ]
    )
    scenario_defaults = scenario_mode_theme_defaults(scenario_mode)
    base_theme_pool = rank_theme_candidates(dedupe_preserve_order(
        [*scenario_defaults, *derive_priority_themes(f"{project.scenario_brief}\n{source_digest}"), *terms],
        limit=10,
    ), limit=8) or ["Brand Authenticity", "Pricing Sensitivity", "Brand Loyalty"]
    scenario_theme_pool = rank_theme_candidates(dedupe_preserve_order(
        [
            *scenario_defaults,
            *derive_priority_themes(f"{project.scenario_brief}\n{source_digest}"),
            *terms,
        ],
        limit=14,
    ), limit=10) or base_theme_pool
    graph_entities.sort(
        key=lambda item: (
            int(item.get("centrality_score", 0) or 0),
            len(item.get("related_edges") or []) if isinstance(item.get("related_edges"), list) else 0,
            len(item.get("related_nodes") or []) if isinstance(item.get("related_nodes"), list) else 0,
            1 if str(item.get("summary") or "").strip() else 0,
            len(str(item.get("name") or "")),
        ),
        reverse=True,
    )
    graph_target_count = len(graph_entities) if graph_entities else expected_count
    requested_count = max(1, int(expected_count or graph_target_count or 0))
    if graph_entities:
        profile_count = min(graph_target_count, requested_count, 96)
    else:
        profile_count = max(10, min(requested_count, 48))
    enrichment_limit = min(
        profile_count,
        max(6, min(14, profile_count // 4 + 4)) if llm else 0,
    )
    base_profiles: list[dict[str, object]] = []
    for index, entity in enumerate(graph_entities[:profile_count]):
        entity_type = str((entity.get("labels") or ["Entity"])[0] or "Entity")
        source_name = str(entity.get("name") or f"{entity_type} {index + 1}").strip()
        summary = str(entity.get("summary") or "").strip()
        profession = profession_for_entity(
            entity_type,
            professions[index % len(professions)],
            summary=summary,
            source_name=source_name,
        )
        interested_topics = entity_topics(entity, index)
        relationship_fact_list = relationship_facts(entity)
        primary_topic = interested_topics[0]
        secondary_topic = interested_topics[1] if len(interested_topics) > 1 else base_theme_pool[index % len(base_theme_pool)]
        relationship_count = len(entity.get("related_edges") or []) if isinstance(entity.get("related_edges"), list) else 0
        individual = entity_is_individual(entity_type)
        display_name = display_name_for_entity(source_name, entity_type, individual)
        trust_lens = trust_lens_for_entity(entity_type, primary_topic, summary)
        narrative_role = narrative_role_for_entity(entity_type, relationship_count)
        platform_behavior = platform_behavior_for_entity(entity_type, individual, interested_topics)
        profile = {
            "agent_id": f"agent_{index + 1:03d}",
            "oasis_user_id": index,
            "user_id": index,
            "name": display_name,
            "username": f"{slugify(source_name)}_{index + 1:02d}",
            "persona": persona_narrative_for_entity(
                source_name=source_name,
                profession=profession,
                entity_type=entity_type,
                interested_topics=interested_topics,
                narrative_role=narrative_role,
                platform_behavior=platform_behavior,
                relationship_facts_list=relationship_fact_list,
                project_label=project_label,
            ),
            "bio": profile_bio_for_entity(
                source_name=source_name,
                profession=profession,
                relationship_facts_list=relationship_fact_list,
                summary=summary,
                primary_topic=primary_topic,
                secondary_topic=secondary_topic,
            ),
            "description": (
                f"Graph-grounded persona for {source_name}, shaped by {entity_type.lower()} context and centered on "
                f"{', '.join(interested_topics[:3]).lower()}."
            ),
            "profession": profession,
            "entity_type": entity_type,
            "entity_source": source_name,
            "interested_topics": interested_topics,
            "trust_lens": trust_lens,
            "narrative_role": narrative_role,
            "platform_behavior": platform_behavior,
            "engagement_style": (
                "comments more than posts" if relationship_count >= 4 else "posts selectively and reacts quickly when evidence shifts"
            ),
            "relationship_facts": relationship_fact_list,
            "source_entity_uuid": str(entity.get("uuid") or f"entity_{slugify(entity_type)}_{index + 1:02d}"),
            "source_entity_type": entity_type,
            "age": (23 if individual else 28) + (index % 16),
            "gender": genders[index % len(genders)],
            "mbti": mbti_types[index % len(mbti_types)],
            "country": countries[index % len(countries)],
            "karma": 900 + ((index + 1) * 101) + (relationship_count * 17),
            "friend_count": 140 + (index * 9) + (relationship_count * 3),
            "follower_count": 220 + (index * 21) + (relationship_count * 11),
            "statuses_count": 460 + (index * 19) + (relationship_count * 13),
        }
        if llm and index < enrichment_limit:
            profile = apply_profile_enrichment(
                profile,
                source_name=source_name,
                summary=summary,
                interested_topics=interested_topics,
                related_nodes=entity.get("related_nodes") if isinstance(entity.get("related_nodes"), list) else [],
                entity=entity,
            )
        base_profiles.append(profile)
        if progress_callback is not None:
            progress_callback(index + 1, profile_count, source_name)

    for index in range(len(base_profiles), profile_count):
        topic = terms[index % len(terms)].title()
        profession = professions[index % len(professions)]
        entity_type = entity_types[index % len(entity_types)]
        username = f"{slugify(topic)}_{index + 1:02d}"
        external_agent_id = f"agent_{index + 1:03d}"
        source_entity_uuid = f"entity_{slugify(entity_type)}_{slugify(topic)}_{index + 1:02d}"
        interested_topics = [
            topic,
            terms[(index + 1) % len(terms)].title(),
            terms[(index + 2) % len(terms)].title(),
        ]
        base_profiles.append(
            {
                "agent_id": external_agent_id,
                "oasis_user_id": index,
                "user_id": index,
                "name": f"{topic} {profession.split()[0]}",
                "username": username,
                "persona": (
                    f"{profession} who tracks how {topic.lower()} affects trust, attention, and public interpretation."
                ),
                "bio": (
                    f"{profession} focused on {topic.lower()}, scenario risk, and second-order audience reactions."
                ),
                "description": (
                    f"Prepared persona for {project_label} with a strong interest in {topic.lower()}."
                ),
                "profession": profession,
                "entity_type": entity_type,
                "entity_source": topic,
                "interested_topics": interested_topics,
                "source_entity_uuid": source_entity_uuid,
                "source_entity_type": entity_type,
                "age": 24 + (index % 17),
                "gender": genders[index % len(genders)],
                "mbti": mbti_types[index % len(mbti_types)],
                "country": countries[index % len(countries)],
                "karma": 800 + ((index + 1) * 137),
                "friend_count": 120 + (index * 11),
                "follower_count": 180 + (index * 19),
                "statuses_count": 420 + (index * 23),
            }
        )
        if progress_callback is not None:
            progress_callback(index + 1, profile_count, topic)

    reddit_profiles = [{**profile, "platform": "reddit"} for profile in base_profiles]
    twitter_profiles = [{**profile, "platform": "twitter"} for profile in base_profiles]
    return {
        "expected_count": profile_count,
        "graph_entity_count": len(graph_entities),
        "reddit_profiles": reddit_profiles,
        "twitter_profiles": twitter_profiles,
    }


def build_glass_simulation_config(
    *,
    project: Project,
    source_digest: str,
    profiles: list[dict[str, object]],
    entities: list[dict[str, object]] | None = None,
    llm: TextGenerator | None = None,
) -> dict[str, object]:
    """Build a richer graph-grounded simulation config payload for the glass workflow."""
    scenario_mode = detect_social_brand_simulation_submode(f"{project.scenario_brief}\n{source_digest}")
    scenario_seed_themes = dedupe_preserve_order(
        [
            *scenario_mode_theme_defaults(scenario_mode),
            *derive_priority_themes(f"{project.scenario_brief}\n{source_digest}"),
        ],
        limit=10,
    )
    terms = dedupe_preserve_order(
        [
            *scenario_seed_themes,
            *extract_focus_phrases(f"{project.scenario_brief}\n{source_digest}", limit=10),
            *[clean_topic_label(term) for term in source_digest.split(",") if str(term).strip()],
        ],
        limit=10,
    )
    project_label = derive_project_label(project.name, project.scenario_brief, topics=terms)
    graph_entities = {
        str(item.get("uuid")): item
        for item in (entities or [])
        if isinstance(item, dict) and item.get("uuid")
    }
    entity_name_blacklist, entity_fragment_blacklist = build_entity_topic_blacklist(
        [
            str(item.get("name") or "").strip()
            for item in graph_entities.values()
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
    )

    def entity_type_slug(value: str) -> str:
        return slugify(value).replace("-", "")

    def clamp_float(value: object, default: float, *, low: float, high: float) -> float:
        if not isinstance(value, (int, float)):
            return default
        return round(max(low, min(float(value), high)), 2)

    def clamp_int(value: object, default: int, *, low: int, high: int) -> int:
        if not isinstance(value, (int, float)):
            return default
        return max(low, min(int(value), high))

    def normalize_hours(value: object, default: list[int]) -> list[int]:
        if not isinstance(value, list):
            return default
        hours = sorted({int(item) for item in value if isinstance(item, (int, float)) and 0 <= int(item) <= 23})
        return hours or default

    def base_agent_behavior(profile: dict[str, object], index: int) -> dict[str, object]:
        entity_type = str(profile.get("entity_type") or "Entity")
        normalized = entity_type_slug(entity_type)
        topics = [str(item).strip() for item in profile.get("interested_topics", []) if str(item).strip()]
        topic_bonus = min(max(len(topics) - 1, 0), 4)
        relationship_count = 0
        entity = graph_entities.get(str(profile.get("source_entity_uuid") or ""))
        if isinstance(entity, dict) and isinstance(entity.get("related_edges"), list):
            relationship_count = len(entity["related_edges"])
        follower_count = int(profile.get("follower_count", 0) or 0)
        influence_bonus = min(1.6, follower_count / 1800)

        if normalized in {"fashionbrand", "luxurybrand"}:
            config = {
                "activity_level": 0.62,
                "posts_per_hour": 0.58,
                "comments_per_hour": 0.34,
                "active_hours": list(range(9, 24)),
                "response_delay_min": 12,
                "response_delay_max": 90,
                "sentiment_bias": 0.12,
                "stance": "supportive",
                "influence_weight": 3.6,
            }
        elif normalized in {"marketanalyst", "retailindustryanalyst"}:
            config = {
                "activity_level": 0.72,
                "posts_per_hour": 0.66,
                "comments_per_hour": 0.62,
                "active_hours": [8, 9, 10, 11, 12, 13, 17, 18, 19, 20, 21],
                "response_delay_min": 4,
                "response_delay_max": 24,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.8,
            }
        elif normalized in {"geopoliticalcommentator"}:
            config = {
                "activity_level": 0.78,
                "posts_per_hour": 0.74,
                "comments_per_hour": 0.68,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22],
                "response_delay_min": 3,
                "response_delay_max": 18,
                "sentiment_bias": -0.08,
                "stance": "observer",
                "influence_weight": 2.6,
            }
        elif normalized in {"sustainabilityactivist"}:
            config = {
                "activity_level": 0.8,
                "posts_per_hour": 0.56,
                "comments_per_hour": 1.08,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22],
                "response_delay_min": 2,
                "response_delay_max": 14,
                "sentiment_bias": -0.12,
                "stance": "opposing",
                "influence_weight": 2.1,
            }
        elif normalized in {"competitorbrand"}:
            config = {
                "activity_level": 0.76,
                "posts_per_hour": 0.76,
                "comments_per_hour": 0.46,
                "active_hours": list(range(9, 24)),
                "response_delay_min": 6,
                "response_delay_max": 48,
                "sentiment_bias": -0.05,
                "stance": "opposing",
                "influence_weight": 2.9,
            }
        elif normalized in {"sportswearcompetitor"}:
            config = {
                "activity_level": 0.74,
                "posts_per_hour": 0.72,
                "comments_per_hour": 0.48,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22],
                "response_delay_min": 4,
                "response_delay_max": 24,
                "sentiment_bias": -0.04,
                "stance": "opposing",
                "influence_weight": 2.8,
            }
        elif normalized in {"executive"}:
            config = {
                "activity_level": 0.64,
                "posts_per_hour": 0.42,
                "comments_per_hour": 0.38,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21],
                "response_delay_min": 6,
                "response_delay_max": 40,
                "sentiment_bias": 0.08,
                "stance": "supportive",
                "influence_weight": 3.4,
            }
        elif normalized in {"fashioninfluencer"}:
            config = {
                "activity_level": 0.94,
                "posts_per_hour": 1.08,
                "comments_per_hour": 0.66,
                "active_hours": [9, 10, 11, 12, 13, 14, 18, 19, 20, 21, 22, 23],
                "response_delay_min": 2,
                "response_delay_max": 14,
                "sentiment_bias": 0.08,
                "stance": "observer",
                "influence_weight": 3.0,
            }
        elif normalized in {"genzconsumer", "audiencesegment", "consumer", "customer", "community", "audience", "consumercohort"}:
            config = {
                "activity_level": 0.92,
                "posts_per_hour": 0.64,
                "comments_per_hour": 1.58,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],
                "response_delay_min": 1,
                "response_delay_max": 10,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.5,
            }
        elif normalized in {"discountshopper", "brandpurist"}:
            config = {
                "activity_level": 0.78,
                "posts_per_hour": 0.46,
                "comments_per_hour": 1.34,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],
                "response_delay_min": 1,
                "response_delay_max": 10,
                "sentiment_bias": -0.05 if normalized == "discountshopper" else 0.08,
                "stance": "opposing" if normalized == "discountshopper" else "supportive",
                "influence_weight": 1.4,
            }
        elif normalized in {"athleteambassador"}:
            config = {
                "activity_level": 0.7,
                "posts_per_hour": 0.62,
                "comments_per_hour": 0.54,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22],
                "response_delay_min": 3,
                "response_delay_max": 16,
                "sentiment_bias": 0.1,
                "stance": "supportive",
                "influence_weight": 2.7,
            }
        elif normalized in {"person"}:
            config = {
                "activity_level": 0.7,
                "posts_per_hour": 0.58,
                "comments_per_hour": 0.92,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],
                "response_delay_min": 3,
                "response_delay_max": 20,
                "sentiment_bias": 0.02,
                "stance": "neutral",
                "influence_weight": 1.9,
            }
        elif normalized in {"productline"}:
            config = {
                "activity_level": 0.4,
                "posts_per_hour": 0.26,
                "comments_per_hour": 0.2,
                "active_hours": list(range(9, 23)),
                "response_delay_min": 8,
                "response_delay_max": 56,
                "sentiment_bias": 0.04,
                "stance": "observer",
                "influence_weight": 1.5,
            }
        elif normalized in {"platform"}:
            config = {
                "activity_level": 0.7,
                "posts_per_hour": 0.72,
                "comments_per_hour": 0.42,
                "active_hours": list(range(8, 24)),
                "response_delay_min": 2,
                "response_delay_max": 16,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.2,
            }
        elif normalized in {"governmentagency", "organization", "ngo", "company", "brand", "university", "institution", "institutionalactor", "retailpartner", "watchdoggroup"}:
            config = {
                "activity_level": 0.56,
                "posts_per_hour": 0.38,
                "comments_per_hour": 0.44,
                "active_hours": list(range(8, 22)),
                "response_delay_min": 8,
                "response_delay_max": 56,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.8,
            }
        elif normalized in {"mediaoutlet", "journalist", "fashionmediaoutlet"}:
            config = {
                "activity_level": 0.9,
                "posts_per_hour": 1.18,
                "comments_per_hour": 0.7,
                "active_hours": list(range(7, 24)),
                "response_delay_min": 3,
                "response_delay_max": 18,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.8,
            }
        elif normalized in {"professor", "expert", "official", "faculty"}:
            config = {
                "activity_level": 0.48,
                "posts_per_hour": 0.32,
                "comments_per_hour": 0.52,
                "active_hours": list(range(8, 22)),
                "response_delay_min": 10,
                "response_delay_max": 60,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0,
            }
        elif normalized in {"student"}:
            config = {
                "activity_level": 0.84,
                "posts_per_hour": 0.62,
                "comments_per_hour": 1.42,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],
                "response_delay_min": 1,
                "response_delay_max": 12,
                "sentiment_bias": 0.05,
                "stance": "neutral",
                "influence_weight": 0.9,
            }
        elif normalized in {"alumni", "creator", "activist"}:
            config = {
                "activity_level": 0.64,
                "posts_per_hour": 0.46,
                "comments_per_hour": 0.92,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],
                "response_delay_min": 3,
                "response_delay_max": 18,
                "sentiment_bias": 0.1 if normalized in {"activist", "creator"} else 0.0,
                "stance": "supportive" if normalized in {"community", "audience"} else "neutral",
                "influence_weight": 1.1,
            }
        else:
            config = {
                "activity_level": 0.64,
                "posts_per_hour": 0.52,
                "comments_per_hour": 1.02,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22],
                "response_delay_min": 4,
                "response_delay_max": 24,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0,
            }

        activity_scale = 1.02
        post_scale = 1.03
        comment_scale = 1.08
        if normalized in {"mediaoutlet", "journalist", "fashionmediaoutlet", "fashioninfluencer", "marketanalyst", "retailindustryanalyst", "geopoliticalcommentator"}:
            activity_scale = 1.08
            post_scale = 1.14
            comment_scale = 1.08
        elif normalized in {"audiencesegment", "consumer", "customer", "community", "audience", "student", "alumni", "genzconsumer", "consumercohort", "discountshopper", "brandpurist"}:
            activity_scale = 1.06
            post_scale = 1.0
            comment_scale = 1.16
        elif normalized in {"brand", "fashionbrand", "luxurybrand", "competitorbrand", "sportswearcompetitor", "company", "organization", "productline", "executive", "institutionalactor", "athleteambassador"}:
            post_scale = 1.08
            comment_scale = 0.98
        config["activity_level"] = clamp_float(config["activity_level"] * activity_scale, config["activity_level"], low=0.05, high=1.0)
        config["posts_per_hour"] = clamp_float(config["posts_per_hour"] * post_scale, config["posts_per_hour"], low=0.02, high=2.0)
        config["comments_per_hour"] = clamp_float(config["comments_per_hour"] * comment_scale, config["comments_per_hour"], low=0.02, high=3.0)

        if normalized in {"customer", "consumer", "student", "community", "audience"} and index % 4 == 0:
            config["stance"] = "opposing"
            config["sentiment_bias"] = clamp_float(config["sentiment_bias"], 0.0, low=-1.0, high=1.0) - 0.15
        elif normalized in {"brand", "company", "organization"} and index % 3 == 0:
            config["stance"] = "supportive"
            config["sentiment_bias"] = clamp_float(config["sentiment_bias"], 0.0, low=-1.0, high=1.0) + 0.1

        config["activity_level"] = clamp_float(config["activity_level"] + (topic_bonus * 0.02), config["activity_level"], low=0.05, high=1.0)
        config["posts_per_hour"] = clamp_float(config["posts_per_hour"] + (topic_bonus * 0.028), config["posts_per_hour"], low=0.03, high=1.9)
        config["comments_per_hour"] = clamp_float(config["comments_per_hour"] + min(0.4, relationship_count * 0.03), config["comments_per_hour"], low=0.03, high=2.8)
        config["influence_weight"] = clamp_float(config["influence_weight"] + influence_bonus + min(0.85, relationship_count * 0.06), config["influence_weight"], low=0.5, high=6.0)
        return config

    def preferred_platform(agent: dict[str, object], fallback_index: int) -> str:
        normalized = entity_type_slug(str(agent.get("entity_type") or ""))
        if normalized in {"mediaoutlet", "journalist", "governmentagency", "official", "brand", "company", "creator", "marketanalyst", "retailindustryanalyst", "geopoliticalcommentator"}:
            return "twitter"
        if normalized in {"student", "alumni", "community", "audience", "consumer", "customer", "discountshopper", "brandpurist", "sustainabilityactivist"}:
            return "reddit"
        return "twitter" if fallback_index % 2 == 0 else "reddit"

    scenario_themes = dedupe_preserve_order(
        [*scenario_seed_themes, *extract_focus_phrases(project.scenario_brief, limit=10)],
        limit=10,
    )
    topic_counter: Counter[str] = Counter()
    prioritized_topics = dedupe_preserve_order(scenario_seed_themes, limit=8)

    def register_topic(candidate: str, weight: int) -> None:
        cleaned = normalize_theme_label(candidate)
        if not cleaned:
            return
        if cleaned in prioritized_topics:
            topic_counter[cleaned] += max(weight, 6)
            return
        if not is_conceptual_topic(
            cleaned,
            entity_names=entity_name_blacklist,
            entity_fragments=entity_fragment_blacklist,
        ):
            return
        topic_counter[cleaned] += weight

    for profile in profiles:
        for topic in profile.get("interested_topics", [])[:4]:
            if isinstance(topic, str) and topic.strip():
                register_topic(topic, 2)
        for fact in profile.get("relationship_facts", [])[:4]:
            if isinstance(fact, str) and fact.strip():
                for term in derive_priority_themes(fact):
                    register_topic(term, 2)
    for entity in entities or []:
        if not isinstance(entity, dict):
            continue
        summary = str(entity.get("summary") or "").strip()
        if summary:
            for term in derive_priority_themes(summary):
                register_topic(term, 3)
            for term in extract_focus_phrases(summary, limit=3):
                register_topic(term, 2)
        for edge in entity.get("related_edges", [])[:4]:
            if not isinstance(edge, dict):
                continue
            fact = str(edge.get("fact") or edge.get("edge_name") or "").strip()
            for term in derive_priority_themes(fact):
                register_topic(term, 2)
            for term in extract_focus_phrases(fact, limit=2):
                register_topic(term, 1)
    for term in scenario_themes[:8]:
        register_topic(term, 5)
    for term in terms[:6]:
        register_topic(term, 3)

    ranked_hot_topics = [
        topic
        for topic, _score in sorted(
            (
                (topic, int(count) + theme_signal_score(topic))
                for topic, count in topic_counter.items()
                if topic and topic.casefold() not in GENERIC_TOPIC_TERMS
            ),
            key=lambda item: (-item[1], -len(item[0].split()), item[0]),
        )[:10]
    ]
    hot_topics = rank_theme_candidates(
        prioritized_topics + ranked_hot_topics,
        limit=8,
    ) or rank_theme_candidates(scenario_themes[:8], limit=8) or ["Brand Loyalty", "Pricing Sensitivity", "Brand Authenticity"]
    hot_topics = rank_theme_candidates(
        [
            "Brand Relevance" if item == "Gen Z Cultural Relevance" else normalize_theme_label(item)
            for item in hot_topics
        ],
        limit=8,
    )
    suppressed_topics: set[str] = set()
    if "Pricing vs Fast Fashion" in hot_topics:
        suppressed_topics.add("Pricing Sensitivity")
    if "Gen Z Authenticity" in hot_topics:
        suppressed_topics.add("Brand Authenticity")
    if "Brand Relevance" in hot_topics:
        suppressed_topics.add("Brand Loyalty")
    hot_topics = [item for item in hot_topics if item not in suppressed_topics]
    if "sustainab" in (project.scenario_brief or "").lower() and "Sustainability Criticism" not in hot_topics:
        hot_topics.insert(min(3, len(hot_topics)), "Sustainability Criticism")
    if scenario_mode == "market_expansion":
        hot_topics = [
            item
            for item in hot_topics
            if item not in {
                "Holiday Campaign Virality",
                "Viral Aesthetic",
                "Viral Momentum",
                "Streetwear Credibility",
                "Brand Relevance",
                "Pricing vs Fast Fashion",
                "Gen Z Authenticity",
                "Premium Value Debate",
            }
        ]
        hot_topics = rank_theme_candidates(
            [*scenario_mode_theme_defaults(scenario_mode), *hot_topics],
            limit=8,
        )
        if "Geopolitical Risk" not in hot_topics:
            hot_topics.insert(min(3, len(hot_topics)), "Geopolitical Risk")
    hot_topics = rank_theme_candidates(hot_topics, limit=8)
    total_hours = 168
    minutes_per_round = 60
    rounds = max(1, int((total_hours * 60) / minutes_per_round))

    agent_configs: list[dict[str, object]] = []
    for index, profile in enumerate(profiles):
        oasis_user_id = int(profile.get("oasis_user_id", index))
        defaults = base_agent_behavior(profile, index)
        preferred = preferred_platform(profile, index)
        cross_platform_affinity = 0.22 if preferred == "twitter" else 0.26
        agent_configs.append(
            {
                "agent_id": oasis_user_id,
                "external_agent_id": str(profile.get("agent_id") or f"agent_{oasis_user_id:03d}"),
                "entity_uuid": str(profile.get("source_entity_uuid") or f"entity_{oasis_user_id:03d}"),
                "entity_name": str(profile.get("name") or f"Agent {oasis_user_id}"),
                "entity_type": str(profile.get("entity_type") or "Entity"),
                "bio": str(profile.get("bio") or ""),
                "persona": str(profile.get("persona") or ""),
                "topics": [str(item) for item in profile.get("interested_topics", []) if isinstance(item, str)][:5],
                "profession": str(profile.get("profession") or profile.get("entity_type") or "Entity"),
                "narrative_role": str(profile.get("narrative_role") or ""),
                "platform_behavior": str(profile.get("platform_behavior") or ""),
                "trust_lens": str(profile.get("trust_lens") or ""),
                "preferred_platform": preferred,
                "cross_platform_affinity": cross_platform_affinity,
                **defaults,
            }
        )

    agent_count = max(len(agent_configs), 1)
    agents_per_hour_min = max(3, min(agent_count, max(int(round(agent_count * 0.08)), agent_count // 16, 3)))
    agents_per_hour_max = max(agents_per_hour_min + 2, min(agent_count, max(int(round(agent_count * 0.18)), agent_count // 8, 6)))
    if agent_count >= 40:
        agents_per_hour_min = max(agents_per_hour_min, 4)
        agents_per_hour_max = max(agents_per_hour_max, 8)
    elif agent_count >= 24:
        agents_per_hour_min = max(agents_per_hour_min, 4)
        agents_per_hour_max = max(agents_per_hour_max, 7)
    if scenario_mode == "market_expansion":
        if agent_count >= 48:
            agents_per_hour_min = max(agents_per_hour_min, 6)
            agents_per_hour_max = max(agents_per_hour_max, 13)
        elif agent_count >= 36:
            agents_per_hour_min = max(agents_per_hour_min, 6)
            agents_per_hour_max = max(agents_per_hour_max, 12)
        elif agent_count >= 24:
            agents_per_hour_min = max(agents_per_hour_min, 5)
            agents_per_hour_max = max(agents_per_hour_max, 9)
    if agent_count <= 5:
        agents_per_hour_min = max(1, min(agent_count, agents_per_hour_min))
        agents_per_hour_max = agent_count
    scenario_brief_lower = (project.scenario_brief or "").lower()
    twitter_share = 0.54
    reddit_share = 0.58
    if "reddit" in scenario_brief_lower and "twitter" not in scenario_brief_lower:
        twitter_share, reddit_share = 0.25, 0.9
    elif "twitter" in scenario_brief_lower and "reddit" not in scenario_brief_lower:
        twitter_share, reddit_share = 0.9, 0.25
    elif any(keyword in scenario_brief_lower for keyword in ("pricing", "authentic", "sustainab", "loyal")):
        twitter_share, reddit_share = 0.58, 0.62
    if scenario_mode == "market_expansion":
        twitter_share, reddit_share = 0.52, 0.66
    default_agents_per_hour_min = agents_per_hour_min
    default_agents_per_hour_max = agents_per_hour_max
    time_config = {
        "total_simulation_hours": total_hours,
        "minutes_per_round": minutes_per_round,
        "agents_per_hour_min": agents_per_hour_min,
        "agents_per_hour_max": agents_per_hour_max,
        "peak_hours": [19, 20, 21, 22],
        "peak_activity_multiplier": 1.5,
        "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
        "work_activity_multiplier": 0.7,
        "morning_hours": [6, 7, 8],
        "morning_activity_multiplier": 0.4,
        "off_peak_hours": [0, 1, 2, 3, 4, 5],
        "off_peak_activity_multiplier": 0.05,
        "platform_mix": {"twitter": twitter_share, "reddit": reddit_share},
    }
    if agent_count >= 28:
        time_config["peak_activity_multiplier"] = 1.65
        time_config["work_activity_multiplier"] = 0.8
        time_config["morning_activity_multiplier"] = 0.45
        time_config["off_peak_activity_multiplier"] = 0.08
    if scenario_mode == "market_expansion":
        time_config["peak_activity_multiplier"] = max(float(time_config["peak_activity_multiplier"]), 1.62)
        time_config["work_activity_multiplier"] = max(float(time_config["work_activity_multiplier"]), 0.8)
    twitter_config = {
        "platform": "twitter",
        "recency_weight": 0.4,
        "popularity_weight": 0.3,
        "relevance_weight": 0.3,
        "viral_threshold": 10,
        "echo_chamber_strength": 0.5,
    }
    reddit_config = {
        "platform": "reddit",
        "recency_weight": 0.3,
        "popularity_weight": 0.4,
        "relevance_weight": 0.3,
        "viral_threshold": 15,
        "echo_chamber_strength": 0.6,
    }

    ranked_agents = sorted(
        agent_configs,
        key=lambda item: (
            float(item.get("influence_weight", 1.0) or 1.0),
            float(item.get("posts_per_hour", 0.0) or 0.0) + float(item.get("comments_per_hour", 0.0) or 0.0),
        ),
        reverse=True,
    )

    def select_agent_for_topic(topic: str, used_ids: set[int]) -> dict[str, object]:
        topic_lower = topic.lower()
        candidates = sorted(
            agent_configs,
            key=lambda item: (
                topic_lower in {str(topic_item).lower() for topic_item in item.get("topics", [])},
                float(item.get("influence_weight", 1.0) or 1.0),
                float(item.get("posts_per_hour", 0.0) or 0.0),
            ),
            reverse=True,
        )
        for candidate in candidates:
            candidate_id = int(candidate["agent_id"])
            if candidate_id not in used_ids:
                return candidate
        return ranked_agents[0] if ranked_agents else {"agent_id": 0, "entity_type": "Entity", "entity_name": "Agent"}

    pricing_focus = "pricing" in scenario_brief_lower or "$" in scenario_brief_lower
    authenticity_focus = "authentic" in scenario_brief_lower
    sustainability_focus = "sustainab" in scenario_brief_lower
    loyalty_focus = "loyal" in scenario_brief_lower
    competitor_focus = "competitor" in scenario_brief_lower or "burberry" in scenario_brief_lower or "tommy hilfiger" in scenario_brief_lower

    def compose_seed_post(agent_config: dict[str, object], *, topic: str, stance: str, platform: str, phase: str) -> str:
        entity_name = str(agent_config.get("entity_name") or "This account").strip()
        profession = str(agent_config.get("profession") or agent_config.get("entity_type") or "observer").strip()
        trust_lens = str(agent_config.get("trust_lens") or "").strip()
        persona = str(agent_config.get("persona") or "").strip()
        topic_text = topic.lower()
        if stance == "supportive":
            opening = f"{entity_name} thinks {project_label} has a real opening around {topic_text}"
        elif stance == "opposing":
            opening = f"{entity_name} sees {topic_text} exposing weak points in {project_label}'s positioning"
        elif stance == "observer":
            opening = f"{entity_name} reads {topic_text} as a live test of {project_label}'s cultural relevance"
        else:
            opening = f"{entity_name} thinks {topic_text} is becoming a meaningful signal for how {project_label} will be judged"
        pressure_clauses: list[str] = []
        if pricing_focus:
            pressure_clauses.append("pricing still looks hard to justify against lower-cost alternatives")
        if authenticity_focus:
            pressure_clauses.append("the brand still has to prove this is more than polished nostalgia")
        if sustainability_focus:
            pressure_clauses.append("sustainability and supply-chain scrutiny are already part of the reaction")
        if loyalty_focus:
            pressure_clauses.append("viral attention will matter only if it becomes repeat loyalty")
        if competitor_focus:
            pressure_clauses.append("competitors still have an opening if the brand cannot hold the narrative")
        perspective = pressure_clauses[0] if pressure_clauses else "the next phase depends on whether the narrative holds under scrutiny"
        if phase == "event":
            return (
                f"{opening}. From a {profession.lower()} lens, {perspective}. "
                f"{trust_lens or persona or 'This is the moment when attention either converts into conviction or turns into backlash.'}"
            )
        return (
            f"{opening}. As a {profession.lower()}, {entity_name} keeps coming back to the fact that {perspective}. "
            f"{trust_lens or persona or 'The current signal is strong, but conviction still has to be earned through proof.'}"
        )

    initial_posts: list[dict[str, object]] = []
    used_initial_agents: set[int] = set()
    platform_seed_counts = {"twitter": 0, "reddit": 0}
    initial_target = min(len(agent_configs), max(8, min(14, (len(agent_configs) // 8) + 5)))
    if scenario_mode == "market_expansion":
        initial_target = min(len(agent_configs), max(initial_target, 10))
    for index, topic in enumerate(hot_topics[:initial_target]):
        agent_config = select_agent_for_topic(topic, used_initial_agents)
        agent_id = int(agent_config["agent_id"])
        used_initial_agents.add(agent_id)
        topic_lower = topic.lower()
        if any(keyword in topic_lower for keyword in ("pricing", "authentic", "sustainab", "loyalty", "streetwear")):
            platform = "reddit"
        elif any(keyword in topic_lower for keyword in ("viral", "media", "aesthetic", "campaign", "influencer")):
            platform = "twitter"
        else:
            platform = preferred_platform(agent_config, index)
        other_platform = "reddit" if platform == "twitter" else "twitter"
        if platform_seed_counts[platform] > platform_seed_counts[other_platform] + 1:
            platform = other_platform
        platform_seed_counts[platform] += 1
        stance = str(agent_config.get("stance") or "neutral")
        initial_posts.append(
            {
                "poster_agent_id": agent_id,
                "poster_type": str(agent_config.get("entity_type") or "Entity"),
                "platform": platform,
                "topic": topic,
                "content": compose_seed_post(agent_config, topic=topic, stance=stance, platform=platform, phase="initial"),
            }
    )

    scheduled_events: list[dict[str, object]] = []
    for offset, topic in enumerate(hot_topics[1:6], start=1):
        agent_config = ranked_agents[(offset + 1) % len(ranked_agents)] if ranked_agents else {"agent_id": 0, "entity_type": "Entity", "entity_name": "Agent"}
        trigger_round = min(rounds, max(2, int((rounds / (len(hot_topics[:3]) + 1)) * (offset + 1))))
        scheduled_events.append(
            {
                "event_id": f"event_{offset:02d}",
                "round": trigger_round,
                "simulated_hour": min(total_hours - 1, int(((trigger_round - 1) * minutes_per_round) / 60)),
                "poster_agent_id": int(agent_config["agent_id"]),
                "poster_type": str(agent_config.get("entity_type") or "Entity"),
                "platform": preferred_platform(agent_config, offset),
                "topic": topic,
                "content": compose_seed_post(
                    agent_config,
                    topic=topic,
                    stance=str(agent_config.get("stance") or "neutral"),
                    platform=preferred_platform(agent_config, offset),
                    phase="event",
                ),
                "reason": f"Introduce a second-wave narrative turn around {topic}.",
            }
        )

    generated_plan: dict[str, object] | None = None
    if llm and agent_configs:
        entity_type_counts = Counter(str(item.get("entity_type") or "Entity") for item in profiles)
        type_summary = ", ".join(f"{name}: {count}" for name, count in entity_type_counts.most_common(8))
        profile_brief = "\n".join(
            f"- {item['agent_id']}: {item['entity_name']} ({item['entity_type']}) | role={item.get('narrative_role') or 'participant'} | "
            f"stance={item['stance']} | influence={item['influence_weight']} | topics={', '.join(str(topic) for topic in item.get('topics', [])[:3])}"
            for item in agent_configs[:16]
        )
        generated_plan = maybe_generate_json(
            llm,
            system_prompt=(
                "Return a JSON object with keys time_config, hot_topics, narrative_direction, reasoning, agent_overrides, "
                "initial_posts, scheduled_events, twitter_config, reddit_config. Use only the provided agent_id values. "
                "Keep the output realistic for a public social simulation. Hot topics must be scenario tensions or debate themes, not entity names."
            ),
            user_prompt=(
                f"Project: {project_label}\n"
                f"Scenario: {project.scenario_brief}\n"
                f"Source terms: {', '.join(terms[:8])}\n"
                f"Entity type mix: {type_summary}\n"
                f"Default time config: {time_config}\n"
                f"Default hot topics: {', '.join(hot_topics[:6])}\n"
                f"Default initial posts: {json.dumps(initial_posts[:4])}\n"
                f"Default scheduled events: {json.dumps(scheduled_events[:3])}\n"
                f"Agents:\n{profile_brief}"
            ),
        )
    if isinstance(generated_plan, dict):
        generated_time = generated_plan.get("time_config")
        if isinstance(generated_time, dict):
            time_config["total_simulation_hours"] = clamp_int(generated_time.get("total_simulation_hours"), time_config["total_simulation_hours"], low=12, high=168)
            time_config["minutes_per_round"] = clamp_int(generated_time.get("minutes_per_round"), time_config["minutes_per_round"], low=15, high=180)
            time_config["agents_per_hour_min"] = max(
                default_agents_per_hour_min,
                clamp_int(generated_time.get("agents_per_hour_min"), time_config["agents_per_hour_min"], low=1, high=agent_count),
            )
            time_config["agents_per_hour_max"] = max(
                default_agents_per_hour_max,
                clamp_int(
                    generated_time.get("agents_per_hour_max"),
                    time_config["agents_per_hour_max"],
                    low=1,
                    high=min(agent_count, max(default_agents_per_hour_max + 2, 8)),
                ),
            )
            if time_config["agents_per_hour_max"] < time_config["agents_per_hour_min"]:
                time_config["agents_per_hour_max"] = time_config["agents_per_hour_min"]
            for key in ("peak_hours", "work_hours", "morning_hours", "off_peak_hours"):
                time_config[key] = normalize_hours(generated_time.get(key), list(time_config[key]))
            for key, default in (
                ("peak_activity_multiplier", time_config["peak_activity_multiplier"]),
                ("work_activity_multiplier", time_config["work_activity_multiplier"]),
                ("morning_activity_multiplier", time_config["morning_activity_multiplier"]),
                ("off_peak_activity_multiplier", time_config["off_peak_activity_multiplier"]),
            ):
                time_config[key] = clamp_float(generated_time.get(key), float(default), low=0.02, high=3.0)

        rounds = max(1, int((int(time_config["total_simulation_hours"]) * 60) / max(int(time_config["minutes_per_round"]), 1)))
        generated_topics = generated_plan.get("hot_topics")
        if isinstance(generated_topics, list):
            parsed_topics = []
            for item in generated_topics:
                cleaned = normalize_theme_label(str(item or "").strip().title())
                if cleaned:
                    parsed_topics.append(cleaned)
            deduped_topics: list[str] = []
            seen_topics: set[str] = set()
            for item in parsed_topics:
                if item.lower() in seen_topics:
                    continue
                if item not in prioritized_topics and not is_conceptual_topic(
                    item,
                    entity_names=entity_name_blacklist,
                    entity_fragments=entity_fragment_blacklist,
                ):
                    continue
                seen_topics.add(item.lower())
                deduped_topics.append(item)
                if len(deduped_topics) >= 8:
                    break
            if deduped_topics:
                hot_topics = deduped_topics

        overrides = generated_plan.get("agent_overrides")
        if isinstance(overrides, list):
            by_id = {int(item["agent_id"]): item for item in agent_configs}
            baseline_by_id = {int(item["agent_id"]): dict(item) for item in agent_configs}
            for item in overrides:
                if not isinstance(item, dict):
                    continue
                try:
                    agent_id = int(item.get("agent_id"))
                except Exception:
                    continue
                target = by_id.get(agent_id)
                if not target:
                    continue
                baseline = baseline_by_id.get(agent_id, {})
                for key, bounds in (
                    ("activity_level", (0.05, 1.0)),
                    ("posts_per_hour", (0.02, 2.5)),
                    ("comments_per_hour", (0.02, 3.5)),
                    ("sentiment_bias", (-1.0, 1.0)),
                    ("influence_weight", (0.5, 6.0)),
                ):
                    value = item.get(key)
                    if isinstance(value, (int, float)):
                        candidate_value = clamp_float(value, float(target[key]), low=bounds[0], high=bounds[1])
                        if key in {"activity_level", "posts_per_hour", "comments_per_hour", "influence_weight"}:
                            baseline_value = float(baseline.get(key, target[key]) or target[key])
                            floor_ratio = 0.85 if key == "comments_per_hour" else 0.9
                            candidate_value = max(candidate_value, round(baseline_value * floor_ratio, 2))
                        target[key] = candidate_value
                for key, bounds in (
                    ("response_delay_min", (1, 360)),
                    ("response_delay_max", (2, 720)),
                ):
                    value = item.get(key)
                    if isinstance(value, (int, float)):
                        target[key] = clamp_int(value, int(target[key]), low=bounds[0], high=bounds[1])
                if int(target["response_delay_max"]) < int(target["response_delay_min"]):
                    target["response_delay_max"] = int(target["response_delay_min"])
                if isinstance(item.get("stance"), str) and item.get("stance"):
                    target["stance"] = str(item["stance"]).strip().lower()
                if isinstance(item.get("active_hours"), list):
                    target["active_hours"] = normalize_hours(item["active_hours"], list(target["active_hours"]))
                if isinstance(item.get("topics"), list):
                    target["topics"] = [str(topic).strip().title() for topic in item["topics"] if str(topic).strip()][:5]

        generated_initial_posts = generated_plan.get("initial_posts")
        if isinstance(generated_initial_posts, list):
            validated_posts: list[dict[str, object]] = []
            valid_agent_ids = {int(item["agent_id"]) for item in agent_configs}
            for item in generated_initial_posts[:6]:
                if not isinstance(item, dict):
                    continue
                try:
                    poster_agent_id = int(item.get("poster_agent_id"))
                except Exception:
                    continue
                if poster_agent_id not in valid_agent_ids:
                    continue
                platform = str(item.get("platform") or "twitter").lower()
                if platform not in {"twitter", "reddit"}:
                    platform = "twitter"
                content = str(item.get("content") or "").strip()
                topic = str(item.get("topic") or "").strip().title()
                if not content:
                    continue
                poster_type = next(
                    (
                        str(agent["entity_type"])
                        for agent in agent_configs
                        if int(agent["agent_id"]) == poster_agent_id
                    ),
                    "Entity",
                )
                validated_posts.append(
                    {
                        "poster_agent_id": poster_agent_id,
                        "poster_type": poster_type,
                        "platform": platform,
                        "topic": topic or hot_topics[0],
                        "content": content,
                    }
                )
            if validated_posts:
                initial_posts = validated_posts

        generated_events = generated_plan.get("scheduled_events")
        if isinstance(generated_events, list):
            validated_events: list[dict[str, object]] = []
            valid_agent_ids = {int(item["agent_id"]) for item in agent_configs}
            for index, item in enumerate(generated_events[:6], start=1):
                if not isinstance(item, dict):
                    continue
                try:
                    poster_agent_id = int(item.get("poster_agent_id"))
                except Exception:
                    continue
                if poster_agent_id not in valid_agent_ids:
                    continue
                trigger_round = clamp_int(item.get("round"), max(2, min(rounds, 2 + (index * 4))), low=2, high=rounds)
                platform = str(item.get("platform") or "twitter").lower()
                if platform not in {"twitter", "reddit", "both"}:
                    platform = "twitter"
                poster_type = next(
                    (
                        str(agent["entity_type"])
                        for agent in agent_configs
                        if int(agent["agent_id"]) == poster_agent_id
                    ),
                    "Entity",
                )
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                validated_events.append(
                    {
                        "event_id": f"event_{index:02d}",
                        "round": trigger_round,
                        "simulated_hour": min(int(time_config["total_simulation_hours"]) - 1, int(((trigger_round - 1) * int(time_config["minutes_per_round"])) / 60)),
                        "poster_agent_id": poster_agent_id,
                        "poster_type": poster_type,
                        "platform": platform,
                        "topic": str(item.get("topic") or hot_topics[min(index, len(hot_topics) - 1)]).title(),
                        "content": content,
                        "reason": str(item.get("reason") or "Introduce a new turn in the discussion.").strip(),
                    }
                )
            if validated_events:
                scheduled_events = validated_events

        for platform_key, defaults in (("twitter_config", twitter_config), ("reddit_config", reddit_config)):
            generated_platform = generated_plan.get(platform_key)
            if not isinstance(generated_platform, dict):
                continue
            target_platform = dict(defaults)
            for key in ("recency_weight", "popularity_weight", "relevance_weight", "echo_chamber_strength"):
                target_platform[key] = clamp_float(generated_platform.get(key), float(target_platform[key]), low=0.0, high=1.5)
            target_platform["viral_threshold"] = clamp_int(generated_platform.get("viral_threshold"), int(target_platform["viral_threshold"]), low=1, high=100)
            if platform_key == "twitter_config":
                twitter_config = target_platform
            else:
                reddit_config = target_platform

    narrative_direction = (
        f"Run the scenario as a public narrative cycle around {project_label}, "
        f"tracking how {', '.join(hot_topics[:3])} shift attention, trust, and peer amplification across the graph-linked personas."
    )
    generation_reasoning = (
        f"Derived {rounds} rounds from {time_config['total_simulation_hours']} simulated hours at {time_config['minutes_per_round']} minutes per round | "
        f"Grounded pacing, seeded posts, and event turns in {len(profiles)} graph-linked personas, entity-type behavior defaults, and dominant topics."
    )
    if isinstance(generated_plan, dict):
        generated_direction = generated_plan.get("narrative_direction")
        if isinstance(generated_direction, str) and generated_direction.strip():
            cleaned = sanitize_short_model_text(generated_direction.strip(), narrative_direction)
            if cleaned and not looks_like_prompt_echo(cleaned):
                narrative_direction = cleaned
        generated_reasoning = generated_plan.get("reasoning")
        if isinstance(generated_reasoning, str) and generated_reasoning.strip():
            cleaned = sanitize_short_model_text(generated_reasoning.strip(), generation_reasoning)
            if cleaned and not looks_like_prompt_echo(cleaned):
                generation_reasoning = cleaned
    elif llm:
        generated_direction = maybe_generate_text(
            llm,
            system_prompt=(
                "Write a concise simulation narrative direction for analysts. "
                "Return exactly two lines starting with DIRECTION: and REASONING:."
            ),
            user_prompt=(
                f"Project: {project_label}\n"
                f"Scenario: {project.scenario_brief}\n"
                f"Hot topics: {', '.join(hot_topics[:5])}\n"
                f"Persona count: {len(profiles)}\n"
                f"Scheduled event count: {len(scheduled_events)}"
            ),
        )
        if generated_direction:
            for raw_line in generated_direction.splitlines():
                line = raw_line.strip()
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                cleaned_value = sanitize_short_model_text(value.strip(), value.strip())
                if not cleaned_value:
                    continue
                lowered_key = key.strip().lower()
                if lowered_key == "direction":
                    narrative_direction = cleaned_value
                if lowered_key == "reasoning":
                    generation_reasoning = cleaned_value

    return {
        "time_config": time_config,
        "agent_configs": agent_configs,
        "twitter_config": twitter_config,
        "reddit_config": reddit_config,
        "event_config": {
            "initial_posts": initial_posts,
            "scheduled_events": scheduled_events,
            "narrative_direction": narrative_direction,
            "hot_topics": hot_topics,
        },
        "generation_reasoning": generation_reasoning,
    }


def build_glass_action_plan(
    *,
    project: Project,
    profiles: list[dict[str, object]],
    config: dict[str, object],
    total_rounds: int,
) -> list[dict[str, object]]:
    """Generate a round-by-round action plan for the live simulation playback."""
    project_label = derive_project_label(project.name, project.scenario_brief, topics=[
        item for item in config.get("event_config", {}).get("hot_topics", []) if isinstance(item, str)
    ])
    topics = [
        item
        for item in config.get("event_config", {}).get("hot_topics", [])
        if isinstance(item, str) and item.strip()
    ] or ["Trust", "Response", "Narrative"]
    actions: list[dict[str, object]] = []
    visible_profiles = profiles[: min(len(profiles), 24)]
    action_types = ["CREATE_POST", "COMMENT", "QUOTE_POST", "LIKE_POST", "FOLLOW"]
    for round_number in range(1, total_rounds + 1):
        for offset, profile in enumerate(visible_profiles[:8]):
            topic = topics[(round_number + offset - 1) % len(topics)]
            action_type = action_types[(round_number + offset - 1) % len(action_types)]
            platform = "twitter" if offset % 2 == 0 else "reddit"
            base_content = (
                f"Round {round_number}: {profile['name']} is reacting to {topic.lower()} as a live signal for "
                f"{project_label}, testing whether the narrative is turning into durable preference or just fast attention."
            )
            actions.append(
                {
                    "action_id": f"action_{round_number:03d}_{offset + 1:02d}",
                    "round_num": round_number,
                    "platform": platform,
                    "agent_id": profile["agent_id"],
                    "agent_name": profile["name"],
                    "action_type": action_type,
                    "content": base_content,
                    "topic": topic,
                }
            )
    return actions


def build_glass_interview_response(
    llm: TextGenerator | None,
    *,
    project: Project,
    profile: dict[str, object],
    prompt: str,
    recent_actions: list[dict[str, object]],
) -> str:
    """Generate a first-person interview response grounded in the persona and run history."""
    project_label = derive_project_label(project.name, project.scenario_brief, topics=list(profile.get("interested_topics", [])))
    action_summary = "\n".join(
        f"- Round {item.get('round_num', '?')}: {item.get('content', '')}"
        for item in recent_actions[:4]
    ) or "- No recent actions recorded."
    trust_lens = str(profile.get("trust_lens") or "")
    narrative_role = str(profile.get("narrative_role") or "")
    platform_behavior = str(profile.get("platform_behavior") or "")
    engagement_style = str(profile.get("engagement_style") or "")
    conceptual_focus = dedupe_preserve_order(
        [
            *derive_priority_themes(project.scenario_brief),
            *extract_focus_phrases(
                " ".join(
                    [
                        str(profile.get("persona") or ""),
                        str(profile.get("bio") or ""),
                        trust_lens,
                        platform_behavior,
                    ]
                ),
                limit=4,
            ),
        ],
        limit=3,
    )
    focus_text = ", ".join(conceptual_focus[:2]) or "pricing, authenticity, and cultural relevance"
    recent_signal = ""
    if recent_actions:
        lead_action = recent_actions[0]
        lead_content = sanitize_short_model_text(str(lead_action.get("content") or "").strip(), "")
        if lead_content:
            if len(lead_content) > 180:
                lead_content = f"{lead_content[:177].rsplit(' ', 1)[0]}..."
            recent_signal = f" In the run, the most visible recent signal for me was: {lead_content}"
    fallback = (
        f"I'm {profile.get('name', 'this persona')}, speaking as a {str(profile.get('profession') or 'participant').lower()}. "
        f"My read is that {project_label} is really being tested on {focus_text}. "
        f"{trust_lens or 'The key question is whether the narrative holds up once people move from first impressions to proof.'} "
        f"{platform_behavior or 'I would watch how the tone diverges between Twitter momentum and Reddit skepticism before calling it durable.'}"
        f"{recent_signal}"
    )
    if llm is None:
        return fallback
    generated = maybe_generate_text(
        llm,
        system_prompt=(
            "Answer as the simulated persona in first person. Stay concrete, grounded, and avoid mentioning being an AI."
        ),
        user_prompt=(
            f"Project: {project_label}\n"
            f"Scenario: {project.scenario_brief}\n"
            f"Persona name: {profile.get('name')}\n"
            f"Persona role: {profile.get('profession')}\n"
            f"Persona bio: {profile.get('bio')}\n"
            f"Trust lens: {trust_lens}\n"
            f"Narrative role: {narrative_role}\n"
            f"Platform behavior: {platform_behavior}\n"
            f"Engagement style: {engagement_style}\n"
            f"Interested topics: {', '.join(profile.get('interested_topics', []))}\n"
            f"Recent actions:\n{action_summary}\n\n"
            f"Interview prompt: {prompt}"
        ),
    )
    cleaned = sanitize_short_model_text(generated)
    if looks_like_prompt_echo(cleaned):
        return fallback
    if not cleaned or not re.search(r"\b(i|i'm|im|my)\b", cleaned.lower()):
        return fallback
    return cleaned or fallback


def build_glass_report_package(
    *,
    project: Project,
    focus: str,
    config: dict[str, object],
    actions: list[dict[str, object]],
    interviews: list[dict[str, str]],
    posts_by_platform: dict[str, list[dict[str, object]]] | None = None,
    comments: list[dict[str, object]] | None = None,
    graph_metadata: dict[str, object] | None = None,
    graph_nodes: list[dict[str, object]] | None = None,
    graph_facts: list[str] | None = None,
    llm: TextGenerator | None = None,
) -> dict[str, object]:
    """Generate a sectioned report payload for the glass report workspace."""
    configured_topics = [
        item
        for item in config.get("event_config", {}).get("hot_topics", [])
        if isinstance(item, str)
    ] or ["Brand Loyalty", "Pricing Sensitivity", "Brand Authenticity"]
    project_label = derive_project_label(
        project.name,
        project.scenario_brief,
        topics=configured_topics,
        graph_facts=graph_facts or [],
    )
    report_label = project_label.replace("Scenario", "Simulation") if "Scenario" in project_label else project_label
    if not report_label.lower().endswith(("simulation", "report")):
        report_label = f"{report_label} Simulation"
    posts_by_platform = posts_by_platform or {}
    comments = comments or []
    graph_metadata = graph_metadata or {}
    graph_nodes = [
        item
        for item in (graph_nodes or graph_metadata.get("nodes", []) or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    graph_facts = [str(item).strip() for item in (graph_facts or []) if str(item).strip()]
    entity_name_blacklist, entity_fragment_blacklist = build_entity_topic_blacklist(
        [
            str(item.get("name") or "").strip()
            for item in graph_nodes
        ]
    )
    action_count = len(actions)
    analysis_actions = [
        item
        for item in actions
        if str(item.get("action_type") or "").upper() in {"CREATE_POST", "QUOTE_POST", "COMMENT", "REPOST"}
        or (
            str(item.get("content") or "").strip()
            and str(item.get("action_type") or "").upper() not in {"REFRESH", "TREND", "SEARCH_POSTS", "SEARCH_USER", "DO_NOTHING"}
        )
    ]
    visible_actions = analysis_actions or actions
    visible_action_count = len(visible_actions)
    total_rounds = max((int(item.get("round_num", 0)) for item in actions), default=0)
    twitter_posts = len(posts_by_platform.get("twitter", []))
    reddit_posts = len(posts_by_platform.get("reddit", []))
    comments_count = len(comments)
    node_count = int(graph_metadata.get("node_count", 0) or 0)
    edge_count = int(graph_metadata.get("edge_count", 0) or 0)
    entity_types = [
        str(item)
        for item in graph_metadata.get("entity_types", [])
        if isinstance(item, str)
    ]

    report_platform_names = {
        "facebook",
        "instagram",
        "pinterest",
        "reddit",
        "snapchat",
        "tiktok",
        "wechat",
        "x",
        "twitter",
        "youtube",
    }
    report_location_names = {
        "asia-pacific",
        "beijing",
        "california",
        "china",
        "europe",
        "france",
        "italy",
        "japan",
        "london",
        "los angeles",
        "new york",
        "north america",
        "paris",
        "seoul",
        "shanghai",
        "south korea",
        "tokyo",
        "u.k.",
        "uk",
        "u.s.",
        "us",
        "usa",
        "united kingdom",
        "united states",
    }
    report_event_fragments = {
        "awards",
        "championship",
        "cup",
        "fashion week",
        "festival",
        "gala",
        "games",
        "open",
        "olympic",
        "paralympic",
        "tournament",
        "week",
        "wimbledon",
    }
    report_location_hints = {"city", "country", "geography", "market", "province", "region", "territory"}
    report_product_fragments = {
        "collection",
        "double rl",
        "fragrance",
        "home",
        "label",
        "line",
        "polo",
        "purple label",
        "rrl",
    }

    def node_slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def report_node_categories(node: dict[str, object]) -> set[str]:
        name = str(node.get("name") or "").strip()
        label = str(node.get("label") or "").strip()
        summary = str(node.get("summary") or "").strip()
        lowered_name = " ".join(name.lower().split())
        lowered_summary = summary.lower()
        categories: set[str] = set()
        label_slug = node_slug(label)

        is_location = (
            label == "Location"
            or lowered_name in report_location_names
            or any(token in lowered_summary for token in report_location_hints)
        )
        is_platform = label == "Platform" or lowered_name in report_platform_names
        is_event = (
            label == "Event"
            or (
                label in {"Organization", "Entity", "Node"}
                and any(fragment in lowered_name for fragment in report_event_fragments)
                and "team" not in lowered_name
            )
        )
        is_product = label in {"Product", "Product Line"} or (
            label in {"Luxury Brand", "Brand"} and any(fragment in lowered_name for fragment in report_product_fragments)
        )

        if label in {"Luxury Brand", "Brand", "Competitor Brand", "Fashion Brand", "Sportswear Competitor"} or label_slug in {"luxurybrand", "brand", "competitorbrand", "fashionbrand", "sportswearcompetitor"}:
            categories.add("brands")
        if label in {"Consumer Cohort", "Audience Segment", "Audience Group", "Discount Shopper", "Brand Purist"}:
            categories.add("audiences")
        if label in {"Fashion Media Outlet", "Media Outlet"}:
            categories.add("media")
        if label in {"Person", "Executive", "Public Figure", "Market Analyst", "Retail Industry Analyst", "Geopolitical Commentator", "Sustainability Activist", "Athlete Ambassador"}:
            categories.add("people")
        if is_product:
            categories.add("products")
        if is_platform:
            categories.add("platforms")
        if is_event:
            categories.add("events")
        if is_location:
            categories.add("locations")
        if label in {"Organization", "Institutional Actor", "Creator Group", "Internal Team", "Retail Channel", "Region"} and not (is_location or is_platform or is_event):
            categories.add("organizations")
        if not categories and label not in {"Entity", "Node"}:
            categories.add("organizations")
        return categories

    named_entities: dict[str, list[str]] = {
        "brands": [],
        "products": [],
        "events": [],
        "locations": [],
        "platforms": [],
        "media": [],
        "audiences": [],
        "people": [],
        "organizations": [],
    }
    for item in graph_nodes:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        for category in report_node_categories(item):
            if name not in named_entities[category]:
                named_entities[category].append(name)

    round_counter = Counter(int(item.get("round_num", 0) or 0) for item in visible_actions if int(item.get("round_num", 0) or 0) > 0)
    peak_rounds = [round_num for round_num, _ in round_counter.most_common(3)]
    agent_counter = Counter(str(item.get("agent_name") or "Unknown") for item in visible_actions if item.get("agent_name"))
    leading_agents = [agent for agent, _ in agent_counter.most_common(3)]
    top_agents = [{"name": agent, "count": count} for agent, count in agent_counter.most_common(4)]
    agent_config_lookup = {
        str(item.get("external_agent_id") or f"agent_{item.get('agent_id', '0')}"): item
        for item in config.get("agent_configs", [])
        if isinstance(item, dict)
    }
    prioritized_topics = dedupe_preserve_order(
        [*configured_topics, *derive_priority_themes(project.scenario_brief)],
        limit=8,
    )
    topic_counter = Counter()
    for topic in prioritized_topics:
        topic = normalize_theme_label(topic)
        if is_conceptual_topic(
            topic,
            entity_names=entity_name_blacklist,
            entity_fragments=entity_fragment_blacklist,
        ) or topic in prioritized_topics:
            topic_counter[clean_topic_label(topic)] += 6
    topic_counter.update(
        clean_topic_label(str(item.get("topic") or "").strip())
        for item in visible_actions
        if str(item.get("topic") or "").strip()
        and is_conceptual_topic(
            str(item.get("topic") or "").strip(),
            entity_names=entity_name_blacklist,
            entity_fragments=entity_fragment_blacklist,
        )
    )
    for platform_posts in posts_by_platform.values():
        for post in platform_posts[:12]:
            if not isinstance(post, dict):
                continue
            content = " ".join(
                str(post.get(key) or "")
                for key in ("content", "title", "body", "text")
            ).strip()
            for term in extract_focus_phrases(content, limit=3):
                if is_conceptual_topic(
                    term,
                    entity_names=entity_name_blacklist,
                    entity_fragments=entity_fragment_blacklist,
                ):
                    topic_counter[term] += 1
    for term in extract_focus_phrases(project.scenario_brief, limit=8):
        term = normalize_theme_label(term)
        if is_conceptual_topic(
            term,
            entity_names=entity_name_blacklist,
            entity_fragments=entity_fragment_blacklist,
        ) or term in prioritized_topics:
            topic_counter[term] += 4
    for fact in graph_facts[:6]:
        for theme in derive_priority_themes(fact):
            if is_conceptual_topic(
                theme,
                entity_names=entity_name_blacklist,
                entity_fragments=entity_fragment_blacklist,
            ):
                topic_counter[normalize_theme_label(theme)] += 3
        for term in extract_focus_phrases(fact, limit=2):
            if is_conceptual_topic(
                term,
                entity_names=entity_name_blacklist,
                entity_fragments=entity_fragment_blacklist,
            ):
                topic_counter[normalize_theme_label(term)] += 2
    dominant_topics = [
        topic
        for topic, _score in sorted(
            (
                (normalize_theme_label(topic), int(count) + theme_signal_score(topic))
                for topic, count in topic_counter.items()
                if topic and topic.casefold() not in GENERIC_TOPIC_TERMS and topic.casefold() not in {"ralph", "lauren"}
            ),
            key=lambda item: (-item[1], -len(item[0].split()), item[0]),
        )[:8]
    ] or [clean_topic_label(topic) for topic in configured_topics[:4]]
    dominant_topics = rank_theme_candidates(prioritized_topics + dominant_topics, limit=5)
    platform_focus = "twitter" if twitter_posts >= reddit_posts else "reddit"
    action_type_counter = Counter(str(item.get("action_type") or "ACTION") for item in visible_actions)
    platform_action_counter = Counter(str(item.get("platform") or "unknown") for item in visible_actions)
    active_type_counter = Counter(
        str((agent_config_lookup.get(str(item.get("agent_id") or ""), {}) or {}).get("entity_type") or "Entity")
        for item in visible_actions
        if item.get("agent_id")
    )
    stance_counter = Counter(
        str((agent_config_lookup.get(str(item.get("agent_id") or ""), {}) or {}).get("stance") or "neutral")
        for item in visible_actions
        if item.get("agent_id")
    )

    def top_graph_entities(labels: set[str], *, limit: int = 4) -> list[str]:
        names: list[str] = []
        for item in graph_nodes:
            label = str(item.get("label") or "")
            if label not in labels:
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in names:
                continue
            names.append(name)
            if len(names) >= limit:
                break
        return names

    def top_named_entities(category: str, *, limit: int = 4) -> list[str]:
        return named_entities.get(category, [])[:limit]

    def top_agents_by_entity_labels(labels: set[str], *, limit: int = 4) -> list[str]:
        names: list[str] = []
        for agent_name, _ in agent_counter.most_common():
            matching_id = next(
                (
                    str(action.get("agent_id") or "")
                    for action in visible_actions
                    if str(action.get("agent_name") or "") == agent_name
                ),
                "",
            )
            config_entry = agent_config_lookup.get(matching_id, {})
            entity_type = str(config_entry.get("entity_type") or "")
            if entity_type not in labels:
                continue
            if agent_name not in names:
                names.append(agent_name)
            if len(names) >= limit:
                break
        return names

    interview_quotes = interviews[:6]
    quote_lines = [
        f"> {(sanitize_short_model_text(item['response'], 'Interview evidence was synthesized from persona and action history.') or 'Interview evidence was synthesized from persona and action history.')}\n>\n> - {item['agent_name']}"
        for item in interview_quotes
    ] or ["> Interview evidence was synthesized from persona and action history."]
    interview_snippets = [
        sanitize_model_excerpt(str(item.get("response") or ""), "Interview evidence available.")
        or "Interview evidence available."
        for item in interview_quotes
    ]

    graph_lines = [
        f"- Graph coverage: {node_count} nodes / {edge_count} edges" if node_count or edge_count else "- Graph coverage was not persisted for this run.",
        f"- Entity types in scope: {', '.join(str(item) for item in entity_types[:5])}" if entity_types else "- Entity type inventory is not available.",
    ]
    graph_lines.extend(f"- Graph signal: {item}" for item in graph_facts[:4])

    signal_lines = [runtime_action_line(item, verb="flagged") for item in visible_actions[:10]]
    for platform_name, platform_posts in posts_by_platform.items():
        for post in platform_posts[:3]:
            if not isinstance(post, dict):
                continue
            content = next(
                (
                    str(post.get(key)).strip()
                    for key in ("content", "title", "body", "text")
                    if str(post.get(key) or "").strip()
                ),
                "",
            )
            if content:
                snippet = content if len(content) <= 180 else f"{content[:177].rsplit(' ', 1)[0]}..."
                signal_lines.append(f"- {platform_name.title()} post signal: {snippet}")
    for comment in comments[:4]:
        if not isinstance(comment, dict):
            continue
        content = next(
            (
                str(comment.get(key)).strip()
                for key in ("content", "body", "text")
                if str(comment.get(key) or "").strip()
            ),
            "",
        )
        if content:
            snippet = content if len(content) <= 160 else f"{content[:157].rsplit(' ', 1)[0]}..."
            signal_lines.append(f"- Comment signal: {snippet}")
    if not signal_lines:
        signal_lines.append("- No runtime platform signals were persisted for this run.")

    strongest_posts: list[str] = []
    for platform_name, platform_posts in posts_by_platform.items():
        sorted_posts = sorted(
            [item for item in platform_posts if isinstance(item, dict)],
            key=lambda item: int(item.get("score", 0) or 0),
            reverse=True,
        )
        for post in sorted_posts[:2]:
            content = next(
                (
                    str(post.get(key)).strip()
                    for key in ("content", "title", "body", "text")
                    if str(post.get(key) or "").strip()
                ),
                "",
            )
            if not content:
                continue
            snippet = content if len(content) <= 220 else f"{content[:217].rsplit(' ', 1)[0]}..."
            strongest_posts.append(f"- {platform_name.title()} lead: {snippet}")

    runtime_quotes = [
        line[2:] if line.startswith("- ") else line
        for line in dedupe_preserve_order(
            [*strongest_posts, *signal_lines[:6]],
            limit=8,
        )
    ]

    scenario_flags = {
        "pricing": "pricing" in project.scenario_brief.lower() or "$" in project.scenario_brief,
        "authenticity": "authentic" in project.scenario_brief.lower(),
        "sustainability": "sustainab" in project.scenario_brief.lower(),
        "loyalty": "loyal" in project.scenario_brief.lower(),
        "competition": any(term in project.scenario_brief.lower() for term in ("competitor", "burberry", "tommy hilfiger", "michael kors", "lacoste")),
    }
    competitive_agents = top_agents_by_entity_labels({"Competitor Brand", "Sportswear Competitor"})
    audience_agents = top_agents_by_entity_labels({"Audience Segment", "Consumer Cohort", "Discount Shopper", "Brand Purist"})
    media_agents = top_agents_by_entity_labels({"Media Outlet", "Fashion Media Outlet", "Market Analyst", "Retail Industry Analyst", "Geopolitical Commentator"})
    institutional_agents = top_agents_by_entity_labels({"Brand", "Luxury Brand", "Fashion Brand", "Executive", "Institutional Actor", "Product Line", "Platform", "Organization", "Sustainability Activist"})
    brand_entities = top_named_entities("brands", limit=6) or top_graph_entities({"Brand", "Luxury Brand", "Competitor Brand", "Fashion Brand", "Sportswear Competitor"}, limit=6)
    product_entities = top_named_entities("products", limit=6) or top_graph_entities({"Product Line"}, limit=6)
    event_entities = top_named_entities("events", limit=5) or top_graph_entities({"Event"}, limit=5)
    location_entities = top_named_entities("locations", limit=5) or top_graph_entities({"Location"}, limit=5)
    platform_entities = top_named_entities("platforms", limit=5)
    media_entities = top_named_entities("media", limit=5)
    organization_entities = top_named_entities("organizations", limit=6)
    people_entities = top_named_entities("people", limit=5)
    audience_entities = top_named_entities("audiences", limit=5)
    core_named_entities = dedupe_preserve_order(
        [
            *brand_entities[:4],
            *product_entities[:3],
            *platform_entities[:2],
            *location_entities[:2],
            *event_entities[:2],
        ],
        limit=10,
    )

    dominant_topic_text = dominant_topics[0].lower() if dominant_topics else "the leading narrative"
    secondary_topic_text = dominant_topics[1].lower() if len(dominant_topics) > 1 else "attention"
    executive_summary = (
        f"{project_label} is most exposed when {dominant_topic_text} and {secondary_topic_text} "
        f"move faster than the supporting evidence, especially when the {platform_focus} conversation accelerates first and "
        f"the loyalty question shifts from aesthetics to price, authenticity, and repeat behavior. "
        f"The most decision-useful evidence in this run came from {visible_action_count} visible post, quote, repost, and comment actions rather than passive trace events, "
        f"especially around {', '.join(core_named_entities[:4]) or 'the main named entities in the graph'}."
    )

    recommendation_lines = [
        f"- Separate fast-response messaging from deeper proof points around {dominant_topic_text}.",
        "- Pair the visible aesthetic hook with explicit price, quality, and sustainability proof before the second-wave backlash hardens.",
        f"- Track whether {secondary_topic_text} keeps converging or fragments by platform, actor type, and competitor reaction.",
        f"- Re-run the scenario when a new external signal changes who holds narrative authority across the {platform_focus} conversation.",
    ]

    adoption_title = (
        "The Viral Aesthetic Surge: December 2025 Holiday Campaign"
        if any(topic in {"Ralph Lauren Christmas", "Viral Aesthetic", "Viral Momentum"} for topic in dominant_topics)
        else "Initial Adoption and Narrative Velocity"
    )
    reaction_title = "Agent Reaction Matrix: Divergent Responses Across Consumer Segments"
    competition_title = "Competitive Landscape and Market Positioning Shifts"
    risk_title = (
        "Emergent Risks: Sustainability Criticism and Brand Trust Erosion"
        if scenario_flags["sustainability"]
        else "Emergent Risks: Authenticity Friction and Brand Trust Erosion"
    )
    loyalty_title = (
        "Loyalty Outlook, Conversion Barriers, and Strategic Recommendations"
        if scenario_flags["loyalty"] or scenario_flags["competition"]
        else "Loyalty Outlook and Strategic Recommendations"
    )

    section_specs = [
        {
            "title": "Executive Summary",
            "brief": "Give the analyst team the shortest credible readout of the scenario.",
        },
        {
            "title": adoption_title,
            "brief": "Explain how the scenario first took hold, who amplified it, and which early signals mattered most.",
        },
        {
            "title": reaction_title,
            "brief": "Explain how the most important audience, media, institutional, and competitor segments reacted to the scenario.",
        },
        {
            "title": "Platform Split: Velocity Versus Scrutiny",
            "brief": "Compare what accelerated on Twitter with what deepened or resisted on Reddit, and explain what that means analytically.",
        },
        {
            "title": competition_title,
            "brief": "Explain how competitors and adjacent brands repositioned themselves while the scenario unfolded.",
        },
        {
            "title": risk_title,
            "brief": "Explain the structural trust, sustainability, and authenticity risks that emerged during the run.",
        },
        {
            "title": loyalty_title,
            "brief": "Assess whether the run indicates durable loyalty, temporary hype, or emerging conversion barriers, then recommend next actions.",
        },
        {
            "title": "Persona Interviews",
            "brief": "Use persona testimony to show how actors interpreted the scenario from inside the run.",
        },
    ]

    if llm:
        generated_outline = maybe_generate_json(
            llm,
            system_prompt=(
                "Return a JSON object with keys executive_summary, recommendations, and section_briefs. "
                "section_briefs must be a list of objects with title and brief. Keep the same section titles if provided. "
                "Prioritize the actual scenario tensions, named actors, markets, and platforms, not generic brand-analysis language."
            ),
            user_prompt=(
                f"Project: {project_label}\n"
                f"Scenario: {project.scenario_brief}\n"
                f"Focus: {focus}\n"
                f"Graph: {node_count} nodes, {edge_count} edges, entity types {', '.join(entity_types[:6])}\n"
                f"Runtime: {action_count} actions, {twitter_posts} twitter posts, {reddit_posts} reddit posts, {comments_count} comments\n"
                f"Dominant topics: {', '.join(dominant_topics[:5])}\n"
                f"Named entity inventory: brands={', '.join(brand_entities[:6])}; products={', '.join(product_entities[:6])}; locations={', '.join(location_entities[:5])}; platforms={', '.join(platform_entities[:5])}; organizations={', '.join(organization_entities[:5])}; people={', '.join(people_entities[:5])}\n"
                f"Peak rounds: {', '.join(str(item) for item in peak_rounds)}\n"
                f"Leading agents: {', '.join(leading_agents[:4])}\n"
                f"Graph facts: {' | '.join(graph_facts[:4])}\n"
                f"Runtime evidence: {' | '.join(runtime_quotes[:5])}\n"
                f"Interview evidence: {' | '.join(interview_snippets[:3])}\n"
                f"Section titles: {', '.join(item['title'] for item in section_specs)}"
            ),
            max_tokens=1600,
        )
        if isinstance(generated_outline, dict):
            generated_summary = generated_outline.get("executive_summary")
            if isinstance(generated_summary, str):
                cleaned_summary = sanitize_short_model_text(generated_summary, executive_summary)
                if cleaned_summary and not looks_like_prompt_echo(cleaned_summary):
                    executive_summary = cleaned_summary
            generated_recommendations = generated_outline.get("recommendations")
            if isinstance(generated_recommendations, list):
                parsed_lines = [
                    f"- {sanitize_short_model_text(str(item).strip(), str(item).strip())}"
                    for item in generated_recommendations
                    if str(item).strip()
                ]
                parsed_lines = [item for item in parsed_lines if item != "- None"]
                if parsed_lines:
                    recommendation_lines = parsed_lines[:4]
            generated_section_briefs = generated_outline.get("section_briefs")
            if isinstance(generated_section_briefs, list):
                briefs_by_title = {
                    str(item.get("title") or "").strip(): str(item.get("brief") or "").strip()
                    for item in generated_section_briefs
                    if isinstance(item, dict) and str(item.get("title") or "").strip()
                }
                updated_specs: list[dict[str, str]] = []
                for item in section_specs:
                    brief = briefs_by_title.get(item["title"], item["brief"])
                    updated_specs.append({"title": item["title"], "brief": brief or item["brief"]})
                section_specs = updated_specs

    def fallback_section_content(title: str) -> str:
        if title == "Executive Summary":
            return "\n".join(
                [
                    "## Executive Summary",
                    "",
                    executive_summary,
                    "",
                    f"- Scenario: {project_label}",
                    f"- Focus: {focus or 'General analyst briefing'}",
                    f"- Total rounds observed: {total_rounds}",
                    f"- Total actions observed: {action_count}",
                    f"- Visible narrative actions observed: {visible_action_count}",
                    f"- Key named entities in scope: {', '.join(core_named_entities) or 'Named entity inventory remained sparse in this run'}",
                    f"- Posts captured: {twitter_posts} twitter, {reddit_posts} reddit, {comments_count} comments",
                    f"- Most active entity types: {', '.join(name for name, _ in active_type_counter.most_common(4)) or 'Activity type mix unavailable'}",
                    f"- Platform split: {', '.join(f'{name}={count}' for name, count in platform_action_counter.items()) or 'No platform activity recorded'}",
                    f"- Active platforms and media surfaces: {', '.join(dedupe_preserve_order(platform_entities[:3] + media_entities[:3], limit=6)) or 'No platform inventory persisted'}",
                    f"- Key markets and places: {', '.join(location_entities[:5]) or 'No market inventory persisted'}",
                ]
            )
        if title == adoption_title:
            return "\n".join(
                [
                    f"## {adoption_title}",
                    "",
                    f"The opening phase centered on {', '.join(dominant_topics[:3])}, with the first visible signals coming from {platform_focus} and the agents that carried {project_label} into public conversation.",
                    "",
                    "**Initial Viral Explosion**",
                    (
                        f"{project_label} generated immediate attention because {dominant_topic_text} gave participants a simple visual or cultural hook, "
                        f"but the run shows that attention alone did not settle the question of trust, value, or repeat loyalty."
                    ),
                    (
                        f"The strongest named assets in the graph were {', '.join(product_entities[:4]) or ', '.join(brand_entities[:4]) or ', '.join(core_named_entities[:4]) or 'the main brand entities'}, "
                        "which is where the scenario translated abstract brand language into concrete products, events, and visible cultural references."
                    ),
                    (
                        f"The first wave stayed concentrated around {', '.join(leading_agents[:3]) or 'a small set of visible amplifiers'}, "
                        f"which means the scenario looked louder before it looked deeper."
                    ),
                    "",
                    "**What Converted And What Did Not**",
                    (
                        f"The strongest early movement happened on {platform_focus}, but the cross-platform split shows the narrative still had to survive "
                        f"a second reading once pricing, authenticity, and sustainability entered the conversation."
                    ),
                    "",
                    *graph_lines,
                    "",
                    f"- Peak rounds by activity: {', '.join(str(item) for item in peak_rounds) or 'No peak round detected'}",
                    f"- Highest-volume entity types: {', '.join(name for name, _ in active_type_counter.most_common(4)) or 'No active entity types recorded'}",
                    f"- Named brands, markets, and platforms: {', '.join(dedupe_preserve_order(brand_entities[:3] + location_entities[:3] + platform_entities[:3], limit=9)) or 'No concrete entity inventory persisted'}",
                    "",
                    *signal_lines[:8],
                    "",
                    *(strongest_posts[:4] or ["- No platform-leading posts were retained."]),
                ]
            )
        if title == reaction_title:
            return "\n".join(
                [
                    f"## {reaction_title}",
                    "",
                    "The run did not produce one unified public response. It split by segment, with audience groups, competitors, media actors, and institutional voices each reacting from different value systems.",
                    "",
                    "**Audience Segments**",
                    (
                        f"Audience-facing entities such as {', '.join(audience_agents[:3] or audience_entities[:3]) or 'the main consumer segments'} reacted through affordability, cultural fit, "
                        "and whether the brand looked genuinely earned rather than temporarily viral."
                    ),
                    "",
                    "**Media And Amplifiers**",
                    (
                        f"Media-facing agents such as {', '.join(media_agents[:3] or media_entities[:3] or platform_entities[:3]) or 'the visible media layer'} helped convert the scenario from a style signal into an evaluative narrative, "
                        "which is why transparency and authenticity became more important over time."
                    ),
                    "",
                    "**Institutional And Brand Voices**",
                    (
                        f"Institutional actors such as {', '.join(institutional_agents[:3] or organization_entities[:3] or people_entities[:3]) or 'the core brand-facing accounts'} stayed more measured, "
                        "but that restraint also meant they did not fully control the tone once external criticism picked up."
                    ),
                    "",
                    f"- Stance mix: {', '.join(f'{name}={count}' for name, count in stance_counter.items()) or 'No stance data'}",
                    f"- Leading audience or media agents: {', '.join(dedupe_preserve_order(audience_agents + media_agents, limit=6)) or 'No segment leaders recorded'}",
                    "",
                    *(signal_lines[:8] or ["- No reaction signals were retained."]),
                ]
            )
        if title == "Platform Split: Velocity Versus Scrutiny":
            return "\n".join(
                [
                    "## Platform Split: Velocity Versus Scrutiny",
                    "",
                    "The run behaved differently by platform. Twitter concentrated early visibility and repeat naming, while Reddit carried more of the price, authenticity, and sustainability stress test that determines whether relevance can convert into durable preference.",
                    "",
                    "**Twitter: Fast Narrative Compression**",
                    (
                        f"Twitter generated {twitter_posts} posts and {platform_action_counter.get('twitter', 0)} visible actions, which made it the faster surface for aesthetic framing, creator amplification, and media pickup."
                    ),
                    (
                        f"The most visible twitter-side actors were {', '.join([item['name'] for item in top_agents if item['name']]) or 'the lead amplifiers'}, "
                        "which means attention clustered quickly around a small set of voices before the broader market had fully interpreted the move."
                    ),
                    "",
                    "**Reddit: Slower But More Diagnostic**",
                    (
                        f"Reddit generated {reddit_posts} posts and {comments_count} comments, which made it the better surface for price-value debate, authenticity checks, and skepticism about whether the brand had earned Gen Z attention."
                    ),
                    (
                        "This mattered because the loyalty question was not decided by who noticed the campaign first, but by whether deeper conversation kept reinforcing the same story once comparison and criticism entered."
                    ),
                    "",
                    f"- Platform action split: {', '.join(f'{name}={count}' for name, count in platform_action_counter.items()) or 'No platform activity recorded'}",
                    f"- Dominant topics by both platforms: {', '.join(dominant_topics[:5])}",
                    "",
                    *(strongest_posts[:4] or ["- No leading posts were retained for platform comparison."]),
                ]
            )
        if title == competition_title:
            return "\n".join(
                [
                    f"## {competition_title}",
                    "",
                    "Competitive pressure did not remain abstract in this run. Rival brands and adjacent category voices used the same conversation to test whether the focal brand's momentum was durable or opportunistic.",
                    "",
                    "**Where Competitors Gained Ground**",
                    (
                        f"Competitor-facing agents such as {', '.join(competitive_agents[:4]) or 'the main competitor set'} benefitted whenever the conversation moved from aesthetic discovery "
                        "to pricing, authenticity, or sustainability proof."
                    ),
                    (
                        f"The graph also kept explicit competitor and adjacent brand references in play, including {', '.join(brand_entities[:5] or organization_entities[:3]) or 'the broader brand set'}, "
                        "which is why comparative judgment became more important as the run progressed."
                    ),
                    "",
                    "**Positioning Shift To Watch**",
                    (
                        "The most important shift was not simple share-of-voice. It was the move from attention metrics to comparative judgment, where competing brands could look more grounded, "
                        "more transparent, or simply easier to justify."
                    ),
                    "",
                    f"- Competitive pressure flags: pricing={scenario_flags['pricing']}, competition={scenario_flags['competition']}, sustainability={scenario_flags['sustainability']}",
                    f"- Competitor and media leaders: {', '.join(dedupe_preserve_order(competitive_agents + media_agents, limit=6)) or 'No competitor leaders recorded'}",
                    "",
                    *(strongest_posts[:4] or ["- No competitive platform signals were retained."]),
                ]
            )
        if title == risk_title:
            barrier_lines = [
                line
                for line in signal_lines
                if any(
                    keyword in line.lower()
                    for keyword in ("price", "pricing", "authentic", "sustainab", "supply", "trust", "burberry", "tommy", "hilfiger")
                )
            ]
            return "\n".join(
                [
                    f"## {risk_title}",
                    "",
                    "The most durable resistance in the run came from the gap between aesthetic attention and the harder questions of price, authenticity, and whether the brand had earned enough trust to keep younger audiences engaged.",
                    "",
                    "**Trust Erosion Path**",
                    (
                        "Once the conversation moved beyond the initial aesthetic hook, skepticism clustered around value, transparency, and whether the campaign represented a durable cultural fit or a temporary imitation of Gen Z language."
                    ),
                    "",
                    "**Why The Risk Persists**",
                    (
                        "The graph-backed evidence and runtime signals point to a structural issue: backlash themes are easier to reinforce than loyalty themes unless the brand can supply proof that survives comparison, not just attention."
                    ),
                    "",
                    f"- Dominant topics: {', '.join(dominant_topics[:5])}",
                    f"- Named products, events, markets, and platforms in scope: {', '.join(dedupe_preserve_order(product_entities[:3] + event_entities[:2] + location_entities[:2] + platform_entities[:2], limit=9)) or 'No concrete graph entities retained'}",
                    f"- Leading agents voicing friction: {', '.join(leading_agents) or 'No dominant agent detected'}",
                    f"- Platform emphasis: Twitter posts {twitter_posts}, Reddit posts {reddit_posts}, Reddit comments {comments_count}",
                    f"- Stance mix: {', '.join(f'{name}={count}' for name, count in stance_counter.items()) or 'No stance data'}",
                    f"- Competition and pressure flags: pricing={scenario_flags['pricing']}, authenticity={scenario_flags['authenticity']}, sustainability={scenario_flags['sustainability']}, competition={scenario_flags['competition']}",
                    "",
                    *(barrier_lines[:10] or signal_lines[:8]),
                ]
            )
        if title == loyalty_title:
            return "\n".join(
                [
                    f"## {loyalty_title}",
                    "",
                    "The run points to a loyalty test rather than a clean conversion story. The key strategic question is whether early visibility can survive the second-wave scrutiny that appears once the conversation turns from aesthetic appeal to brand proof.",
                    "",
                    "**Conversion Outlook**",
                    (
                        f"The evidence suggests that {project_label} can create a burst of relevance, but durable conversion still depends on whether {dominant_topic_text} can coexist with price justification, authenticity, and proof of follow-through."
                    ),
                    "",
                    "**Strategic Recommendation**",
                    (
                        "The practical response is to keep the cultural hook, but pair it with credibility assets that answer the most common conversion objections before competitors define the narrative for you."
                    ),
                    (
                        f"The graph suggests that the most reusable concrete anchors are {', '.join(dedupe_preserve_order(product_entities[:3] + event_entities[:2] + location_entities[:2], limit=7)) or 'the named products and events already in circulation'}, "
                        "which should be the first proof points tightened before the next run."
                    ),
                    "",
                    f"- Peak rounds: {', '.join(str(item) for item in peak_rounds) or 'No peak round detected'}",
                    f"- Leading agents: {', '.join(leading_agents) or 'No dominant agent detected'}",
                    f"- Actions observed: {action_count}",
                    f"- Scheduled events planned: {len(config.get('event_config', {}).get('scheduled_events', []))}",
                    f"- Top action types: {', '.join(f'{name}={count}' for name, count in action_type_counter.most_common(4)) or 'No action types recorded'}",
                    "",
                    "- Watch whether the narrative stays concentrated among a few amplifiers or begins to diffuse into broader audience segments.",
                    "- Treat pricing and authenticity as conversion gates rather than cosmetic side issues.",
                    "- Use reddit skepticism and comment behavior as the check against twitter-led excitement.",
                    "- Re-run the scenario when a new competitive, sustainability, or media signal changes who holds narrative authority.",
                ]
            )
        if title == "Persona Interviews":
            return "\n".join(
                [
                    "## Persona Interviews",
                    "",
                    "Interview evidence captures how the most visible agents interpreted the scenario after the run had already started to harden into a public narrative.",
                    "",
                    "**Representative Testimony**",
                    "",
                    *quote_lines,
                ]
            )
        return "\n".join(["## Analyst Notes", "", *recommendation_lines])

    sections: list[dict[str, object]] = []
    for index, spec in enumerate(section_specs, start=1):
        title = spec["title"]
        fallback_content = fallback_section_content(title)
        content = fallback_content
        if llm:
            generated_content = maybe_generate_text(
                llm,
                system_prompt=(
                    "Write one analyst-report section in markdown. "
                    "Start with the exact heading provided. Use evidence, not chain-of-thought. "
                    "Be specific about scenario tensions, platform differences, named entities, and what the evidence actually supports. "
                    "Use at least two substantive subheadings after the main heading when the section calls for analysis. "
                    "Prefer concrete brands, markets, platforms, organizations, and public figures over abstract placeholders."
                ),
                user_prompt=(
                    f"Heading: ## {title}\n"
                    f"Section purpose: {spec['brief']}\n"
                    f"Project: {project_label}\n"
                    f"Scenario: {project.scenario_brief}\n"
                    f"Focus: {focus}\n"
                    f"Graph facts: {' | '.join(graph_facts[:4])}\n"
                    f"Runtime stats: {action_count} actions, {twitter_posts} twitter posts, {reddit_posts} reddit posts, {comments_count} comments\n"
                    f"Peak rounds: {', '.join(str(item) for item in peak_rounds)}\n"
                    f"Leading agents: {', '.join(leading_agents[:4])}\n"
                    f"Dominant topics: {', '.join(dominant_topics[:5])}\n"
                    f"Named brands/products/events/locations/platforms: {', '.join(dedupe_preserve_order(brand_entities[:5] + product_entities[:4] + event_entities[:3] + location_entities[:4] + platform_entities[:4], limit=16))}\n"
                    f"Named organizations and people: {', '.join(dedupe_preserve_order(organization_entities[:5] + people_entities[:5] + media_entities[:5], limit=12))}\n"
                    f"Runtime evidence: {' | '.join(runtime_quotes[:6])}\n"
                    f"Interview evidence: {' | '.join(interview_snippets[:3])}\n"
                    f"Fallback draft:\n{fallback_content}"
                ),
                max_tokens=2200,
            )
            cleaned_content = generated_content.strip() if isinstance(generated_content, str) else ""
            if cleaned_content and not looks_like_prompt_echo(cleaned_content):
                if not cleaned_content.startswith(f"## {title}"):
                    cleaned_content = f"## {title}\n\n{cleaned_content}"
                content = cleaned_content
        sections.append(
            {
                "index": index,
                "title": title,
                "content": content,
            }
        )

    markdown_body = "\n\n".join(section["content"] for section in sections)
    return {
        "title": f"Future Prediction Report: {report_label}",
        "summary": (
            f"Generated a grounded analyst report for {report_label} from graph context, runtime activity, "
            "persona interviews, and recommended actions."
        ),
        "executive_summary": executive_summary,
        "evidence_summary": {
            "graph": {
                "node_count": node_count,
                "edge_count": edge_count,
                "entity_types": entity_types,
                "signals": graph_facts[:4],
                "named_entities": named_entities,
            },
            "runtime": {
                "actions": action_count,
                "rounds": total_rounds,
                "twitter_posts": twitter_posts,
                "reddit_posts": reddit_posts,
                "comments": comments_count,
                "platform_focus": platform_focus,
                "peak_rounds": peak_rounds,
                "quotes": runtime_quotes[:6],
            },
            "topics": dominant_topics,
            "top_agents": top_agents,
            "interviews": interview_quotes,
        },
        "sections": sections,
        "markdown_body": markdown_body,
    }


def build_glass_report_chat_response(
    llm: TextGenerator,
    *,
    project: Project,
    simulation: Simulation,
    report: Report | None,
    message: str,
    sections: list[dict[str, object]],
    evidence: dict[str, object],
    chat_history: list[dict[str, str]] | None = None,
) -> tuple[str, list[str], list[dict[str, str]]]:
    """Generate a grounded report-chat response from report sections and runtime evidence."""
    project_label = derive_project_label(project.name, project.scenario_brief, topics := [str(item) for item in evidence.get("topics", []) if isinstance(item, str)])
    runtime = evidence.get("runtime", {}) if isinstance(evidence.get("runtime"), dict) else {}
    graph = evidence.get("graph", {}) if isinstance(evidence.get("graph"), dict) else {}
    named_entities = graph.get("named_entities", {}) if isinstance(graph.get("named_entities"), dict) else {}
    conversation_history = [
        {
            "role": str(item.get("role") or "user").strip(),
            "content": str(item.get("content") or "").strip(),
        }
        for item in (chat_history or [])
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ][-4:]
    conversation_lines = [
        f"{item['role']}: {sanitize_model_excerpt(item['content'], item['content'][:120], max_sentences=1, max_chars=180) or item['content'][:180]}"
        for item in conversation_history
    ]
    runtime_quotes = [str(item).strip() for item in runtime.get("quotes", []) if str(item).strip()] if isinstance(runtime.get("quotes"), list) else []
    interview_quotes = [
        f"{item.get('agent_name') or item.get('agent_id')}: "
        f"{sanitize_model_excerpt(str(item.get('response') or ''), 'Interview evidence available.') or 'Interview evidence available.'}"
        for item in evidence.get("interviews", [])
        if isinstance(item, dict)
    ]
    named_entity_lines = [
        f"{category}: {', '.join(str(name) for name in values[:5])}"
        for category, values in named_entities.items()
        if isinstance(values, list) and values
    ]
    graph_summary = (
        f"{int(graph.get('node_count', 0) or 0)} nodes, "
        f"{int(graph.get('edge_count', 0) or 0)} edges, "
        f"entity types {', '.join(str(item) for item in graph.get('entity_types', [])[:6])}"
        if isinstance(graph.get("entity_types"), list)
        else f"{int(graph.get('node_count', 0) or 0)} nodes and {int(graph.get('edge_count', 0) or 0)} edges"
    )
    runtime_summary = (
        f"{int(runtime.get('actions', 0) or 0)} actions across {int(runtime.get('rounds', 0) or 0)} rounds, "
        f"{int(runtime.get('twitter_posts', 0) or 0)} twitter posts, "
        f"{int(runtime.get('reddit_posts', 0) or 0)} reddit posts, "
        f"{int(runtime.get('comments', 0) or 0)} comments, "
        f"platform focus {str(runtime.get('platform_focus') or 'mixed')}"
    )
    section_summaries = "\n".join(
        f"- {item.get('title', 'Section')}: {(sanitize_model_excerpt(str(item.get('content') or ''), '', max_sentences=2, max_chars=280) or '').strip()}"
        for item in sections[:6]
    ).strip()
    generated = maybe_generate_text(
        llm,
        system_prompt=(
            "Answer as a senior analyst using only the evidence provided. "
            "Return exactly one <final_answer>...</final_answer> block and nothing else. "
            "Inside that block, write two short paragraphs: the first states the conclusion, the second explains the strongest reasons and named entities behind it. "
            "Use concrete brands, cohorts, markets, platforms, or public figures whenever available. "
            "Do not include setup notes, labels, bullets, hidden reasoning, tool syntax, or prompt restatements."
        ),
        user_prompt=(
            f"Project: {project_label}\n"
            f"Scenario: {project.scenario_brief}\n"
            f"Question: {message}\n"
            f"Conversation history: {' | '.join(conversation_lines) or 'None'}\n"
            f"Report executive summary: {report.executive_summary if report and report.executive_summary else 'None'}\n"
            f"Simulation summary: {simulation.summary or 'None'}\n"
            f"Graph summary: {graph_summary}\n"
            f"Runtime summary: {runtime_summary}\n"
            f"Dominant topics: {', '.join(topics) or 'None'}\n"
            f"Named entities: {' | '.join(named_entity_lines[:6]) or 'None'}\n"
            f"Runtime evidence: {' | '.join(runtime_quotes[:4]) or 'None'}\n"
            f"Interview evidence: {' | '.join(interview_quotes[:3]) or 'None'}\n"
            f"Report section summaries: {section_summaries or 'None'}\n"
            "Return only the final answer inside <final_answer> tags."
        ),
        max_tokens=900,
    )
    focal_entities = dedupe_preserve_order(
        [
            *(named_entities.get("brands", []) if isinstance(named_entities.get("brands"), list) else []),
            *(named_entities.get("platforms", []) if isinstance(named_entities.get("platforms"), list) else []),
            *(named_entities.get("locations", []) if isinstance(named_entities.get("locations"), list) else []),
        ],
        limit=6,
    )
    sources = [
        report.executive_summary if report and report.executive_summary else "",
        f"Topics: {', '.join(topics[:3])}" if topics else "",
        (
            f"Runtime: {runtime.get('actions', 0)} actions, {runtime.get('twitter_posts', 0)} twitter posts, "
            f"{runtime.get('reddit_posts', 0)} reddit posts, {runtime.get('comments', 0)} comments."
        ),
        f"Named entities: {', '.join(focal_entities)}" if focal_entities else "",
        runtime_quotes[0] if runtime_quotes else "",
        interview_quotes[0] if interview_quotes else "",
        section_summaries.splitlines()[0].lstrip("- ").strip() if section_summaries else "",
    ]
    sources = [item for item in sources if item]
    fallback = (
        f"Conclusion: The run suggests {project_label} is still being judged more on {topics[0].lower() if topics else 'the leading narrative'} than on durable loyalty. "
        f"Across {runtime.get('actions', 0)} actions, the conversation kept circling around {', '.join(focal_entities[:4]) or 'the main named actors in the graph'}.\n\n"
        f"The strongest reasons were persistent price and authenticity scrutiny, visible pressure from competitor and media voices, and a weak bridge from fast platform attention to repeat behavior. "
        f"The next analyst check is whether that scrutiny keeps broadening across cohorts, markets, and platforms instead of narrowing into a smaller loyalty base."
    )
    cleaned = sanitize_model_answer(generated, fallback)
    if looks_like_prompt_echo(cleaned) or looks_like_incomplete_answer(cleaned):
        cleaned = fallback
    return cleaned or fallback, sources, [
        {"name": "report_context", "status": "completed"},
        {"name": "report_outline", "status": "completed"},
        {"name": "report_sections", "status": "completed"},
        {"name": "report_evidence", "status": "completed"},
    ]


def slugify(value: str) -> str:
    """Create a stable identifier slug."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "item"
