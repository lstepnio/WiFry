import Dashboard from './components/Dashboard';
import ErrorBoundary from './components/ErrorBoundary';
import Gremlin from './components/Gremlin';
import CollabOverlay from './components/CollabOverlay';
import ConfirmProvider from './components/ConfirmProvider';
import NotificationProvider from './components/NotificationProvider';

function App() {
  return (
    <NotificationProvider>
      <ConfirmProvider>
        <ErrorBoundary>
          <Dashboard />
        </ErrorBoundary>
        <CollabOverlay />
        <Gremlin />
      </ConfirmProvider>
    </NotificationProvider>
  );
}

export default App;
