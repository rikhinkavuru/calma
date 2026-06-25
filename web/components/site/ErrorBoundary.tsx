"use client";

import React from "react";

/* Contains a failing decorative subtree (e.g. a WebGL component on a machine
   with no GPU / WebGL disabled) so it degrades to a CSS fallback instead of
   throwing past the root and blanking the whole page. */
export class ErrorBoundary extends React.Component<
  { fallback?: React.ReactNode; children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    /* swallow — the fallback is the recovery */
  }
  render() {
    return this.state.failed ? this.props.fallback ?? null : this.props.children;
  }
}
