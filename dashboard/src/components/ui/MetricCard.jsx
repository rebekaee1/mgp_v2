import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { TrendingUp, TrendingDown, HelpCircle } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer } from 'recharts';

function TooltipPortal({ anchor, children, visible }) {
  const [pos, setPos] = useState(null);

  useEffect(() => {
    if (!visible || !anchor.current) { setPos(null); return; }
    const rect = anchor.current.getBoundingClientRect();
    setPos({
      top: rect.bottom + 8 + window.scrollY,
      left: rect.left + rect.width / 2 + window.scrollX,
    });
  }, [visible, anchor]);

  if (!visible || !pos) return null;
  return createPortal(
    <div
      className="fixed z-[9999] pointer-events-none animate-fade-in"
      style={{ top: pos.top - window.scrollY, left: pos.left, transform: 'translateX(-50%)' }}
    >
      <div className="flex flex-col items-center">
        <div className="w-0 h-0 border-l-[6px] border-r-[6px] border-b-[6px] border-l-transparent border-r-transparent border-b-[#1E293B]" />
        <div className="w-52 px-3.5 py-2.5 rounded-xl bg-[#1E293B] text-white text-[11px] leading-relaxed shadow-xl">
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default function MetricCard({ title, value, delta, icon: Icon, suffix, sparklineData, valueColor, tooltip, subtitle, className = '' }) {
  const [showTip, setShowTip] = useState(false);
  const helpRef = useRef(null);

  return (
    <div className={`bg-white rounded-2xl shadow-sm hover:shadow-md transition-all duration-200 p-5 flex flex-col gap-2 group h-full border-l-[3px] border-primary/50 group-hover:border-primary ${className}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-[13px] text-text-secondary font-medium">{title}</span>
          {tooltip && (
            <div
              ref={helpRef}
              onMouseEnter={() => setShowTip(true)}
              onMouseLeave={() => setShowTip(false)}
              className="relative"
            >
              <HelpCircle
                size={13}
                className="text-text-secondary/40 hover:text-primary cursor-help transition-colors shrink-0"
              />
              <TooltipPortal anchor={helpRef} visible={showTip}>
                {tooltip}
              </TooltipPortal>
            </div>
          )}
        </div>
        {Icon && (
          <div className="w-9 h-9 rounded-xl bg-primary-50 flex items-center justify-center">
            <Icon size={18} className="text-primary" strokeWidth={1.8} />
          </div>
        )}
      </div>

      <div className="flex items-end justify-between gap-2 mt-auto">
        <div className="flex items-end gap-2 min-w-0">
          <span className={`text-2xl font-bold animate-count-up ${valueColor || 'text-text'}`}>{value}{suffix}</span>
          {delta != null && delta !== 0 && (
            <span className={`flex items-center gap-0.5 text-[11px] font-semibold px-1.5 py-0.5 rounded-full mb-0.5 ${
              delta > 0 ? 'text-success bg-success-light' : 'text-danger bg-danger-light'
            }`}>
              {delta > 0 ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
              {delta > 0 ? '+' : ''}{delta}%
            </span>
          )}
        </div>

        {sparklineData && sparklineData.length > 1 && (
          <div className="w-20 h-8 shrink-0 opacity-60 group-hover:opacity-100 transition-opacity">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={sparklineData}>
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#0038FF"
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={true}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {subtitle && (
        <p className="text-[11px] text-text-secondary">{subtitle}</p>
      )}
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="bg-white rounded-2xl shadow-sm p-5 animate-pulse">
      <div className="h-3 w-24 bg-surface-sunken rounded mb-3" />
      <div className="h-7 w-16 bg-surface-sunken rounded" />
    </div>
  );
}
