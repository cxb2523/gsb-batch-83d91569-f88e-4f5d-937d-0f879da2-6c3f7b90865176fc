import "./fonts.css";
import { createRoot } from "react-dom/client";
import { createApiClient } from "./api/client";
import { AppShell } from "./App";
import { ErrorBoundary } from "./ErrorBoundary";
import { installImageFallback } from "./ui/imageFallback";

async function main() {
  installImageFallback(document);
  const [baseUrl, apiToken, diagnosticsLogPath] = await Promise.all([
    window.releaseTracker?.getApiBaseUrl?.(),
    window.releaseTracker?.getApiToken?.(),
    window.releaseTracker?.getDiagnosticsLogPath?.()
  ]);
  const apiBaseUrl = baseUrl ?? "http://127.0.0.1:3333";
  const api = createApiClient(apiBaseUrl, apiToken);
  createRoot(document.getElementById("root")!).render(
    <ErrorBoundary api={api}>
      <AppShell
        apiBaseUrl={apiBaseUrl}
        api={api}
        diagnosticsLogPath={diagnosticsLogPath}
        onOpenDiagnosticsLog={() => window.releaseTracker?.openDiagnosticsLog?.()}
      />
    </ErrorBoundary>
  );
}

void main();
