import type { Ontology, GraphData, GraphNode, GraphEdge } from '../types';

/**
 * Convert an ontology schema into displayable GraphData.
 * Entity types become nodes; edge types (with source_targets) become edges.
 */
export function ontologyToGraph(ontology: Ontology): GraphData {
  const nodes: GraphNode[] = ontology.entity_types.map((et, i) => ({
    uuid: `ent_${et.name}`,
    name: et.name,
    label: et.name,
    group_id: i,
    summary: et.description,
    attributes: normalizeAttrs(et.attributes),
  }));

  const nameSet = new Set(nodes.map((n) => n.uuid));
  const edges: GraphEdge[] = [];
  let idx = 0;

  for (const et of ontology.edge_types) {
    const pairs: { source: string; target: string }[] = [
      ...(et.source_targets ?? []),
    ];

    // Legacy fallback: source_types x target_types
    if (
      pairs.length === 0 &&
      et.source_types?.length &&
      et.target_types?.length
    ) {
      for (const s of et.source_types)
        for (const t of et.target_types) pairs.push({ source: s, target: t });
    }

    for (const { source, target } of pairs) {
      const srcId = `ent_${source}`;
      const tgtId = `ent_${target}`;
      if (nameSet.has(srcId) && nameSet.has(tgtId)) {
        edges.push({
          uuid: `edge_${idx++}`,
          source_uuid: srcId,
          target_uuid: tgtId,
          relation_type: et.name,
          fact: et.description,
        });
      }
    }
  }

  return {
    nodes,
    edges,
    metadata: {
      node_count: nodes.length,
      edge_count: edges.length,
      entity_types: ontology.entity_types.map((e) => e.name),
      edge_types: ontology.edge_types.map((e) => e.name),
    },
  };
}

function normalizeAttrs(
  attrs?:
    | Record<string, string>
    | { name: string; type?: string; description?: string }[],
): Record<string, unknown> {
  if (!attrs) return {};
  if (Array.isArray(attrs)) {
    const out: Record<string, unknown> = {};
    for (const a of attrs) out[a.name] = a.description ?? a.type ?? '';
    return out;
  }
  return attrs;
}
