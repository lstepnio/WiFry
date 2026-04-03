import { useCallback, useEffect, useRef, useState } from 'react';

export type NotificationType = 'success' | 'error' | 'info';

export interface Notification {
  id: string;
  message: string;
  type: NotificationType;
}

let nextId = 0;

export function useNotification() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const notify = useCallback(
    (message: string, type: NotificationType = 'info') => {
      const id = `notif-${++nextId}`;
      const notification: Notification = { id, message, type };
      setNotifications((prev) => [...prev, notification]);

      const delay = type === 'error' ? 10_000 : 5_000;
      const timer = setTimeout(() => {
        dismiss(id);
      }, delay);
      timers.current.set(id, timer);

      return id;
    },
    [dismiss]
  );

  // Cleanup all timers on unmount
  useEffect(() => {
    const t = timers.current;
    return () => {
      t.forEach((timer) => clearTimeout(timer));
      t.clear();
    };
  }, []);

  return { notify, notifications, dismiss };
}
