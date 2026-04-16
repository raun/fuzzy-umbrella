import * as Sentry from "@sentry/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

const dsn = import.meta.env.VITE_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT ?? "development",
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: 1.0,
    sendDefaultPii: false,
  });
}

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root element #root not found in the document.");
}

createRoot(container).render(
  <Sentry.ErrorBoundary fallback={<p>An unexpected error occurred.</p>}>
    <StrictMode>
      <App />
    </StrictMode>
  </Sentry.ErrorBoundary>
);
