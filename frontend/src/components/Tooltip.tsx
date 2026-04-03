import { useState } from 'react';

export default function Tooltip({ text, children }: { text: string; children: React.ReactNode }) {
  const [show, setShow] = useState(false);

  return (
    <span className="relative inline-flex items-center"
      onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
      {children}
      {show && (
        <span className="absolute bottom-full left-1/2 z-50 mb-2 -translate-x-1/2 whitespace-normal rounded-lg bg-gray-800 px-3 py-2 text-xs text-gray-200 shadow-lg" style={{ minWidth: '200px', maxWidth: '300px' }}>
          {text}
          <span className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-gray-800" />
        </span>
      )}
    </span>
  );
}

export function HelpIcon({ text }: { text: string }) {
  return (
    <Tooltip text={text}>
      <span className="ml-1 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-gray-700 text-[10px] font-bold text-gray-400 hover:bg-gray-600 hover:text-white">?</span>
    </Tooltip>
  );
}
