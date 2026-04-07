import { createContext, useContext } from 'react';

export type ConfirmTone = 'primary' | 'danger';

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmTone?: ConfirmTone;
}

export interface ConfirmContextValue {
  /**
   * Show a styled confirmation dialog and return a promise that resolves
   * to `true` (confirmed) or `false` (cancelled).
   *
   * Usage:
   *   const confirmed = await confirm({ title: '...', message: '...' });
   *   if (!confirmed) return;
   */
  confirm: (options: ConfirmOptions) => Promise<boolean>;
}

export const ConfirmContext = createContext<ConfirmContextValue | null>(null);

export function useConfirm() {
  const context = useContext(ConfirmContext);
  if (!context) {
    throw new Error('useConfirm must be used within a ConfirmProvider');
  }
  return context.confirm;
}
