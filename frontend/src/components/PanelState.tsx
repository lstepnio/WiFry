interface PanelStateProps {
  title: string;
  message: string;
  variant?: 'loading' | 'error' | 'empty';
}

const VARIANT_STYLES = {
  loading: 'border-blue-800 bg-blue-950/30 text-blue-200',
  error: 'border-red-800 bg-red-950/30 text-red-200',
  empty: 'border-gray-700 bg-gray-900 text-gray-300',
};

export default function PanelState({ title, message, variant = 'loading' }: PanelStateProps) {
  return (
    <div className={`rounded-lg border p-6 shadow-sm ${VARIANT_STYLES[variant]}`}>
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mt-2 text-sm opacity-90">{message}</p>
    </div>
  );
}
