import { useRef, useEffect } from 'react';
import s from '../styles/shared.module.css';

interface Props {
  lines: string[];
  title?: string;
  maxHeight?: string;
}

export default function SystemLog({ lines, title = 'System Log', maxHeight = '300px' }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [lines.length]);

  const lineTone = (line: string) => {
    const text = line.toLowerCase();
    if (
      text.includes('[error]') ||
      text.includes(' failed') ||
      text.includes('error:') ||
      text.includes('timed out')
    ) {
      return s.logLineError;
    }
    if (
      text.includes('[warn]') ||
      text.includes('retrying') ||
      text.includes('stalled') ||
      text.includes('unavailable')
    ) {
      return s.logLineWarn;
    }
    if (text.includes('[info]')) {
      return s.logLineInfo;
    }
    return '';
  };

  return (
    <div className={s.logPanel} style={{ maxHeight }}>
      <div className={s.logHeader}>{title}</div>
      <div className={s.logBody} aria-live="polite">
        {lines.length === 0 && <span className={s.logEmpty}>Waiting for output...</span>}
        {lines.map((line, i) => (
          <div key={i} className={`${s.logLine} ${lineTone(line)}`.trim()}>{line}</div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
