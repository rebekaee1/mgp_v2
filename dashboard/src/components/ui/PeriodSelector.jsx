import { useState, useRef, useEffect, useCallback } from 'react';
import { Calendar } from 'lucide-react';

const DEFAULT_PERIODS = [
  { value: '7d', label: '7 дней' },
  { value: '30d', label: '30 дней' },
  { value: '90d', label: '90 дней' },
];

export default function PeriodSelector({ value, onChange, showCustom = false, onCustomRange, periods }) {
  const PERIODS = periods || DEFAULT_PERIODS;
  const [customOpen, setCustomOpen] = useState(false);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const containerRef = useRef(null);
  const [indicatorStyle, setIndicatorStyle] = useState({});

  const updateIndicator = useCallback(() => {
    if (!containerRef.current || customOpen) return;
    const active = containerRef.current.querySelector('[data-active="true"]');
    if (active) {
      const containerRect = containerRef.current.getBoundingClientRect();
      const activeRect = active.getBoundingClientRect();
      setIndicatorStyle({
        left: activeRect.left - containerRect.left,
        width: activeRect.width,
        opacity: 1,
      });
    }
  }, [value, customOpen]);

  useEffect(() => {
    updateIndicator();
  }, [updateIndicator]);

  const handleCustomApply = () => {
    if (dateFrom && dateTo && onCustomRange) {
      onCustomRange(dateFrom, dateTo);
      setCustomOpen(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <div ref={containerRef} className="relative flex bg-white rounded-xl p-0.5 shadow-xs">
        <div
          className="absolute top-0.5 h-[calc(100%-4px)] rounded-lg bg-primary shadow-sm transition-all duration-300 ease-out"
          style={{ ...indicatorStyle, opacity: indicatorStyle.opacity ?? 0 }}
        />
        {PERIODS.map((p) => (
          <button
            key={p.value}
            data-active={value === p.value && !customOpen}
            onClick={() => { onChange(p.value); setCustomOpen(false); }}
            className={`relative z-10 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors duration-200 ${
              value === p.value && !customOpen
                ? 'text-white'
                : 'text-text-secondary hover:text-text'
            }`}
          >
            {p.label}
          </button>
        ))}
        {showCustom && (
          <button
            onClick={() => setCustomOpen(!customOpen)}
            className={`relative z-10 flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
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
