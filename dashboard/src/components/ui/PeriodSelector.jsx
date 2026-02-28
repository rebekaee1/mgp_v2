import { useState } from 'react';
import { Calendar } from 'lucide-react';

const PERIODS = [
  { value: '7d', label: '7 дней' },
  { value: '30d', label: '30 дней' },
  { value: '90d', label: '90 дней' },
];

export default function PeriodSelector({ value, onChange, showCustom = false, onCustomRange }) {
  const [customOpen, setCustomOpen] = useState(false);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const handleCustomApply = () => {
    if (dateFrom && dateTo && onCustomRange) {
      onCustomRange(dateFrom, dateTo);
      setCustomOpen(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <div className="flex bg-white rounded-xl p-0.5 shadow-xs">
        {PERIODS.map((p) => (
          <button
            key={p.value}
            onClick={() => { onChange(p.value); setCustomOpen(false); }}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              value === p.value && !customOpen
                ? 'bg-primary text-white shadow-sm'
                : 'text-text-secondary hover:text-text'
            }`}
          >
            {p.label}
          </button>
        ))}
        {showCustom && (
          <button
            onClick={() => setCustomOpen(!customOpen)}
            className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              customOpen
                ? 'bg-primary text-white shadow-sm'
                : 'text-text-secondary hover:text-text'
            }`}
          >
            <Calendar size={12} />
            <span className="hidden sm:inline">Период</span>
          </button>
        )}
      </div>

      {customOpen && (
        <div className="flex items-center gap-1.5 animate-fade-in">
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="h-7 px-2 text-xs border border-border rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <span className="text-xs text-text-secondary">—</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="h-7 px-2 text-xs border border-border rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <button
            onClick={handleCustomApply}
            disabled={!dateFrom || !dateTo}
            className="h-7 px-2.5 text-xs font-medium bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors disabled:opacity-40"
          >
            ОК
          </button>
        </div>
      )}
    </div>
  );
}
