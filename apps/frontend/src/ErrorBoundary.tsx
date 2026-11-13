import React, { type ErrorInfo, type ReactNode } from "react";
import type { ApiClient } from "./api/client";

interface ErrorBoundaryProps {
  api: Pick<ApiClient, "logEvent">;
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    void this.props.api.logEvent("ui.render_error", {
      error: error.message,
      stack: error.stack,
      componentStack: info.componentStack
    }).catch(() => undefined);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <section className="state error error-boundary" role="alert">
        <h2>Something went wrong</h2>
        <p>{this.state.error.message || "The app encountered an unexpected error."}</p>
        <button type="button" onClick={() => window.location.reload()}>Reload</button>
      </section>
    );
  }
}
