import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { graphApi, simulationApi } from '../api';
import type { RawProject } from '../api/graph';
import { useScrollReveal } from '../hooks/useScrollReveal';
import styles from '../styles/history.module.css';

/* -- Merged card data -------------------------------------- */

interface CardData {
  id: string;
  projectId: string;
  simulationId?: string;
  reportId?: string | null;
  name: string;
  requirement?: string | null;
  status: string;
  files: { filename: string }[];
  entityTypes?: string[];
  entitiesCount?: number;
  profilesCount?: number;
  currentRound?: number;
  totalRounds?: number;
  graphId?: string | null;
  hasOntology: boolean;
  createdAt: string;
}

/* -- Helpers ----------------------------------------------- */

const STATUS_META: Record<string, { label: string; cls: string }> = {
  created:              { label: 'Created',    cls: 'statusCreated' },
  ontology_generating:  { label: 'Generating', cls: 'statusGenerating' },
  ontology_generated:   { label: 'Ontology OK', cls: 'statusGenerated' },
  graph_building:       { label: 'Building',   cls: 'statusBuilding' },
  graph_completed:      { label: 'Graph OK',   cls: 'statusCompleted' },
  preparing:            { label: 'Preparing',  cls: 'statusGenerating' },
  running:              { label: 'Running',    cls: 'statusBuilding' },
  completed:            { label: 'Completed',  cls: 'statusCompleted' },
  failed:               { label: 'Failed',     cls: 'statusFailed' },
};

const FILE_EXT_COLORS: Record<string, { bg: string; fg: string }> = {
  pdf:  { bg: 'rgba(246,135,135,0.15)', fg: '#f87171' },
  md:   { bg: 'rgba(168,139,250,0.15)', fg: '#a78bfa' },
  txt:  { bg: 'rgba(156,163,175,0.15)', fg: '#9ca3af' },
  doc:  { bg: 'rgba(96,165,250,0.15)',  fg: '#60a5fa' },
  docx: { bg: 'rgba(96,165,250,0.15)',  fg: '#60a5fa' },
  csv:  { bg: 'rgba(74,222,128,0.15)',  fg: '#4ade80' },
  json: { bg: 'rgba(250,204,21,0.15)',  fg: '#facc15' },
};
const DEFAULT_EXT_COLOR = { bg: 'rgba(255,255,255,0.08)', fg: 'var(--text-muted)' };

function getExt(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot >= 0 ? filename.slice(dot + 1).toLowerCase() : '';
}

function formatId(id: string): string {
  return id.replace(/^(proj_|sim_)/, '').slice(0, 8).toUpperCase();
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch { return iso; }
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, max).trimEnd() + '...';
}

/* -- Component --------------------------------------------- */

