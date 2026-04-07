import { useCallback, useMemo, useRef, useState } from 'react';
import ModalDialog from './ModalDialog';
import { ConfirmContext, type ConfirmOptions, type ConfirmTone } from '../hooks/useConfirm';

interface PendingConfirm {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  confirmTone: ConfirmTone;
  resolve: (value: boolean) => void;
}

/**
 * Provides a global `confirm()` function via React context that shows
 * a styled ModalDialog instead of the browser-native `window.confirm()`.
 *
 * Wrap your app with `<ConfirmProvider>` and use `useConfirm()` in any
 * component to get a promise-based confirm function:
 *
 *   const confirm = useConfirm();
 *   const ok = await confirm({ title: 'Delete?', message: '...' });
 *   if (!ok) return;
 */
export default function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const pendingRef = useRef<PendingConfirm | null>(null);

  const confirm = useCallback((options: ConfirmOptions): Promise<boolean> => {
    // If there's already a pending confirm, reject it
    if (pendingRef.current) {
      pendingRef.current.resolve(false);
    }

    return new Promise<boolean>((resolve) => {
      const entry: PendingConfirm = {
        title: options.title,
        message: options.message,
        confirmLabel: options.confirmLabel ?? 'Confirm',
        cancelLabel: options.cancelLabel ?? 'Cancel',
        confirmTone: options.confirmTone ?? 'primary',
        resolve,
      };
      pendingRef.current = entry;
      setPending(entry);
    });
  }, []);

  const handleConfirm = useCallback(() => {
    if (pendingRef.current) {
      pendingRef.current.resolve(true);
      pendingRef.current = null;
    }
    setPending(null);
  }, []);

  const handleCancel = useCallback(() => {
    if (pendingRef.current) {
      pendingRef.current.resolve(false);
      pendingRef.current = null;
    }
    setPending(null);
  }, []);

  const value = useMemo(() => ({ confirm }), [confirm]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <ModalDialog
        open={pending !== null}
        title={pending?.title ?? ''}
        description={pending?.message}
        confirmLabel={pending?.confirmLabel}
        cancelLabel={pending?.cancelLabel}
        confirmTone={pending?.confirmTone}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </ConfirmContext.Provider>
  );
}
