import { useRef, useEffect, useCallback, useState } from 'react';
import * as d3 from 'd3';
import type { GraphData, GraphNode, GraphEdge } from '../types';
import css from '../styles/graph-panel.module.css';

/* -- D3-compatible types ---------------------------------------- */

interface SimNode extends d3.SimulationNodeDatum {
  uuid: string;
  name: string;
  label: string;
  summary?: string;
  attributes?: Record<string, unknown>;
  x: number;
  y: number;
  fx?: number | null;
  fy?: number | null;
  edgeCount: number;
  isPrimaryLabel: boolean;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  uuid: string;
  relation_type: string;
  fact?: string;
  weight?: number;
  curvature: number;
  isSelfLoop: boolean;
  pairTotal: number;
  selfLoopCount?: number;
  selfLoopEdges?: GraphEdge[];
}

interface NodePosition {
  x: number;
  y: number;
}

/* -- Color helpers ---------------------------------------------- */

const NODE_HUES = [195, 265, 35, 140, 330, 70, 210, 300, 15, 170];

function createNodeColorScale(): (label: string) => string {
  const cache = new Map<string, string>();
  let idx = 0;
  return (label: string) => {
    let c = cache.get(label);
    if (!c) {
      const h = NODE_HUES[idx % NODE_HUES.length]!;
      c = `hsl(${h}, 72%, 64%)`;
      cache.set(label, c);
      idx++;
    }
    return c;
  };
}

const EDGE_STROKE = 'rgba(208, 227, 255, 0.84)';
const EDGE_STROKE_SELECTED = 'rgba(126, 231, 255, 0.98)';
const EDGE_MARKER_FILL = 'rgba(226, 238, 255, 0.94)';
const EDGE_LABEL_TEXT = 'rgba(241, 247, 255, 0.96)';
const EDGE_LABEL_BORDER = 'rgba(150, 185, 255, 0.24)';
const EDGE_LABEL_FILL = 'rgba(12, 20, 36, 0.84)';
const NODE_LABEL_COLOR = 'rgba(246, 250, 255, 0.98)';
const NODE_LABEL_HALO = 'rgba(4, 9, 20, 0.82)';
const LABEL_FONT_SIZE = 11;
const PRIMARY_LABEL_MIN = 14;
const PRIMARY_LABEL_SHARE = 0.34;
const ALL_LABEL_ZOOM = 1.12;
const PRIMARY_LABEL_ZOOM = 0.74;

/* -- Constants -------------------------------------------------- */

const MIN_R = 8;
const MAX_R = 16;
const LABEL_ZOOM = 0.75;

function baseEdgeOpacity(d: Pick<SimLink, 'isSelfLoop'>): number {
  return d.isSelfLoop ? 0.62 : 0.82;
}

function baseEdgeWidth(d: Pick<SimLink, 'isSelfLoop'>): number {
  return d.isSelfLoop ? 1.45 : 1.85;
}

function baseEdgeStroke(_d: Pick<SimLink, 'isSelfLoop'>): string {
  return EDGE_STROKE;
}

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function seededOffset(key: string, spread: number): number {
  return ((stableHash(key) % 10000) / 10000 - 0.5) * spread;
}

function seededCenterPosition(
  key: string,
  width: number,
  height: number,
  spread: number,
): NodePosition {
  const angle = ((stableHash(`${key}:angle`) % 10000) / 10000) * Math.PI * 2;
  const radius = spread * (0.2 + ((stableHash(`${key}:radius`) % 10000) / 10000) * 0.8);
  return {
    x: width / 2 + Math.cos(angle) * radius,
    y: height / 2 + Math.sin(angle) * radius,
  };
}

function makeGraphSignature(graphData: { nodes: GraphNode[]; edges: GraphEdge[] }): string {
  const nodeIds = graphData.nodes.map((node) => node.uuid).sort().join('|');
  const edgeIds = graphData.edges
    .map((edge) => edge.uuid || `${edge.source_uuid}:${edge.target_uuid}:${edge.relation_type}:${edge.fact ?? ''}`)
    .sort()
    .join('|');
  return `${graphData.nodes.length}:${graphData.edges.length}:${nodeIds}:${edgeIds}`;
}

/* -- Props ------------------------------------------------------ */

interface GraphPanelProps {
  graphData: GraphData | null;
  loading: boolean;
  schemaMode?: boolean;
  graphMode?: 'full' | 'focused';
  onGraphModeChange?: (mode: 'full' | 'focused') => void;
  onNodeSelect?: (node: GraphNode | null) => void;
  emptyTitle?: string;
  emptyHint?: string;
}

/* -- Detail types ----------------------------------------------- */

type DetailData =
  | {
      kind: 'node';
      node: SimNode;
      connections: { relation: string; target: string; direction: 'in' | 'out' }[];
    }
  | { kind: 'edge'; edge: SimLink };

/* ================================================================
   Component
   ================================================================ */

