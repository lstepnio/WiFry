import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import NotificationStack from './Notification';
import { NotificationContext, type NotificationItem, type NotificationType } from '../hooks/useNotification';

let nextId = 0;

export default function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((notification) => notification.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const notify = useCallback((message: string, type: NotificationType = 'info') => {
    const id = `notif-${++nextId}`;
    const notification: NotificationItem = { id, message, type };
    setNotifications((prev) => [...prev, notification]);

    const delay = type === 'error' ? 10_000 : 5_000;
    const timer = setTimeout(() => dismiss(id), delay);
    timers.current.set(id, timer);

    return id;
  }, [dismiss]);

  useEffect(() => {
    const activeTimers = timers.current;
    return () => {
      activeTimers.forEach((timer) => clearTimeout(timer));
      activeTimers.clear();
    };
  }, []);

  const value = useMemo(() => ({ notifications, dismiss, notify }), [dismiss, notifications, notify]);

  return (
    <NotificationContext.Provider value={value}>
      {children}
      <NotificationStack notifications={notifications} onDismiss={dismiss} />
    </NotificationContext.Provider>
  );
}
