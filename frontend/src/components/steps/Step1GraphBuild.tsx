import { useState } from 'react';
import type { GraphData, TaskInfo, Project } from '../../types';
import StatusIndicator from '../StatusIndicator';
import SystemLog from '../SystemLog';
import shared from '../../styles/shared.module.css';
import s from '../../styles/steps.module.css';

interface Props {
  currentPhase: number;
  projectData: Project | null;
  ontologyProgress: TaskInfo | null;
  buildProgress: TaskInfo | null;
  graphData: GraphData | null;
  schemaMode: boolean;
  systemLogs: string[];
  onNextStep: () => void;
}

function TagWithTooltip({
  name,
  description,
  variant,
}: {
  name: string;
  description: string;
  variant: 'entity' | 'edge';
}) {
  const [show, setShow] = useState(false);
  return (
    <span
      className={`${s.tag} ${variant === 'entity' ? s.tagEntity : s.tagEdge}`}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {name}
      {show && <span className={s.tagTooltip}>{description}</span>}
    </span>
  );
}

function formatDate(iso?: string): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

function firstMeaningfulLine(value?: string | null): string | null {
  if (!value) return null;
  const line = value
    .split(/\r?\n/)
    .map((part) => part.trim())
    .find(Boolean);
  return line ?? null;
}

