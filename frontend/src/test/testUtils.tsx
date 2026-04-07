import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import ConfirmProvider from '../components/ConfirmProvider';
import NotificationProvider from '../components/NotificationProvider';

/**
 * Render a component wrapped in all app-level context providers
 * (NotificationProvider, ConfirmProvider) so hooks like useNotification()
 * and useConfirm() work correctly in tests.
 */
export function renderWithProviders(ui: ReactElement) {
  return render(
    <NotificationProvider>
      <ConfirmProvider>{ui}</ConfirmProvider>
    </NotificationProvider>,
  );
}

/** @deprecated Use renderWithProviders instead */
export function renderWithNotifications(ui: ReactElement) {
  return renderWithProviders(ui);
}

export function jsonResponse(body: unknown, init: ResponseInit = {}) {
  const headers = new Headers(init.headers);
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  return new Response(JSON.stringify(body), {
    ...init,
    headers,
  });
}
