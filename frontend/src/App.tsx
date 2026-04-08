import { WorkspaceProvider } from "./store/workspace";
import { PendingUploadProvider } from "./store/pendingUpload";
import AppRouter from "./router";

export function App() {
  return (
    <WorkspaceProvider>
      <PendingUploadProvider>
        <AppRouter />
      </PendingUploadProvider>
    </WorkspaceProvider>
  );
}
