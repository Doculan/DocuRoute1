import { Component } from "react";

/**
 * Catches a crash in the screens beneath it and shows a short message
 * with a way back, instead of an empty white page. "Try again" remounts
 * them from the start.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false, attempt: 0 };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, info) {
    // Left in the console for whoever investigates; the screen stays usable.
    console.error("A screen failed to draw:", error, info?.componentStack);
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="empty-state" role="alert">
          <p className="empty-title">{this.props.title || "This screen could not be shown"}</p>
          <p className="empty-text">Something went wrong while drawing it. Nothing was changed.</p>
          <button type="button" className="btn btn-ghost btn-sm"
                  onClick={() => this.setState((s) => ({ failed: false, attempt: s.attempt + 1 }))}>
            {this.props.backLabel || "Try again"}
          </button>
        </div>
      );
    }
    return <div key={this.state.attempt}>{this.props.children}</div>;
  }
}
