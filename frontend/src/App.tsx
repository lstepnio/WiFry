import { useRef } from 'react';
import Dashboard from './components/Dashboard';
import ErrorBoundary from './components/ErrorBoundary';
import Gremlin from './components/Gremlin';
import CollabOverlay from './components/CollabOverlay';

function App() {
  const collabWsRef = useRef<WebSocket | null>(null);

  return (
    <>
      <ErrorBoundary>
        <Dashboard collabWsRef={collabWsRef} />
      </ErrorBoundary>
      <CollabOverlay wsRef={collabWsRef} />
      <Gremlin />
    </>
  );
}

export default App;
