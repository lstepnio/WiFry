import type { Notification as NotificationItem } from '../hooks/useNotification';

const TYPE_STYLES: Record<string, string> = {
  success: 'bg-green-600',
  error: 'bg-red-600',
  info: 'bg-blue-600',
};

export default function NotificationStack({
  notifications,
  onDismiss,
}: {
  notifications: NotificationItem[];
  onDismiss: (id: string) => void;
}) {
  if (notifications.length === 0) return null;

  return (
    <div className="fixed right-4 top-4 z-50 flex flex-col gap-2">
      {notifications.map((n) => (
        <div
          key={n.id}
          className={`animate-fade-in flex items-start gap-3 rounded-lg px-4 py-3 text-sm text-white shadow-lg ${TYPE_STYLES[n.type] || TYPE_STYLES.info}`}
          style={{ minWidth: 280, maxWidth: 400 }}
        >
          <span className="flex-1">{n.message}</span>
          <button
            onClick={() => onDismiss(n.id)}
            className="ml-2 text-white/70 hover:text-white"
            aria-label="Dismiss"
          >
            &times;
          </button>
        </div>
      ))}
    </div>
  );
}
