interface Props {
  status: string;
  size?: number;
}

const COLOR_MAP: Record<string, string> = {
  completed: '#4ade80',
  ready: '#4ade80',
  running: '#facc15',
  processing: '#facc15',
  preparing: '#facc15',
  generating: '#facc15',
  pending: 'var(--text-muted)',
  created: 'var(--text-muted)',
  idle: 'var(--text-muted)',
  failed: '#f87171',
  error: '#f87171',
  stopped: '#f87171',
};

export default function StatusIndicator({ status, size = 8 }: Props) {
  const color = COLOR_MAP[status] || 'var(--text-muted)';
  const isActive = ['running', 'processing', 'preparing', 'generating'].includes(status);

  return (
    <span
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        borderRadius: '50%',
        background: color,
        animation: isActive ? 'pulse 1.5s ease-in-out infinite' : 'none',
        flexShrink: 0,
      }}
      title={status}
    />
  );
}
