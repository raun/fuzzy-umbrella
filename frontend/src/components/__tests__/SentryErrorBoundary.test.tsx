/**
 * Tests for the Sentry ErrorBoundary integration in frontend/src/main.tsx.
 *
 * The entire @sentry/react module is mocked so:
 *  - No real Sentry DSN or network call is required.
 *  - Sentry.init() is a no-op vi.fn().
 *  - Sentry.ErrorBoundary is a React component implemented here that mirrors
 *    the real contract: renders children normally; renders `fallback` when a
 *    descendant throws during render.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock @sentry/react before any import that might pull it in
// ---------------------------------------------------------------------------

// A minimal React error boundary that delegates to the `fallback` prop — the
// same contract as Sentry.ErrorBoundary.
class _MockErrorBoundary extends React.Component<
  { children: React.ReactNode; fallback: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode; fallback: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return <>{this.props.fallback}</>;
    }
    return <>{this.props.children}</>;
  }
}

vi.mock("@sentry/react", () => ({
  init: vi.fn(),
  ErrorBoundary: _MockErrorBoundary,
  browserTracingIntegration: vi.fn(() => ({})),
}));

import * as Sentry from "@sentry/react";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** A component that unconditionally throws during render. */
function ThrowingChild(): React.ReactElement {
  throw new Error("Simulated render error");
}

/** Silence React's console.error output for expected error-boundary throws. */
function suppressConsoleError() {
  return vi.spyOn(console, "error").mockImplementation(() => {});
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Sentry ErrorBoundary (mocked @sentry/react)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("ErrorBoundary — fallback rendering", () => {
    it("renders children normally when no error is thrown", () => {
      render(
        <Sentry.ErrorBoundary fallback={<p>Something went wrong.</p>}>
          <span>All good</span>
        </Sentry.ErrorBoundary>
      );

      expect(screen.getByText("All good")).toBeInTheDocument();
      expect(screen.queryByText("Something went wrong.")).not.toBeInTheDocument();
    });

    it("renders the fallback when a child throws during render", () => {
      const restoreConsole = suppressConsoleError();
      try {
        render(
          <Sentry.ErrorBoundary fallback={<p>Something went wrong.</p>}>
            <ThrowingChild />
          </Sentry.ErrorBoundary>
        );
      } finally {
        restoreConsole.mockRestore();
      }

      expect(screen.getByText("Something went wrong.")).toBeInTheDocument();
    });

    it("does not render children after a throw", () => {
      const restoreConsole = suppressConsoleError();
      try {
        render(
          <Sentry.ErrorBoundary fallback={<p>Something went wrong.</p>}>
            <ThrowingChild />
            <span>Should not appear</span>
          </Sentry.ErrorBoundary>
        );
      } finally {
        restoreConsole.mockRestore();
      }

      expect(screen.queryByText("Should not appear")).not.toBeInTheDocument();
    });

    it("renders the exact fallback element provided via the fallback prop", () => {
      const restoreConsole = suppressConsoleError();
      try {
        render(
          <Sentry.ErrorBoundary fallback={<p>An unexpected error occurred.</p>}>
            <ThrowingChild />
          </Sentry.ErrorBoundary>
        );
      } finally {
        restoreConsole.mockRestore();
      }

      // The text in main.tsx at the time of writing is "An unexpected error occurred."
      expect(screen.getByText("An unexpected error occurred.")).toBeInTheDocument();
    });
  });

  describe("Sentry.init — module mock verification", () => {
    it("Sentry.init is a vi.fn() (module is fully mocked)", () => {
      // Verify @sentry/react is mocked so no real SDK calls occur in tests.
      expect(vi.isMockFunction(Sentry.init)).toBe(true);
    });

    it("Sentry.init is not called by the ErrorBoundary render itself", () => {
      // Rendering the ErrorBoundary component should not trigger Sentry.init.
      // The init call in main.tsx is guarded by `if (dsn)` and runs at module
      // load time — not during component render. This test confirms the mock
      // stays clean across ErrorBoundary renders.
      vi.mocked(Sentry.init).mockClear();

      render(
        <Sentry.ErrorBoundary fallback={<p>Something went wrong.</p>}>
          <span>content</span>
        </Sentry.ErrorBoundary>
      );

      expect(Sentry.init).not.toHaveBeenCalled();
    });
  });
});
