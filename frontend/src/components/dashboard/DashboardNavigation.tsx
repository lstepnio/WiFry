import type { DashboardTabOption } from './config';
import type { Tab } from './config';

export function SubTabNav<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: DashboardTabOption<T>[];
  active: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="mb-5 flex gap-1 border-b border-gray-800 pb-2">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`rounded-t px-4 py-1.5 text-sm font-medium transition-colors ${
            active === tab.id
              ? 'border-b-2 border-blue-500 text-blue-400'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function DashboardHeader({
  tabs,
  currentTab,
  onTabChange,
}: {
  tabs: DashboardTabOption<Tab>[];
  currentTab: Tab;
  onTabChange: (tab: Tab) => void;
}) {
  return (
    <header className="border-b border-gray-200 bg-white px-6 py-3 dark:border-gray-800 dark:bg-gray-900">
      <div className="mx-auto flex max-w-6xl items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-lg font-bold text-white">
            W
          </div>
          <div>
            <h1 className="text-lg font-bold leading-tight text-gray-900 dark:text-white">WiFry</h1>
            <p className="text-[10px] text-gray-500 dark:text-gray-500">IP Video Edition</p>
          </div>
        </div>

        <nav className="flex gap-0.5">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              title={tab.desc}
              onClick={() => onTabChange(tab.id)}
              className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors ${
                currentTab === tab.id
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}
