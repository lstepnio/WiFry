import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary] Uncaught error:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-gray-950 text-white">
          <div className="max-w-md space-y-6 text-center">
            <h1 className="text-3xl font-bold text-red-400">Something went wrong</h1>
            <p className="text-sm text-gray-400">
              {this.state.error?.message || 'An unexpected error occurred.'}
            </p>
            <div className="flex justify-center gap-4">
              <button
                onClick={() => window.location.reload()}
                className="rounded-lg bg-purple-600 px-5 py-2 text-sm font-medium text-white hover:bg-purple-700"
              >
                Reload
              </button>
              <button
                onClick={() => {
                  window.location.hash = '#/sessions';
                  window.location.reload();
                }}
                className="rounded-lg border border-gray-600 px-5 py-2 text-sm font-medium text-gray-300 hover:bg-gray-800"
              >
                Go to Sessions
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