export function HistoryDatabase() {
  const navigate = useNavigate();
  const [ref, visible] = useScrollReveal();
  const [cards, setCards] = useState<CardData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [projects, historyRes] = await Promise.allSettled([
          graphApi.listProjects(),
          simulationApi.getSimulationHistory(),
        ]);

        if (cancelled) return;

        const projList: RawProject[] = projects.status === 'fulfilled' ? projects.value : [];
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const histList: any[] = historyRes.status === 'fulfilled' ? historyRes.value : [];

        const simByProject = new Map<string, typeof histList[0]>();
        for (const h of histList) {
          if (h.project_id) simByProject.set(h.project_id, h);
        }

        const merged: CardData[] = projList.map((p) => {
          const sim = simByProject.get(p.project_id);
          return {
            id: sim?.simulation_id ?? p.project_id,
            projectId: p.project_id,
            simulationId: sim?.simulation_id,
            reportId: sim?.report_id,
            name: p.name !== 'Unnamed Project' ? p.name : (p.simulation_requirement ? truncate(p.simulation_requirement, 30) : 'Untitled'),
            requirement: sim?.simulation_requirement ?? p.simulation_requirement,
            status: sim?.status ?? p.status,
            files: sim?.files ?? p.files ?? [],
            entityTypes: sim?.entity_types,
            entitiesCount: sim?.entities_count,
            profilesCount: sim?.profiles_count,
            currentRound: sim?.current_round,
            totalRounds: sim?.total_rounds,
            graphId: p.graph_id,
            hasOntology: !!p.ontology,
            createdAt: p.created_at,
          };
        });

        // Add simulations that don't have a matching project
        for (const h of histList) {
          if (!projList.some((p) => p.project_id === h.project_id)) {
            merged.push({
              id: h.simulation_id,
              projectId: h.project_id,
              simulationId: h.simulation_id,
              reportId: h.report_id,
              name: h.simulation_requirement ? truncate(h.simulation_requirement, 30) : 'Simulation',
              requirement: h.simulation_requirement,
              status: h.status,
              files: h.files ?? [],
              entityTypes: h.entity_types,
              entitiesCount: h.entities_count,
              profilesCount: h.profiles_count,
              currentRound: h.current_round,
              totalRounds: h.total_rounds,
              graphId: h.graph_id,
              hasOntology: true,
              createdAt: h.created_at,
            });
          }
        }

        // Sort: completed/running first, then by date
        merged.sort((a, b) => {
          const order: Record<string, number> = { completed: 0, running: 1, graph_completed: 2, preparing: 3 };
          const oa = order[a.status] ?? 5;
          const ob = order[b.status] ?? 5;
          if (oa !== ob) return oa - ob;
          return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
        });

        setCards(merged);
      } catch (err) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'Failed to load';
          if (msg.includes('Network Error') || msg.includes('ECONNREFUSED')) {
            setError('Backend not reachable - start the FastAPI server on port 8020');
          } else {
            setError(msg);
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, []);

  function handleClick(c: CardData) {
    if (c.reportId) {
      navigate(`/interaction/${c.reportId}`);
    } else if (c.simulationId && (c.status === 'running' || c.status === 'completed')) {
      navigate(`/simulation/${c.simulationId}/start`);
    } else if (c.simulationId) {
      navigate(`/simulation/${c.simulationId}`);
    } else {
      navigate(`/process/${c.projectId}`);
    }
  }

  return (
    <section className={styles.section}>
      <div ref={ref} className={`${styles.inner} reveal${visible ? ' visible' : ''}`}>
        <div className={styles.heading}>
          <span className="section-label">History</span>
          <h2>Project Database</h2>
        </div>

        {loading && (
          <div className={styles.row}>
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className={styles.skeleton} />
            ))}
          </div>
        )}

        {!loading && error && <p className={styles.error}>{error}</p>}

        {!loading && !error && cards.length === 0 && (
          <p className={styles.empty}>No previous projects - start a new analysis above</p>
        )}

        {!loading && !error && cards.length > 0 && (
          <div className={styles.row}>
            {cards.map((c) => {
              const sm = STATUS_META[c.status] ?? { label: c.status, cls: 'statusCreated' };
              const visibleFiles = c.files.slice(0, 3);
              const moreCount = c.files.length - 3;
              const hasProgress = c.currentRound != null && c.totalRounds != null;

              return (
                <div
                  key={c.id}
                  className={styles.card}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleClick(c)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleClick(c);
                    }
                  }}
                >
                  {/* Header */}
                  <div className={styles.cardHeader}>
                    <span className={styles.cardId}>
                      {c.simulationId ? `SIM_${formatId(c.simulationId)}` : `PRJ_${formatId(c.projectId)}`}
                    </span>
                    <div className={styles.statusIcons}>
                      <span className={styles.stIcon} title="Graph" data-active={c.graphId ? 'true' : 'false'}>G</span>
                      <span className={styles.stIcon} title="Simulation" data-active={c.simulationId ? 'true' : 'false'}>S</span>
                      <span className={styles.stIcon} title="Report" data-active={c.reportId ? 'true' : 'false'}>R</span>
                    </div>
                  </div>

                  {/* Files */}
                  {visibleFiles.length > 0 && (
                    <div className={styles.fileSection}>
                      {visibleFiles.map((f, fileIndex) => {
                        const ext = getExt(f.filename);
                        const color = FILE_EXT_COLORS[ext] ?? DEFAULT_EXT_COLOR;
                        return (
                          <div key={`${f.filename}-${fileIndex}`} className={styles.fileTag}>
                            <span className={styles.fileExt} style={{ background: color.bg, color: color.fg }}>
                              {ext.toUpperCase() || 'FILE'}
                            </span>
                            <span className={styles.fileName}>{truncate(f.filename, 28)}</span>
                          </div>
                        );
                      })}
                      {moreCount > 0 && <span className={styles.fileMore}>+{moreCount} more</span>}
                    </div>
                  )}

                  {/* Body */}
                  <div className={styles.cardBody}>
                    <div className={styles.cardName}>{c.name}</div>
                    {c.requirement && (
                      <p className={styles.cardDesc}>{truncate(c.requirement, 60)}</p>
                    )}
                  </div>

                  {/* Stats row */}
                  {(c.entitiesCount || c.profilesCount || c.entityTypes) && (
                    <div className={styles.statsRow}>
                      {c.entitiesCount != null && (
                        <span className={styles.statChip}>{c.entitiesCount} entities</span>
                      )}
                      {c.profilesCount != null && (
                        <span className={styles.statChip}>{c.profilesCount} agents</span>
                      )}
                    </div>
                  )}

                  {/* Footer */}
                  <div className={styles.cardFooter}>
                    <div className={styles.cardDate}>
                      <span>{formatDate(c.createdAt)}</span>
                      <span className={styles.cardTime}>{formatTime(c.createdAt)}</span>
                    </div>
                    <div className={styles.footerRight}>
                      {hasProgress && (
                        <span className={`${styles.roundsBadge} ${styles[sm.cls] ?? ''}`}>
                          {c.currentRound}/{c.totalRounds}
                        </span>
                      )}
                      <span className={styles.statusBadge}>
                        <span className={`${styles.statusDot} ${styles[sm.cls] ?? ''}`} />
                        {sm.label}
                      </span>
                    </div>
                  </div>

                  <div className={styles.hoverLine} />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
