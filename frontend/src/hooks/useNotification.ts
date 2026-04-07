import { createContext, useContext } from 'react';

export type NotificationType = 'success' | 'error' | 'info';

export interface NotificationItem {
  id: string;
  message: string;
  type: NotificationType;
}

export interface NotificationContextValue {
  notifications: NotificationItem[];
  dismiss: (id: string) => void;
  notify: (message: string, type?: NotificationType) => string;
}

export const NotificationContext = createContext<NotificationContextValue | null>(null);

export function useNotification() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error('useNotification must be used within a NotificationProvider');
  }

  return context;
}
