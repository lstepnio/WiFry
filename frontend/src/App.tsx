import Dashboard from './components/Dashboard';
import ErrorBoundary from './components/ErrorBoundary';
import Gremlin from './components/Gremlin';
import CollabOverlay from './components/CollabOverlay';
import NotificationProvider from './components/NotificationProvider';

function App() {
  return (
    <NotificationProvider>
      <ErrorBoundary>
        <Dashboard />
      </ErrorBoundary>
      <CollabOverlay />
      <Gremlin />
    </NotificationProvider>
  );
}

export default App;
