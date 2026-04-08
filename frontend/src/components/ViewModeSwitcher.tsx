import { useWorkspace } from '../store/workspace';
import type { ViewMode } from '../types';

const MODES: { value: ViewMode; icon: string; label: string }[] = [
  { value: 'graph', icon: 'G', label: 'Graph' },
  { value: 'split', icon: 'S', label: 'Split' },
  { value: 'workbench', icon: 'W', label: 'Work' },
];

export default function ViewModeSwitcher() {
  const { viewMode, setViewMode } = useWorkspace();

  return (
    <div style={{ display: 'flex', gap: '2px', background: 'rgba(255,255,255,0.06)', borderRadius: 'var(--radius-md)', padding: '2px' }}>
      {MODES.map((m) => (
        <button
          key={m.value}
          onClick={() => setViewMode(m.value)}
          title={m.label}
          style={{
            padding: '0.3rem 0.55rem',
            borderRadius: 'var(--radius-sm)',
            border: 'none',
            background: viewMode === m.value ? 'rgba(126,231,255,0.15)' : 'transparent',
            color: viewMode === m.value ? 'var(--accent-cyan)' : 'var(--text-muted)',
            cursor: 'pointer',
            fontSize: '0.85rem',
            transition: 'all 0.15s',
          }}
        >
          {m.icon}
        </button>
      ))}
    </div>
  );
}
