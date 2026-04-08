import { useRef, useState, useCallback, useEffect, type DragEvent, type ChangeEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { usePendingUpload } from '../store/pendingUpload';
import { useWorkspace } from '../store/workspace';
import WorkflowNav from '../components/WorkflowNav';
import ViewModeSwitcher from '../components/ViewModeSwitcher';
import { HistoryDatabase } from '../components/HistoryDatabase';
import intake from '../styles/intake.module.css';
import s from '../styles/demo-page.module.css';

const ACCEPTED = '.pdf,.md,.txt';
const ACCEPT_SET = new Set(['application/pdf', 'text/markdown', 'text/plain']);
const ACCEPT_EXT = new Set(['.pdf', '.md', '.txt']);

function isAccepted(file: File): boolean {
  if (ACCEPT_SET.has(file.type)) return true;
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
  return ACCEPT_EXT.has(ext);
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DemoPage() {
  const navigate = useNavigate();
  const { upload, addFiles, removeFile, setRequirement } = usePendingUpload();
  const { clearWorkflowContext } = useWorkspace();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    clearWorkflowContext();
  }, [clearWorkflowContext]);

  const handleFiles = useCallback(
    (raw: FileList | null) => {
      if (!raw) return;
      const valid = Array.from(raw).filter(isAccepted);
      if (valid.length) addFiles(valid);
    },
    [addFiles],
  );

  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    setDragging(true);
  }, []);

  const onDragLeave = useCallback(() => setDragging(false), []);

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const onBrowse = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      handleFiles(e.target.files);
      e.target.value = '';
    },
    [handleFiles],
  );

  const canStart = upload.files.length > 0 && upload.requirement.trim().length > 0;

  return (
    <div className={s.page}>
      {/* -- Top bar -- */}
      <header className={s.topBar}>
        <div className={s.topBarLeft}>
          <Link to="/" className={s.logo}>PersonaGraph</Link>
          <WorkflowNav />
        </div>
        <div className={s.topBarRight}>
          <ViewModeSwitcher />
        </div>
      </header>

      {/* -- Main content -- */}
      <main className={s.content}>
        <h1 className={s.heading}>New Analysis</h1>
        <p className={s.subtitle}>Set up your simulation</p>

        {/* Upload zone */}
        <div className={s.formCard}>
          <div
            className={`${intake.dropZone} ${dragging ? intake.dropZoneActive : ''}`}
            role="button"
            tabIndex={0}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                inputRef.current?.click();
              }
            }}
          >
            <span className={intake.dropIcon}>DOC</span>
            <span className={intake.dropLabel}>
              Drag &amp; drop files here, or click to browse
            </span>
            <span className={intake.dropHint}>.pdf, .md, .txt accepted</span>
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPTED}
              multiple
              hidden
              onChange={onBrowse}
            />
          </div>

          {upload.files.length > 0 && (
            <div className={intake.fileList}>
              {upload.files.map((f, i) => (
                <div key={`${f.name}-${i}`} className={intake.fileItem}>
                  <span className={intake.fileIcon}>ATT</span>
                  <div className={intake.fileInfo}>
                    <div className={intake.fileName}>{f.name}</div>
                    <div className={intake.fileSize}>{formatSize(f.size)}</div>
                  </div>
                  <button
                    type="button"
                    className={intake.fileRemove}
                    onClick={(e) => {
                      e.stopPropagation();
                      removeFile(i);
                    }}
                    aria-label={`Remove ${f.name}`}
                  >
                    x
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Prompt textarea */}
        <div className={s.formCard}>
          <textarea
            className={intake.textarea}
            placeholder="Describe what the simulation should test..."
            value={upload.requirement}
            onChange={(e) => setRequirement(e.target.value)}
          />
        </div>

        {/* Start button */}
        <div className={s.actions}>
          <button
            type="button"
            className={`btn btn-primary ${s.startBtn}`}
            disabled={!canStart}
            onClick={() => navigate('/process/new')}
          >
            Start Analysis
          </button>
        </div>

        {/* History */}
        <div className={s.historySection}>
          <HistoryDatabase />
        </div>
      </main>
    </div>
  );
}
