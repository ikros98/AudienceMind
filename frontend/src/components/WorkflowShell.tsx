import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useWorkspace } from '../store/workspace';
import WorkflowNav from './WorkflowNav';
import ViewModeSwitcher from './ViewModeSwitcher';
import s from '../styles/workflow-shell.module.css';

interface Props {
  graphPanel?: ReactNode;
  children: ReactNode;
}

export default function WorkflowShell({ graphPanel, children }: Props) {
  const { viewMode } = useWorkspace();

  const showGraph = viewMode !== 'workbench' && graphPanel;
  const graphFull = viewMode === 'graph';

  return (
    <div className={s.shell}>
      {/* Top bar */}
      <div className={s.topBar}>
        <div className={s.topBarLeft}>
          <Link to="/" className={s.logo}>PersonaGraph</Link>
          <WorkflowNav />
        </div>
        <div className={s.topBarRight}>
          <ViewModeSwitcher />
        </div>
      </div>

      {/* Body */}
      <div className={s.body}>
        {showGraph && (
          <div className={`${s.graphPanel} ${graphFull ? s.full : ''}`}>
            {graphPanel}
          </div>
        )}
        {viewMode !== 'graph' && (
          <div className={`${s.contentPanel} ${!showGraph ? s.full : ''}`}>
            {children}
          </div>
        )}
      </div>
    </div>
  );
}