export default function GraphPanel({
  graphData,
  loading,
  schemaMode = false,
  graphMode = 'full',
  onGraphModeChange,
  onNodeSelect,
  emptyTitle = 'Graph will appear here',
  emptyHint = 'Upload documents & build to visualize',
}: GraphPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const simRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const zoomTransformRef = useRef(d3.zoomIdentity);
  const zoomLevelRef = useRef(1);
  const showLabelsRef = useRef(true);
  const positionCacheRef = useRef<Map<string, NodePosition>>(new Map());
  const graphBoundsRef = useRef<{ minX: number; minY: number; maxX: number; maxY: number } | null>(null);
  const dataSignatureRef = useRef<string | null>(null);
  const hasAutoFittedRef = useRef(false);
  const previewFitTimerRef = useRef<number | null>(null);
  const renderFrameRef = useRef<number | null>(null);
  const edgeLabelPositionUpdaterRef = useRef<(() => void) | null>(null);
  const tooltipFrameRef = useRef<number | null>(null);
  const motionStopTimerRef = useRef<number | null>(null);
  const isDraggingNodeRef = useRef(false);
  const suppressNodeClickRef = useRef(false);
  const dragResetTimerRef = useRef<number | null>(null);

  const [tooltipNode, setTooltipNode] = useState<SimNode | null>(null);
  const [detail, setDetail] = useState<DetailData | null>(null);
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [legendItems, setLegendItems] = useState<
    { label: string; color: string }[]
  >([]);

  useEffect(() => {
    showLabelsRef.current = showEdgeLabels;
  }, [showEdgeLabels]);

  const moveTooltip = useCallback((x: number, y: number) => {
    if (tooltipFrameRef.current !== null) {
      window.cancelAnimationFrame(tooltipFrameRef.current);
    }

    tooltipFrameRef.current = window.requestAnimationFrame(() => {
      tooltipFrameRef.current = null;
      if (!tooltipRef.current) return;
      tooltipRef.current.style.left = `${x}px`;
      tooltipRef.current.style.top = `${y}px`;
    });
  }, []);

  const hideTooltip = useCallback(() => {
    if (tooltipFrameRef.current !== null) {
      window.cancelAnimationFrame(tooltipFrameRef.current);
      tooltipFrameRef.current = null;
    }
    if (tooltipRef.current) {
      tooltipRef.current.style.left = '-9999px';
      tooltipRef.current.style.top = '-9999px';
    }
  }, []);

  const fitCurrentGraph = useCallback((duration = 500) => {
    const svg = svgRef.current;
    const zoom = zoomRef.current;
    const container = containerRef.current;
    const bounds = graphBoundsRef.current;
    if (!svg || !zoom || !container || !bounds) return;

    const { width, height } = container.getBoundingClientRect();
    const graphWidth = Math.max(1, bounds.maxX - bounds.minX);
    const graphHeight = Math.max(1, bounds.maxY - bounds.minY);
    const pad = 72;
    const scale = Math.min(
      (width - pad * 2) / graphWidth,
      (height - pad * 2) / graphHeight,
      2.2,
    );
    const tx = width / 2 - ((bounds.minX + bounds.maxX) / 2) * scale;
    const ty = height / 2 - ((bounds.minY + bounds.maxY) / 2) * scale;
    const transform = d3.zoomIdentity.translate(tx, ty).scale(scale);
    const root = d3.select(svg);

    if (duration > 0) {
      root.transition().duration(duration).call(zoom.transform, transform);
    } else {
      root.call(zoom.transform, transform);
    }
  }, []);

  /* -- Build / rebuild the D3 graph ----------------------------- */

  const build = useCallback(() => {
    const svg = svgRef.current;
    const container = containerRef.current;
    if (!svg || !container) return;

    simRef.current?.stop();
    if (previewFitTimerRef.current !== null) {
      window.clearTimeout(previewFitTimerRef.current);
      previewFitTimerRef.current = null;
    }
    if (motionStopTimerRef.current !== null) {
      window.clearTimeout(motionStopTimerRef.current);
      motionStopTimerRef.current = null;
    }
    if (dragResetTimerRef.current !== null) {
      window.clearTimeout(dragResetTimerRef.current);
      dragResetTimerRef.current = null;
    }
    if (renderFrameRef.current !== null) {
      window.cancelAnimationFrame(renderFrameRef.current);
      renderFrameRef.current = null;
    }

    if (!graphData || graphData.nodes.length === 0) {
      d3.select(svg).selectAll('*').remove();
      dataSignatureRef.current = null;
      graphBoundsRef.current = null;
      edgeLabelPositionUpdaterRef.current = null;
      hasAutoFittedRef.current = false;
      hideTooltip();
      setLegendItems([]);
      return;
    }

    const { width, height } = container.getBoundingClientRect();
    if (width === 0 || height === 0) return;
    const buildSignature = `${schemaMode ? 'schema' : 'graph'}:${width}x${height}:${makeGraphSignature(graphData)}`;
    if (dataSignatureRef.current === buildSignature) return;
    dataSignatureRef.current = buildSignature;
    const cachedNodeCount = graphData.nodes.filter((node) => positionCacheRef.current.has(node.uuid)).length;
    if (cachedNodeCount === 0) {
      hasAutoFittedRef.current = false;
      zoomTransformRef.current = d3.zoomIdentity;
      zoomLevelRef.current = 1;
    }

    const nodeColor = createNodeColorScale();
    const labelNames = [...new Set(graphData.nodes.map((node) => node.label))].sort((a, b) =>
      a.localeCompare(b),
    );

    /* -- Prepare nodes -- */

    const edgeCounts = new Map<string, number>();
    for (const e of graphData.edges) {
      edgeCounts.set(e.source_uuid, (edgeCounts.get(e.source_uuid) ?? 0) + 1);
      edgeCounts.set(e.target_uuid, (edgeCounts.get(e.target_uuid) ?? 0) + 1);
    }
    const maxEdges = Math.max(1, ...edgeCounts.values());
    const rScale = d3.scaleSqrt().domain([0, maxEdges]).range([MIN_R, MAX_R]);

    const uncachedNodeIds = new Set<string>();
    const nodes: SimNode[] = graphData.nodes.map((n) => {
      const cached = positionCacheRef.current.get(n.uuid);
      const seeded = {
        x: width / 2 + seededOffset(`${n.uuid}:seed-x`, Math.min(width, height) * 0.18),
        y: height / 2 + seededOffset(`${n.uuid}:seed-y`, Math.min(width, height) * 0.18),
      };
      if (!cached) uncachedNodeIds.add(n.uuid);
      return {
        uuid: n.uuid,
        name: n.name,
        label: n.label,
        summary: n.summary,
        attributes: n.attributes,
        x: cached?.x ?? seeded.x,
        y: cached?.y ?? seeded.y,
        edgeCount: edgeCounts.get(n.uuid) ?? 0,
        isPrimaryLabel: false,
      };
    });

    const primaryLabelIds = new Set(
      [...nodes]
        .sort((a, b) => b.edgeCount - a.edgeCount || a.name.localeCompare(b.name))
        .slice(
          0,
          Math.min(
            nodes.length,
            Math.max(PRIMARY_LABEL_MIN, Math.round(nodes.length * PRIMARY_LABEL_SHARE)),
          ),
        )
        .map((node) => node.uuid),
    );
    nodes.forEach((node) => {
      node.isPrimaryLabel = primaryLabelIds.has(node.uuid);
    });

    const nodeMap = new Map(nodes.map((n) => [n.uuid, n]));
    const nextLegendItems = labelNames.map((label) => ({ label, color: nodeColor(label) }));
    setLegendItems((prev) => {
      if (
        prev.length === nextLegendItems.length &&
        prev.every((item, index) => item.label === nextLegendItems[index]?.label && item.color === nextLegendItems[index]?.color)
      ) {
        return prev;
      }
      return nextLegendItems;
    });

    /* -- Prepare links with curvature -- */

    const pairKey = (a: string, b: string) =>
      a < b ? `${a}|${b}` : `${b}|${a}`;
    const pairEdges = new Map<string, string[]>();
    const selfLoopGroups = new Map<string, GraphEdge[]>();
    const links: SimLink[] = [];
    for (const e of graphData.edges) {
      if (!nodeMap.has(e.source_uuid) || !nodeMap.has(e.target_uuid)) continue;
      if (e.source_uuid === e.target_uuid) {
        const group = selfLoopGroups.get(e.source_uuid) ?? [];
        group.push(e);
        selfLoopGroups.set(e.source_uuid, group);
        continue;
      }
      const key = pairKey(e.source_uuid, e.target_uuid);
      if (!pairEdges.has(key)) pairEdges.set(key, []);
      pairEdges.get(key)!.push(e.uuid);
      links.push({
        source: nodeMap.get(e.source_uuid)!,
        target: nodeMap.get(e.target_uuid)!,
        uuid: e.uuid,
        relation_type: e.relation_type,
        fact: e.fact,
        weight: e.weight,
        curvature: 0,
        isSelfLoop: false,
        pairTotal: 1,
      });
    }

    for (const [nodeId, groupedEdges] of selfLoopGroups) {
      const node = nodeMap.get(nodeId);
      if (!node) continue;
      links.push({
        source: node,
        target: node,
        uuid: `self_${nodeId}`,
        relation_type: `Self Relations (${groupedEdges.length})`,
        fact:
          groupedEdges.length === 1
            ? groupedEdges[0]?.fact
            : `${groupedEdges.length} self relationships grouped for display.`,
        weight: 1,
        curvature: 0,
        isSelfLoop: true,
        pairTotal: groupedEdges.length,
        selfLoopCount: groupedEdges.length,
        selfLoopEdges: groupedEdges,
      });
    }

    const linkMap = new Map(links.map((l) => [l.uuid, l]));
    for (const [, uuids] of pairEdges) {
      const n = uuids.length;
      if (n === 1) {
        const single = linkMap.get(uuids[0]!);
        if (single) single.pairTotal = 1;
        continue;
      }
      const range = Math.min(1.2, 0.6 + n * 0.15);
      for (let i = 0; i < n; i++) {
        const link = linkMap.get(uuids[i]!);
        if (!link) continue;
        link.curvature = (i / (n - 1) - 0.5) * range * 2;
        link.pairTotal = n;
      }
    }

    nodes.forEach((node) => {
      if (!uncachedNodeIds.has(node.uuid)) return;
      const seeded = seededCenterPosition(
        node.uuid,
        width,
        height,
        schemaMode ? Math.min(width, height) * 0.14 : Math.min(width, height) * 0.22,
      );
      node.x = seeded.x;
      node.y = seeded.y;
    });

    for (const node of nodes) {
      if (!uncachedNodeIds.has(node.uuid)) continue;

      const cachedNeighbors = links.flatMap((link) => {
        const source = link.source as SimNode;
        const target = link.target as SimNode;
        if (source.uuid === node.uuid && positionCacheRef.current.has(target.uuid)) return [target];
        if (target.uuid === node.uuid && positionCacheRef.current.has(source.uuid)) return [source];
        return [];
      });
      if (cachedNeighbors.length === 0) continue;

      const avgX =
        cachedNeighbors.reduce((sum, item) => sum + item.x, 0) / cachedNeighbors.length;
      const avgY =
        cachedNeighbors.reduce((sum, item) => sum + item.y, 0) / cachedNeighbors.length;
      node.x = avgX + seededOffset(`${node.uuid}:neighbor:x`, 40);
      node.y = avgY + seededOffset(`${node.uuid}:neighbor:y`, 40);
    }

    /* -- SVG setup -- */

    const root = d3.select(svg);
    root.selectAll('*').remove();
    root.attr('viewBox', `0 0 ${width} ${height}`);

    const defs = root.append('defs');

    defs
      .append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -4 8 8')
      .attr('refX', 17)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-3L7,0L0,3')
      .attr('fill', EDGE_MARKER_FILL);

    const g = root.append('g');
    const shouldDisplayEdgeLabels = () =>
      showLabelsRef.current && zoomLevelRef.current >= LABEL_ZOOM;
    const nodeLabelOpacity = (node: SimNode) => {
      if (zoomLevelRef.current >= ALL_LABEL_ZOOM) return 0.96;
      if (node.isPrimaryLabel) {
        return zoomLevelRef.current >= PRIMARY_LABEL_ZOOM ? 0.94 : 0.78;
      }
      if (nodes.length <= 18) return 0.9;
      return 0;
    };

    /* -- Path helpers -- */

    function edgePath(d: SimLink): string {
      const s = d.source as SimNode;
      const t = d.target as SimNode;

      if (d.isSelfLoop) {
        const loopRadius = 28 + Math.min(18, (d.selfLoopCount ?? 1) * 2);
        const x1 = s.x + 10;
        const y1 = s.y - 5;
        const x2 = s.x + 10;
        const y2 = s.y + 5;
        return `M ${x1} ${y1} A ${loopRadius} ${loopRadius} 0 1 1 ${x2} ${y2}`;
      }

      if (d.curvature === 0) {
        return `M ${s.x} ${s.y} L ${t.x} ${t.y}`;
      }

      const dx = t.x - s.x;
      const dy = t.y - s.y;
      const mx = (s.x + t.x) / 2;
      const my = (s.y + t.y) / 2;
      const rev = s.uuid > t.uuid;
      const c = rev ? -d.curvature : d.curvature;
      return `M ${s.x} ${s.y} Q ${mx - dy * c} ${my + dx * c} ${t.x} ${t.y}`;
    }

    function edgeLabelPos(d: SimLink): [number, number] {
      const s = d.source as SimNode;
      const t = d.target as SimNode;

      if (d.isSelfLoop) {
        const loopRadius = 28 + Math.min(18, (d.selfLoopCount ?? 1) * 2);
        return [s.x + loopRadius + 26, s.y];
      }

      const mx = (s.x + t.x) / 2;
      const my = (s.y + t.y) / 2;
      if (d.curvature === 0) return [mx, my];

      const dx = t.x - s.x;
      const dy = t.y - s.y;
      const rev = s.uuid > t.uuid;
      const c = rev ? -d.curvature : d.curvature;
      const cpx = mx - dy * c;
      const cpy = my + dx * c;
      return [
        0.25 * s.x + 0.5 * cpx + 0.25 * t.x,
        0.25 * s.y + 0.5 * cpy + 0.25 * t.y,
      ];
    }

    /* -- Draw edges -- */

    const linkSel = g
      .append('g')
      .attr('class', 'links')
      .selectAll<SVGPathElement, SimLink>('path')
      .data(links)
      .join('path')
      .attr('fill', 'none')
      .attr('stroke', baseEdgeStroke)
      .attr('stroke-opacity', baseEdgeOpacity)
      .attr('stroke-width', baseEdgeWidth)
      .attr('stroke-linecap', 'round')
      .attr('stroke-dasharray', (d) => (d.isSelfLoop ? '4.5 4.5' : ''))
      .attr('marker-end', (d) => (d.isSelfLoop ? '' : 'url(#arrow)'))
      .style('cursor', 'pointer')
      .on('click', (_ev: MouseEvent, d: SimLink) => {
        _ev.stopPropagation();
        setDetail({ kind: 'edge', edge: d });
        linkSel
          .attr('stroke', (l) => (l.uuid === d.uuid ? EDGE_STROKE_SELECTED : baseEdgeStroke(l)))
          .attr('stroke-opacity', (l) => (l.uuid === d.uuid ? 1 : 0.12))
          .attr('stroke-width', (l) => (l.uuid === d.uuid ? 2.8 : 1.2));
        nodeGrp.select('.node-circle').attr('opacity', 1);
      });

    /* -- Edge labels -- */

    const edgeLabelGrp = g
      .append('g')
      .attr('class', 'edge-labels')
      .selectAll<SVGGElement, SimLink>('g')
      .data(links)
      .join('g')
      .attr('pointer-events', 'none');

    edgeLabelGrp
      .append('rect')
      .attr('rx', 3)
      .attr('fill', EDGE_LABEL_FILL)
      .attr('stroke', EDGE_LABEL_BORDER)
      .attr('stroke-width', 0.5)
      .attr('stroke-opacity', 1);

    edgeLabelGrp
      .append('text')
      .text((d) => (d.isSelfLoop ? `Self x${d.selfLoopCount ?? 1}` : d.relation_type.replace(/_/g, ' ')))
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'central')
      .attr('font-size', 9)
      .attr('font-weight', 500)
      .attr('fill', EDGE_LABEL_TEXT)
      .attr('letter-spacing', '0.03em');

    edgeLabelGrp.each(function () {
      const grp = d3.select(this);
      const txt = grp.select('text').node() as SVGTextElement | null;
      if (!txt) return;
      const bb = txt.getBBox();
      grp
        .select('rect')
        .attr('x', bb.x - 4)
        .attr('y', bb.y - 2)
        .attr('width', bb.width + 8)
        .attr('height', bb.height + 4);
    });

    edgeLabelGrp.attr(
      'opacity',
      shouldDisplayEdgeLabels() ? Math.min(1, 0.75 + zoomLevelRef.current * 0.08) : 0,
    );

    /* -- Draw nodes -- */

    const nodeGrp = g
      .append('g')
      .attr('class', 'nodes')
      .selectAll<SVGGElement, SimNode>('g')
      .data(nodes)
      .join('g')
      .style('cursor', 'pointer');

    const reheatSimulation = (alpha = 0.14, duration = 900) => {
      if (motionStopTimerRef.current !== null) {
        window.clearTimeout(motionStopTimerRef.current);
      }
      simulation.alpha(Math.max(simulation.alpha(), alpha)).restart();
      motionStopTimerRef.current = window.setTimeout(() => {
        simulation.stop();
        motionStopTimerRef.current = null;
      }, duration);
    };

    nodeGrp
      .append('circle')
      .attr('r', (d) => rScale(d.edgeCount) + 4)
      .attr('fill', (d) => nodeColor(d.label))
      .attr('fill-opacity', 0.14)
      .attr('stroke', 'none');

    nodeGrp
      .append('circle')
      .attr('class', 'node-circle')
      .attr('r', (d) => rScale(d.edgeCount))
      .attr('fill', (d) => nodeColor(d.label))
      .attr('stroke', 'rgba(255,255,255,0.92)')
      .attr('stroke-width', 2.25);

    const nodeLblSel = nodeGrp
      .append('text')
      .text((d) => (d.name.length > 18 ? `${d.name.slice(0, 17)}...` : d.name))
      .attr('dx', (d) => rScale(d.edgeCount) + 8)
      .attr('dy', 4)
      .attr('font-size', LABEL_FONT_SIZE)
      .attr('font-weight', 500)
      .attr('stroke', NODE_LABEL_HALO)
      .attr('stroke-width', 3)
      .attr('paint-order', 'stroke')
      .attr('fill', NODE_LABEL_COLOR)
      .attr('pointer-events', 'none')
      .attr('opacity', (d) => nodeLabelOpacity(d));

    /* -- Zoom -- */

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event: d3.D3ZoomEvent<SVGSVGElement, unknown>) => {
        g.attr('transform', event.transform.toString());
        zoomTransformRef.current = event.transform;
        zoomLevelRef.current = event.transform.k;
        nodeLblSel.attr('opacity', (d) => nodeLabelOpacity(d));
        edgeLabelGrp.attr(
          'opacity',
          shouldDisplayEdgeLabels() ? Math.min(1, 0.75 + zoomLevelRef.current * 0.08) : 0,
        );
      });

    root.call(zoom);
    zoomRef.current = zoom;
    root.call(zoom.transform, zoomTransformRef.current);

    /* -- Drag -- */

    let dragOrigin: { x: number; y: number } | null = null;

    nodeGrp.call(
      d3
        .drag<SVGGElement, SimNode>()
        .on('start', (event) => {
          if (dragResetTimerRef.current !== null) {
            window.clearTimeout(dragResetTimerRef.current);
            dragResetTimerRef.current = null;
          }
          dragOrigin = { x: event.x, y: event.y };
          isDraggingNodeRef.current = true;
          suppressNodeClickRef.current = false;
          setTooltipNode(null);
          hideTooltip();
          event.subject.fx = event.subject.x;
          event.subject.fy = event.subject.y;
        })
        .on('drag', (event) => {
          if (dragOrigin) {
            const dx = event.x - dragOrigin.x;
            const dy = event.y - dragOrigin.y;
            if (Math.sqrt(dx * dx + dy * dy) >= 3) {
              suppressNodeClickRef.current = true;
            }
          }
          setTooltipNode(null);
          hideTooltip();
          reheatSimulation(0.18, 1100);
          event.subject.x = event.x;
          event.subject.y = event.y;
          event.subject.fx = event.x;
          event.subject.fy = event.y;
          renderFrame();
        })
        .on('end', (event) => {
          if (dragOrigin) {
            const dx = event.x - dragOrigin.x;
            const dy = event.y - dragOrigin.y;
            if (Math.sqrt(dx * dx + dy * dy) < 3) {
              event.subject.fx = null;
              event.subject.fy = null;
            }
          }
          dragOrigin = null;
          positionCacheRef.current.set(event.subject.uuid, {
            x: event.subject.x,
            y: event.subject.y,
          });
          dragResetTimerRef.current = window.setTimeout(() => {
            isDraggingNodeRef.current = false;
            suppressNodeClickRef.current = false;
            dragResetTimerRef.current = null;
          }, suppressNodeClickRef.current ? 140 : 0);
          renderFrame();
        }),
    );

    /* -- Node interactions -- */

    nodeGrp
      .on('mouseenter', (event: MouseEvent, d: SimNode) => {
        if (isDraggingNodeRef.current) return;
        const rect = container.getBoundingClientRect();
        setTooltipNode(d);
        moveTooltip(event.clientX - rect.left + 14, event.clientY - rect.top - 10);
        d3.select(event.currentTarget as SVGGElement)
          .select('.node-circle')
          .transition()
          .duration(140)
          .attr('stroke', 'rgba(126, 231, 255, 0.96)')
          .attr('stroke-width', 3.2);
      })
      .on('mousemove', (event: MouseEvent, d: SimNode) => {
        void d;
        if (isDraggingNodeRef.current) return;
        const rect = container.getBoundingClientRect();
        moveTooltip(event.clientX - rect.left + 14, event.clientY - rect.top - 10);
      })
      .on('mouseleave', (event: MouseEvent) => {
        if (isDraggingNodeRef.current) return;
        setTooltipNode(null);
        hideTooltip();
        d3.select(event.currentTarget as SVGGElement)
          .select('.node-circle')
          .transition()
          .duration(140)
          .attr('stroke', 'rgba(255,255,255,0.92)')
          .attr('stroke-width', 2.25);
      })
      .on('click', (_ev: MouseEvent, d: SimNode) => {
        if (isDraggingNodeRef.current || suppressNodeClickRef.current) {
          suppressNodeClickRef.current = false;
          return;
        }
        _ev.stopPropagation();
        reheatSimulation(0.16, 1000);

        const conns = links
          .filter(
            (l) =>
              (l.source as SimNode).uuid === d.uuid ||
              (l.target as SimNode).uuid === d.uuid,
          )
          .map((l) => {
            const isOut = (l.source as SimNode).uuid === d.uuid;
            const other = isOut ? (l.target as SimNode) : (l.source as SimNode);
            return {
              relation: l.relation_type,
              target: other.name,
              direction: (isOut ? 'out' : 'in') as 'in' | 'out',
            };
          });

        setDetail({ kind: 'node', node: d, connections: conns });
        onNodeSelect?.(d);

        const connIds = new Set<string>([d.uuid]);
        for (const l of links) {
          const s = (l.source as SimNode).uuid;
          const t = (l.target as SimNode).uuid;
          if (s === d.uuid) connIds.add(t);
          if (t === d.uuid) connIds.add(s);
        }

        nodeGrp
          .select('.node-circle')
          .transition()
          .duration(200)
          .attr('opacity', (n: unknown) =>
            connIds.has((n as SimNode).uuid) ? 1 : 0.12,
          );
        linkSel
          .transition()
          .duration(200)
          .attr('stroke', (l) => {
            const s = (l.source as SimNode).uuid;
            const t = (l.target as SimNode).uuid;
            return s === d.uuid || t === d.uuid ? EDGE_STROKE_SELECTED : baseEdgeStroke(l);
          })
          .attr('stroke-opacity', (l) => {
            const s = (l.source as SimNode).uuid;
            const t = (l.target as SimNode).uuid;
            return s === d.uuid || t === d.uuid ? 0.98 : 0.08;
          })
          .attr('stroke-width', (l) => {
            const s = (l.source as SimNode).uuid;
            const t = (l.target as SimNode).uuid;
            return s === d.uuid || t === d.uuid ? 2.35 : 1.05;
          });
      });

    // Click background to deselect
    root.on('click', (ev: MouseEvent) => {
      if (ev.target === svg) {
        setDetail(null);
        onNodeSelect?.(null);
        nodeGrp
          .select('.node-circle')
          .transition()
          .duration(200)
          .attr('opacity', 1);
        linkSel
          .transition()
          .duration(200)
          .attr('stroke', baseEdgeStroke)
          .attr('stroke-opacity', baseEdgeOpacity)
          .attr('stroke-width', baseEdgeWidth);
      }
    });

    /* -- Force simulation -- */

    const linkDistance = schemaMode ? 160 : 150;
    const chargeStrength = schemaMode ? -440 : -400;

    const simulation = d3
      .forceSimulation<SimNode>(nodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, SimLink>(links)
          .id((d) => d.uuid)
          .distance((d) => (d.isSelfLoop ? 0 : linkDistance + (Math.max(1, d.pairTotal) - 1) * 50))
          .strength((d) => (d.isSelfLoop ? 0 : 0.42)),
      )
      .force('charge', d3.forceManyBody().strength(chargeStrength))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force(
        'collide',
        d3.forceCollide<SimNode>().radius(() => (schemaMode ? 42 : 50)),
      )
      .force('x', d3.forceX(width / 2).strength(0.05))
      .force('y', d3.forceY(height / 2).strength(0.05))
      .alpha(1)
      .alphaDecay(schemaMode ? 0.08 : 0.07)
      .velocityDecay(0.38)
      .stop();

    const updateBounds = () => {
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;

      for (const node of nodes) {
        const radius = rScale(node.edgeCount) + 10;
        const rightLabelPad = node.isPrimaryLabel ? Math.min(104, node.name.length * 6.4) : 18;
        minX = Math.min(minX, node.x - radius - 18);
        minY = Math.min(minY, node.y - radius - 16);
        maxX = Math.max(maxX, node.x + radius + rightLabelPad);
        maxY = Math.max(maxY, node.y + radius + 18);
        positionCacheRef.current.set(node.uuid, { x: node.x, y: node.y });
      }

      graphBoundsRef.current =
        Number.isFinite(minX) && Number.isFinite(minY) && Number.isFinite(maxX) && Number.isFinite(maxY)
          ? { minX, minY, maxX, maxY }
          : null;
    };

    const renderFrame = () => {
      renderFrameRef.current = null;
      updateBounds();
      linkSel.attr('d', edgePath);
      if (shouldDisplayEdgeLabels()) {
        edgeLabelGrp.attr('transform', (d) => {
          const [lx, ly] = edgeLabelPos(d);
          return `translate(${lx},${ly})`;
        });
      }
      nodeGrp.attr('transform', (d) => `translate(${d.x},${d.y})`);
    };

    edgeLabelPositionUpdaterRef.current = () => {
      edgeLabelGrp.attr('transform', (d) => {
        const [lx, ly] = edgeLabelPos(d);
        return `translate(${lx},${ly})`;
      });
    };

    simulation.on('tick', renderFrame);
    simRef.current = simulation;
    const settleTicks = Math.max(180, Math.min(480, 160 + nodes.length * 4 + links.length * 5));
    for (let tick = 0; tick < settleTicks; tick += 1) {
      simulation.tick();
    }
    renderFrame();
    if (!hasAutoFittedRef.current) {
      hasAutoFittedRef.current = true;
      fitCurrentGraph(420);
    }

    const liveNodeIds = new Set(nodes.map((node) => node.uuid));
    for (const cachedId of Array.from(positionCacheRef.current.keys())) {
      if (!liveNodeIds.has(cachedId)) {
        positionCacheRef.current.delete(cachedId);
      }
    }
  }, [fitCurrentGraph, graphData, hideTooltip, moveTooltip, onNodeSelect, schemaMode]);

  /* -- Effects -- */

  useEffect(() => {
    build();
    return () => {
      simRef.current?.stop();
      if (previewFitTimerRef.current !== null) {
        window.clearTimeout(previewFitTimerRef.current);
        previewFitTimerRef.current = null;
      }
      if (renderFrameRef.current !== null) {
        window.cancelAnimationFrame(renderFrameRef.current);
        renderFrameRef.current = null;
      }
      if (motionStopTimerRef.current !== null) {
        window.clearTimeout(motionStopTimerRef.current);
        motionStopTimerRef.current = null;
      }
      if (dragResetTimerRef.current !== null) {
        window.clearTimeout(dragResetTimerRef.current);
        dragResetTimerRef.current = null;
      }
    };
  }, [build]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => build());
    ro.observe(container);
    return () => ro.disconnect();
  }, [build]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    if (showEdgeLabels) {
      edgeLabelPositionUpdaterRef.current?.();
    }
    d3.select(svg)
      .selectAll<SVGGElement, unknown>('.edge-labels g')
      .transition()
      .duration(200)
      .attr(
        'opacity',
        showEdgeLabels && zoomLevelRef.current >= LABEL_ZOOM
          ? Math.min(1, 0.75 + zoomLevelRef.current * 0.08)
          : 0,
      );
  }, [showEdgeLabels]);

  useEffect(() => {
    return () => {
      hideTooltip();
    };
  }, [hideTooltip]);

  /* -- Fit to view -- */

  const handleFit = useCallback(() => {
    fitCurrentGraph(500);
  }, [fitCurrentGraph]);

  /* -- Close detail -- */

  const closeDetail = useCallback(() => {
    setDetail(null);
    onNodeSelect?.(null);
    const svg = svgRef.current;
    if (svg) {
      const root = d3.select(svg);
      root
        .selectAll<SVGCircleElement, SimNode>('.node-circle')
        .transition()
        .duration(200)
        .attr('opacity', 1);
      root
        .selectAll<SVGPathElement, SimLink>('.links path')
        .transition()
        .duration(200)
        .attr('stroke', baseEdgeStroke)
        .attr('stroke-opacity', baseEdgeOpacity)
        .attr('stroke-width', baseEdgeWidth);
    }
  }, [onNodeSelect]);

  /* -- Render -- */

  const hasData = graphData && graphData.nodes.length > 0;
  return (
    <div ref={containerRef} className={css.wrapper}>
      <svg ref={svgRef} className={css.svg} />

      {/* Controls */}
      {hasData && (
        <div className={css.controls}>
          {onGraphModeChange && !schemaMode && (
            <div className={css.modeSwitch}>
              <button
                className={`${css.modeBtn} ${graphMode === 'full' ? css.modeBtnActive : ''}`}
                onClick={() => onGraphModeChange('full')}
                title="Show the canonical baseline graph"
              >
                Baseline
              </button>
              <button
                className={`${css.modeBtn} ${graphMode === 'focused' ? css.modeBtnActive : ''}`}
                onClick={() => onGraphModeChange('focused')}
                title="Show a focused projection of the baseline graph"
              >
                Focus
              </button>
            </div>
          )}
          <button className={css.ctrlBtn} onClick={handleFit} title="Fit view">
            Fit
          </button>
          <button
            className={`${css.ctrlBtn} ${showEdgeLabels ? css.ctrlActive : ''}`}
            onClick={() => setShowEdgeLabels((p) => !p)}
            title="Toggle edge labels"
          >
            T
          </button>
          {schemaMode && <span className={css.schemaBadge}>SCHEMA</span>}
        </div>
      )}

      {/* Legend */}
      {legendItems.length > 0 && (
        <div className={css.legend}>
          <div className={css.legendTitle}>Entity Types</div>
          {legendItems.map((item) => (
            <div key={item.label} className={css.legendItem}>
              <span className={css.legendDot} style={{ background: item.color }} />
              <span className={css.legendLabel}>{item.label}</span>
            </div>
          ))}
        </div>
      )}

      {/* Detail panel */}
      {detail && (
        <div className={css.detailPanel}>
          <button className={css.detailClose} onClick={closeDetail}>
            x
          </button>
          {detail.kind === 'node' ? (
            <NodeDetail data={detail} />
          ) : (
            <EdgeDetail data={detail} />
          )}
        </div>
      )}

      {/* Tooltip */}
      <div
        ref={tooltipRef}
        className={`${css.tooltip} ${tooltipNode ? css.tooltipVisible : ''}`}
        style={
          tooltipNode
            ? undefined
            : { left: -9999, top: -9999 }
        }
      >
        {tooltipNode && (
          <>
            <div className={css.tooltipName}>{tooltipNode.name}</div>
            <div className={css.tooltipLabel}>{tooltipNode.label}</div>
            {tooltipNode.summary && (
              <div className={css.tooltipSummary}>{tooltipNode.summary}</div>
            )}
          </>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div className={css.loadingOverlay}>
          <div className={css.spinner} />
        </div>
      )}

      {/* Empty */}
      {!loading && !hasData && (
        <div className={css.emptyState}>
          <span className={css.emptyIcon}>{'\u2B21'}</span>
          <span className={css.emptyText}>{emptyTitle}</span>
          <span className={css.emptyHint}>{emptyHint}</span>
        </div>
      )}
    </div>
  );
}

