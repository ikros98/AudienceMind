import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import type { PendingUpload } from '../types';

interface PendingUploadCtx {
  upload: PendingUpload;
  setFiles: (files: File[]) => void;
  addFiles: (files: File[]) => void;
  removeFile: (index: number) => void;
  setRequirement: (req: string) => void;
  clear: () => void;
}

const empty: PendingUpload = { files: [], requirement: '' };
const Ctx = createContext<PendingUploadCtx | null>(null);

export function PendingUploadProvider({ children }: { children: ReactNode }) {
  const [upload, setUpload] = useState<PendingUpload>(empty);

  const setFiles = useCallback((files: File[]) => setUpload((u) => ({ ...u, files })), []);
  const addFiles = useCallback(
    (files: File[]) => setUpload((u) => ({ ...u, files: [...u.files, ...files] })),
    [],
  );
  const removeFile = useCallback(
    (i: number) => setUpload((u) => ({ ...u, files: u.files.filter((_, idx) => idx !== i) })),
    [],
  );
  const setRequirement = useCallback(
    (requirement: string) => setUpload((u) => ({ ...u, requirement })),
    [],
  );
  const clear = useCallback(() => setUpload(empty), []);

  return (
    <Ctx.Provider value={{ upload, setFiles, addFiles, removeFile, setRequirement, clear }}>
      {children}
    </Ctx.Provider>
  );
}

export function usePendingUpload(): PendingUploadCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('usePendingUpload must be used within PendingUploadProvider');
  return ctx;
}