export default function Step1GraphBuild({
  currentPhase,
  projectData,
  ontologyProgress,
  buildProgress,
  graphData,
  schemaMode,
  systemLogs,
  onNextStep,
}: Props) {
  const ontology = projectData?.ontology;
  const ontologyDone = currentPhase >= 1;

  const nodeCount = graphData?.metadata?.node_count ?? graphData?.nodes.length ?? 0;
  const edgeCount = graphData?.metadata?.edge_count ?? graphData?.edges.length ?? 0;
  const entityTypeCount = graphData?.metadata?.entity_types?.length ?? ontology?.entity_types.length ?? 0;
  const relationTypeCount = ontology?.edge_types.length ?? graphData?.metadata?.edge_types?.length ?? 0;

  const isEarlyStage = !ontologyDone && !ontologyProgress;
  const pid = projectData?.project_id;
  const pName = projectData?.name ?? 'Unnamed Project';
  const pStatus = projectData?.status;
  const pCreated = projectData?.created_at;
  const pReq = projectData?.simulation_requirement;
  const pFiles = projectData?.files;
  const fileCount = pFiles?.length ?? projectData?.file_count ?? 0;
  const buildDone = currentPhase >= 2;
  const buildFailed = buildProgress?.status === 'failed' || pStatus === 'failed';
  const buildErrorSummary =
    firstMeaningfulLine(buildProgress?.message) ??
    firstMeaningfulLine(buildProgress?.error) ??
    firstMeaningfulLine(projectData?.error) ??
    null;

  return (
    <div className={s.stepContainer}>
      {/* -- Project info card (always visible) -- */}
      <div className={s.stepCard}>
        <div className={s.stepHeader}>
          <span className={s.stepNumber}>PRJ</span>
          <span className={s.stepTitle}>{pName}</span>
          {pStatus && (
            <StatusIndicator status={
              pStatus === 'graph_completed' ? 'completed' :
              pStatus === 'failed' ? 'error' :
              pStatus === 'created' ? 'idle' : 'processing'
            } />
          )}
        </div>
        <div className={s.stepBody}>
          <div className={s.infoGrid}>
            {pid && (
              <div className={s.idRow}>
                <span className={s.idLabel}>Project ID</span>
                <span className={s.idValue}>{pid}</span>
              </div>
            )}
            {pStatus && (
              <div className={s.idRow}>
                <span className={s.idLabel}>Status</span>
                <span className={s.idValue}>{pStatus.replace(/_/g, ' ')}</span>
              </div>
            )}
            {pCreated && (
              <div className={s.idRow}>
                <span className={s.idLabel}>Created</span>
                <span className={s.idValue}>{formatDate(pCreated)}</span>
              </div>
            )}
            <div className={s.idRow}>
              <span className={s.idLabel}>Files</span>
              <span className={s.idValue}>{fileCount} file{fileCount !== 1 ? 's' : ''}</span>
            </div>
          </div>
          {pReq && (
            <div style={{ marginTop: '0.75rem' }}>
              <div className={s.tagLabel}>Simulation Requirement</div>
              <p className={s.progressMessage} style={{ marginTop: '0.25rem' }}>{pReq}</p>
            </div>
          )}
          {isEarlyStage && (
            <div className={s.earlyNotice}>
              <span className={s.earlyIcon}>i</span>
              This project is in early stage. Upload files and set a requirement from the{' '}
              <a href="/demo" className={s.earlyLink}>Demo page</a> to begin analysis.
            </div>
          )}
        </div>
      </div>

      {/* -- Step 01: Ontology Generation -- */}
      {(currentPhase >= 0 && (ontologyProgress || ontologyDone)) && (
        <div className={s.stepCard}>
          <div className={s.stepHeader}>
            <span className={s.stepNumber}>01</span>
            <span className={s.stepTitle}>Ontology Generation</span>
            <StatusIndicator status={ontologyDone ? 'completed' : 'processing'} />
          </div>

          <div className={s.stepBody}>
            {!ontologyDone && ontologyProgress && (
              <div className={s.progressMessage}>
                {ontologyProgress.message || 'Analyzing documents...'}
              </div>
            )}

            {ontologyDone && ontology && (
              <>
                <div className={s.tagLabel}>Entity Types</div>
                <div className={s.tagList}>
                  {ontology.entity_types.map((et) => (
                    <TagWithTooltip
                      key={et.name}
                      name={et.name}
                      description={et.description}
                      variant="entity"
                    />
                  ))}
                </div>

                <div className={s.tagLabel} style={{ marginTop: '0.65rem' }}>
                  Edge Types
                </div>
                <div className={s.tagList}>
                  {ontology.edge_types.map((et) => (
                    <TagWithTooltip
                      key={et.name}
                      name={et.name}
                      description={et.description}
                      variant="edge"
                    />
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* -- Step 02: Graph Build -- */}
      {currentPhase >= 1 && (
        <div className={s.stepCard}>
          <div className={s.stepHeader}>
            <span className={s.stepNumber}>02</span>
            <span className={s.stepTitle}>Graph Build</span>
            <StatusIndicator status={buildDone ? 'completed' : buildFailed ? 'error' : 'processing'} />
          </div>

          <div className={s.stepBody}>
            {buildFailed && buildErrorSummary && (
              <div className={s.errorNotice}>
                <span className={s.errorIcon}>!</span>
                <div>
                  <div className={s.errorTitle}>Graph build failed</div>
                  <div>{buildErrorSummary}</div>
                </div>
              </div>
            )}

            {!buildDone && buildProgress && !buildFailed && (
              <>
                <div className={shared.progressBar}>
                  <div
                    className={shared.progressFill}
                    style={{ width: `${buildProgress.progress ?? 0}%` }}
                  />
                </div>
                <div className={s.progressMessage}>
                  <span className={s.progressPercent}>
                    {buildProgress.progress ?? 0}%
                  </span>
                  <span>{buildProgress.message || 'Building knowledge graph...'}</span>
                </div>
              </>
            )}

            {buildDone && (
              <>
                {schemaMode && (
                  <div className={s.schemaNotice}>
                    <span className={s.schemaIcon}>i</span>
                    Full graph data is currently unavailable from the graph service. This project is
                    showing the ontology schema preview, so these counts describe the schema rather
                    than the project&apos;s actual graph nodes and edges.
                  </div>
                )}

                <div className={s.statsGrid}>
                  <div className={s.statCard}>
                    <div className={s.statValue}>{schemaMode ? entityTypeCount : nodeCount}</div>
                    <div className={s.statLabel}>{schemaMode ? 'Entity Types' : 'Nodes'}</div>
                  </div>
                  <div className={s.statCard}>
                    <div className={s.statValue}>{schemaMode ? relationTypeCount : edgeCount}</div>
                    <div className={s.statLabel}>{schemaMode ? 'Relation Types' : 'Edges'}</div>
                  </div>
                  <div className={s.statCard}>
                    <div className={s.statValue}>{schemaMode ? edgeCount : entityTypeCount}</div>
                    <div className={s.statLabel}>{schemaMode ? 'Schema Links' : 'Entity Types'}</div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* -- Step 03: Complete -- */}
      {currentPhase >= 2 && (
        <div className={`${s.stepCard} ${s.completeCard}`}>
          <div className={s.stepHeader}>
            <span className={s.stepNumber}>03</span>
            <span className={s.stepTitle}>Graph Ready</span>
            <StatusIndicator status="completed" />
          </div>

          <div className={s.stepBody}>
            <div className={s.completeBanner}>
              <div className={s.completeIcon}>
                <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
                  <circle cx="18" cy="18" r="17" stroke="url(#cg)" strokeWidth="2" />
                  <path d="M12 18l4 4 8-8" stroke="#4ade80" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                  <defs><linearGradient id="cg" x1="0" y1="0" x2="36" y2="36">
                    <stop stopColor="var(--accent-cyan)" />
                    <stop offset="1" stopColor="var(--accent-violet)" />
                  </linearGradient></defs>
                </svg>
              </div>
              <div className={s.completeText}>
                <span className={s.completeLabel}>
                  {schemaMode ? 'Schema Preview Ready' : 'Knowledge Graph Built'}
                </span>
                <span className={s.completeSubtext}>
                  {schemaMode
                    ? `${entityTypeCount} entity types / ${relationTypeCount} relation types / graph service unavailable`
                    : `${nodeCount} nodes / ${edgeCount} edges / ${entityTypeCount} types`}
                </span>
              </div>
            </div>

            <div className={s.buttonRow}>
              <button className={s.primaryBtn} onClick={onNextStep}>
                Enter Environment Setup
              </button>
            </div>
          </div>
        </div>
      )}

      {/* -- System Logs -- */}
      <SystemLog lines={systemLogs} />
    </div>
  );
}