/* ================================================================
   Detail sub-components
   ================================================================ */

function NodeDetail({ data }: { data: Extract<DetailData, { kind: 'node' }> }) {
  const { node, connections } = data;
  return (
    <div className={css.detailContent}>
      <div className={css.detailType}>ENTITY</div>
      <div className={css.detailName}>{node.name}</div>
      <span className={css.detailBadge}>{node.label}</span>
      {node.summary && <p className={css.detailSummary}>{node.summary}</p>}
      {node.attributes && Object.keys(node.attributes).length > 0 && (
        <div className={css.detailSection}>
          <div className={css.detailSectionTitle}>Attributes</div>
          {Object.entries(node.attributes).map(([k, v]) => (
            <div key={k} className={css.detailRow}>
              <span className={css.detailKey}>{k}</span>
              <span className={css.detailVal}>{String(v)}</span>
            </div>
          ))}
        </div>
      )}
      {connections.length > 0 && (
        <div className={css.detailSection}>
          <div className={css.detailSectionTitle}>
            Connections ({connections.length})
          </div>
          {connections.map((c, i) => (
            <div key={i} className={css.connectionRow}>
              <span className={css.connDir}>
                {c.direction === 'out' ? '\u2192' : '\u2190'}
              </span>
              <span className={css.connRelation}>{c.relation}</span>
              <span className={css.connTarget}>{c.target}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EdgeDetail({ data }: { data: Extract<DetailData, { kind: 'edge' }> }) {
  const { edge } = data;
  const src = edge.source as SimNode;
  const tgt = edge.target as SimNode;
  const selfLoopCount = edge.selfLoopCount ?? 1;
  const selfLoopNames = edge.selfLoopEdges
    ?.map((item) => item.relation_type.replace(/_/g, ' '))
    .filter(Boolean)
    .slice(0, 6);

  return (
    <div className={css.detailContent}>
      <div className={css.detailType}>RELATIONSHIP</div>
      <div className={css.detailName}>{edge.relation_type.replace(/_/g, ' ')}</div>
      {edge.isSelfLoop ? (
        <>
          <div className={css.edgePath}>
            <span className={css.edgeEndpoint}>{src.name}</span>
            <span className={css.edgeArrow}>loop</span>
            <span className={css.edgeEndpoint}>{selfLoopCount} relations</span>
          </div>
          {selfLoopNames && selfLoopNames.length > 0 && (
            <div className={css.detailSection}>
              <div className={css.detailSectionTitle}>Included Relations</div>
              {selfLoopNames.map((name) => (
                <div key={name} className={css.detailRow}>
                  <span className={css.detailVal}>{name}</span>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className={css.edgePath}>
          <span className={css.edgeEndpoint}>{src.name}</span>
          <span className={css.edgeArrow}>{'\u2192'}</span>
          <span className={css.edgeEndpoint}>{tgt.name}</span>
        </div>
      )}
      {edge.fact && <p className={css.detailSummary}>{edge.fact}</p>}
    </div>
  );
}
