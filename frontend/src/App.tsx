import Dashboard from './components/Dashboard';
import ErrorBoundary from './components/ErrorBoundary';
import Gremlin from './components/Gremlin';
import CollabOverlay from './components/CollabOverlay';

function App() {
  return (
    <>
      <ErrorBoundary>
        <Dashboard />
      </ErrorBoundary>
      <CollabOverlay />
      <Gremlin />
    </>
  );
}

export default App;
