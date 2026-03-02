import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import {
  PieChart, Pie, Cell, BarChart, Bar, AreaChart, Area, Line, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import MetricCard from '../components/ui/MetricCard';
import PeriodSelector from '../components/ui/PeriodSelector';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import EmptyState from '../components/ui/EmptyState';
import {
  useAnalyticsDestinations, useAnalyticsDepartures, useAnalyticsSearchParams,
  useAnalyticsResponseTimes, useAnalyticsSearchTypes,
  useAnalyticsDemand, useAnalyticsOperators, useAnalyticsActivity, useAnalyticsTravelDates,
  useAnalyticsBusinessMetrics,
} from '../hooks/useDashboardAPI';
import api from '../lib/api';
import { COUNTRY_NAMES, DEPARTURE_NAMES, MEAL_NAMES, STARS_LABELS, formatShortDate } from '../lib/constants';
import {
  MessageSquare, Clock, Globe, MapPin, BookmarkCheck,
  Moon, Users, Building2, Calendar, Download, TrendingUp,
  Wallet, Plane, UserCheck, X,
} from 'lucide-react';

const SEMANTIC_COLORS = [
  '#0038FF', '#F59E0B', '#10B981', '#EF4444', '#8B5CF6',
  '#EC4899', '#06B6D4', '#84CC16', '#F97316', '#6366F1',
];

const TOOLTIP_STYLE = {
  borderRadius: 12, border: 'none',
  boxShadow: '0 4px 12px rgba(0,56,255,0.08)', fontSize: 12,
};

function ChartCard({ title, subtitle, icon: Icon, children, className = '', action }) {
  return (
    <div className={`bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up ${className}`}>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            {Icon && (
              <div className="w-7 h-7 rounded-lg bg-primary-50 flex items-center justify-center">
                <Icon size={14} className="text-primary" />
              </div>
            )}
            <h3 className="text-sm font-semibold text-text">{title}</h3>
          </div>
          {subtitle && <p className="text-xs text-text-secondary mt-1 ml-9">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function DetailModal({ open, onClose, title, data, nameKey, valueKey }) {
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);
  const closingRef = useRef(false);

  const handleClose = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    setVisible(false);
    setTimeout(() => {
      setMounted(false);
      closingRef.current = false;
      document.body.style.overflow = '';
      onClose();
    }, 300);
  }, [onClose]);

  useEffect(() => {
    if (open) {
      setMounted(true);
      requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)));
      document.body.style.overflow = 'hidden';
      const onKey = (e) => { if (e.key === 'Escape') handleClose(); };
      window.addEventListener('keydown', onKey);
      return () => { window.removeEventListener('keydown', onKey); };
    }
  }, [open, handleClose]);

  if (!mounted) return null;

  const total = data.reduce((s, d) => s + d[valueKey], 0);
  const max = Math.max(...data.map((d) => d[valueKey]), 1);

  const handleBackdrop = (e) => { if (e.target === e.currentTarget) handleClose(); };

  return createPortal(
    <div
      className={`fixed inset-0 z-[9999] flex items-center justify-center p-4 transition-all duration-300 ease-out ${visible ? 'bg-black/40 backdrop-blur-sm' : 'bg-transparent backdrop-blur-0'}`}
      onClick={handleBackdrop}
    >
      <div role="dialog" aria-modal="true" aria-label={title} className={`bg-white rounded-3xl shadow-2xl w-full max-w-5xl max-h-[90vh] overflow-hidden transition-all duration-300 ease-out ${visible ? 'scale-100 opacity-100 translate-y-0' : 'scale-95 opacity-0 translate-y-4'}`}>
        <div className="flex items-center justify-between px-8 py-5 border-b border-border/30">
          <div>
            <h2 className="text-lg font-bold text-text">{title}</h2>
            <p className="text-sm text-text-secondary mt-0.5">Всего запросов: {total}</p>
          </div>
          <button onClick={handleClose} className="w-9 h-9 rounded-xl bg-surface-sunken hover:bg-red-50 flex items-center justify-center transition-colors group">
            <X size={18} className="text-text-secondary group-hover:text-red-500" />
          </button>
        </div>

        <div className="flex flex-col lg:flex-row" style={{ maxHeight: 'calc(90vh - 72px)' }}>
          <div className="lg:w-[45%] flex items-center justify-center px-6 py-8 lg:border-r border-border/20 shrink-0">
            <ResponsiveContainer width="100%" height={340}>
              <PieChart>
                <Pie data={data} dataKey={valueKey} nameKey={nameKey} cx="50%" cy="50%" outerRadius={140} innerRadius={75} paddingAngle={2} label={false} labelLine={false} isAnimationActive={true} activeIndex={-1} cursor="default">
                  {data.map((_, i) => <Cell key={i} fill={SEMANTIC_COLORS[i % SEMANTIC_COLORS.length]} stroke="white" strokeWidth={2} />)}
                </Pie>
                <Tooltip
                  contentStyle={{
                    borderRadius: 12, border: 'none', padding: '10px 16px',
                    backgroundColor: '#1E293B', color: '#fff',
                    boxShadow: '0 8px 24px rgba(0,0,0,0.2)', fontSize: 13,
                  }}
                  itemStyle={{ color: '#fff' }}
                  labelStyle={{ color: '#94A3B8', fontSize: 11, marginBottom: 2 }}
                  formatter={(val, name) => {
                    const pct = total > 0 ? Math.round(val / total * 100) : 0;
                    return [`${val} запросов (${pct}%)`, name];
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="lg:w-[55%] overflow-y-auto px-8 py-6">
            <div className="space-y-1">
              {data.map((item, i) => {
                const pct = total > 0 ? Math.round(item[valueKey] / total * 100) : 0;
                return (
                  <div key={i} className="flex items-center gap-3 py-2 px-3 -mx-3 rounded-xl hover:bg-surface-sunken/60 transition-colors">
                    <div className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: SEMANTIC_COLORS[i % SEMANTIC_COLORS.length] }} />
                    <span className="text-[13px] font-medium text-text flex-1 min-w-0">{item[nameKey]}</span>
                    <span className="text-xs text-text-secondary shrink-0 tabular-nums">{pct}%</span>
                    <span className="text-[13px] font-bold text-text shrink-0 w-8 text-right tabular-nums">{item[valueKey]}</span>
                    <div className="w-20 h-2 bg-surface-sunken rounded-full overflow-hidden shrink-0">
                      <div className="h-full rounded-full transition-all duration-500" style={{ width: `${(item[valueKey] / max) * 100}%`, backgroundColor: SEMANTIC_COLORS[i % SEMANTIC_COLORS.length] }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function HorizontalBarList({ data, nameKey, valueKey, defaultVisible = 5, suffix = '', modalTitle = '' }) {
  const [modalOpen, setModalOpen] = useState(false);
  if (!data?.length) return <EmptyState title="Нет данных" description="" />;

  const max = Math.max(...data.map((d) => d[valueKey]), 1);
  const hasMore = data.length > defaultVisible;
  const visible = data.slice(0, defaultVisible);

  return (
    <div>
      <div className="space-y-2.5">
        {visible.map((item, i) => (
          <div key={i}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-text truncate mr-2">{item[nameKey]}</span>
              <span className="text-xs font-semibold text-text whitespace-nowrap">
                {item[valueKey]}{suffix}
              </span>
            </div>
            <div className="h-2 bg-surface-sunken rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${(item[valueKey] / max) * 100}%`,
                  backgroundColor: SEMANTIC_COLORS[i % SEMANTIC_COLORS.length],
                }}
              />
            </div>
          </div>
        ))}
      </div>
      {hasMore && (
        <button
          onClick={() => setModalOpen(true)}
          className="mt-3 w-full text-center text-[11px] font-medium text-primary hover:text-primary/80 transition-colors py-1.5 rounded-lg hover:bg-primary-50"
        >
          Показать все ({data.length})
        </button>
      )}
      <DetailModal open={modalOpen} onClose={() => setModalOpen(false)} title={modalTitle || 'Детализация'} data={data} nameKey={nameKey} valueKey={valueKey} />
    </div>
  );
}

function SimplePie({ data, nameKey, valueKey }) {
  if (!data?.length) return <EmptyState title="Нет данных" description="" />;

  const RADIAN = Math.PI / 180;

  const renderCustomLabel = ({ cx, cy, midAngle, outerRadius, name, percent, fill }) => {
    const radius = outerRadius + 12;
    const endRadius = outerRadius + 30;
    const x1 = cx + radius * Math.cos(-midAngle * RADIAN);
    const y1 = cy + radius * Math.sin(-midAngle * RADIAN);
    const x2 = cx + endRadius * Math.cos(-midAngle * RADIAN);
    const y2 = cy + endRadius * Math.sin(-midAngle * RADIAN);
    const isRight = x2 > cx;
    const x3 = isRight ? x2 + 18 : x2 - 18;

    return (
      <g>
        <polyline
          points={`${x1},${y1} ${x2},${y2} ${x3},${y2}`}
          fill="none"
          stroke={fill}
          strokeWidth={1.5}
        />
        <text
          x={x3 + (isRight ? 4 : -4)}
          y={y2}
          textAnchor={isRight ? 'start' : 'end'}
          dominantBaseline="central"
          fill={fill}
          fontSize={12}
          fontWeight={600}
        >
          {name} {(percent * 100).toFixed(0)}%
        </text>
      </g>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie
          data={data}
          dataKey={valueKey}
          nameKey={nameKey}
          cx="50%"
          cy="50%"
          outerRadius={75}
          innerRadius={42}
          paddingAngle={3}
          label={renderCustomLabel}
          labelLine={false}
        >
          {data.map((_, i) => (
            <Cell key={i} fill={SEMANTIC_COLORS[i % SEMANTIC_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val) => [val, 'Поисков']} />
      </PieChart>
    </ResponsiveContainer>
  );
}

function HeatmapGrid({ heatmap, dayNames }) {
  const [tip, setTip] = useState(null);

  if (!heatmap?.length) return <EmptyState title="Нет данных" description="" />;
  const maxVal = Math.max(...heatmap.flat(), 1);

  const getColor = (val) => {
    if (val === 0) return '#F1F5F9';
    const ratio = val / maxVal;
    if (ratio < 0.25) return '#DBEAFE';
    if (ratio < 0.5) return '#93C5FD';
    if (ratio < 0.75) return '#3B82F6';
    return '#0038FF';
  };

  const hours = Array.from({ length: 24 }, (_, i) => i);

  const pluralize = (n) => {
    const mod = n % 10;
    const mod100 = n % 100;
    if (mod === 1 && mod100 !== 11) return 'диалог';
    if (mod >= 2 && mod <= 4 && (mod100 < 12 || mod100 > 14)) return 'диалога';
    return 'диалогов';
  };

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[600px]">
        <div className="flex gap-0.5 mb-1 ml-8">
          {hours.map((h) => (
            <div key={h} className="flex-1 text-center text-[9px] text-text-secondary">
              {h % 3 === 0 ? `${h}:00` : ''}
            </div>
          ))}
        </div>
        {dayNames?.map((day, dow) => (
          <div key={dow} className="flex items-center gap-0.5 mb-0.5">
            <span className="w-7 text-[10px] text-text-secondary text-right pr-1">{day}</span>
            {hours.map((h) => {
              const count = heatmap[dow]?.[h] || 0;
              return (
                <div
                  key={h}
                  className="flex-1 h-5 rounded-sm transition-all cursor-default hover:ring-2 hover:ring-primary/40 hover:z-10 hover:scale-110"
                  style={{ backgroundColor: getColor(count) }}
                  onMouseEnter={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect();
                    setTip({
                      x: rect.left + rect.width / 2,
                      y: rect.top - 8,
                      day, hour: h, count,
                    });
                  }}
                  onMouseLeave={() => setTip(null)}
                />
              );
            })}
          </div>
        ))}

        {tip && createPortal(
          <div
            className="fixed z-[9999] pointer-events-none animate-fade-in"
            style={{ left: tip.x, top: tip.y, transform: 'translate(-50%, -100%)' }}
          >
            <div className="flex flex-col items-center">
              <div className="bg-[#1E293B] text-white rounded-xl px-3 py-2 shadow-lg text-center whitespace-nowrap">
                <p className="text-[11px] font-semibold">{tip.day}, {tip.hour}:00</p>
                <p className="text-[12px] font-bold">{tip.count} {pluralize(tip.count)}</p>
              </div>
              <div className="w-0 h-0 border-l-[5px] border-r-[5px] border-t-[5px] border-l-transparent border-r-transparent border-t-[#1E293B]" />
            </div>
          </div>,
          document.body,
        )}

        <div className="flex items-center justify-end gap-1 mt-2">
          <span className="text-[9px] text-text-secondary">Меньше</span>
          {[0, 0.25, 0.5, 0.75, 1].map((r) => (
            <div
              key={r}
              className="w-3 h-3 rounded-sm"
              style={{ backgroundColor: getColor(r * maxVal) }}
            />
          ))}
          <span className="text-[9px] text-text-secondary">Больше</span>
        </div>
      </div>
    </div>
  );
}

function OperatorsChart({ data }) {
  const [modalOpen, setModalOpen] = useState(false);
  if (!data?.operators?.length) return <EmptyState title="Нет данных" description="" />;

  const defaultVisible = 5;
  const hasMore = data.operators.length > defaultVisible;
  const visible = data.operators.slice(0, defaultVisible);
  const maxCount = data.operators[0].count;

  const modalData = data.operators.map((op) => ({ name: op.operator, value: op.count }));

  return (
    <div>
      <div className="space-y-2.5">
        {visible.map((op, i) => (
          <div key={i}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-text truncate mr-2">{op.operator}</span>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-text-secondary">{op.share}%</span>
                <span className="text-xs font-semibold text-text">{op.count}</span>
              </div>
            </div>
            <div className="h-2 bg-surface-sunken rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${(op.count / maxCount) * 100}%`,
                  backgroundColor: SEMANTIC_COLORS[i % SEMANTIC_COLORS.length],
                }}
              />
            </div>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-text-secondary text-center pt-2">
        Всего показано карточек: {data.total_cards}
      </p>
      {hasMore && (
        <button
          onClick={() => setModalOpen(true)}
          className="mt-1 w-full text-center text-[11px] font-medium text-primary hover:text-primary/80 transition-colors py-1.5 rounded-lg hover:bg-primary-50"
        >
          Показать все ({data.operators.length})
        </button>
      )}
      <DetailModal open={modalOpen} onClose={() => setModalOpen(false)} title="Туроператоры в результатах" data={modalData} nameKey="name" valueKey="value" />
    </div>
  );
}

const ALL_STARS = [5, 4, 3, 2];
const ALL_MEALS = [1, 2, 3, 4, 5, 6, 7, 8, 9];
const MEAL_SHORT = { 1: 'RO', 2: 'BB', 3: 'HB', 4: 'FB', 5: 'AI', 6: 'UAI', 7: 'HB+', 8: 'FB+', 9: 'AI+' };

function CombinationGrid({ combos }) {
  const [tip, setTip] = useState(null);

  const lookup = {};
  let maxVal = 1;
  if (combos?.length) {
    for (const c of combos) {
      lookup[`${c.stars}-${c.meal}`] = c.count;
      if (c.count > maxVal) maxVal = c.count;
    }
  }

  const getOpacity = (v) => {
    if (!v) return 0;
    return 0.15 + (v / maxVal) * 0.85;
  };

  const pluralize = (n) => {
    const mod = n % 10;
    const mod100 = n % 100;
    if (mod === 1 && mod100 !== 11) return 'запрос';
    if (mod >= 2 && mod <= 4 && (mod100 < 12 || mod100 > 14)) return 'запроса';
    return 'запросов';
  };

  return (
    <div className="overflow-x-auto relative">
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className="text-left text-text-secondary font-medium pb-2 pr-2"></th>
            {ALL_MEALS.map((m) => (
              <th key={m} className="text-center text-text-secondary font-medium pb-2 px-0.5 whitespace-nowrap text-[10px]">
                {MEAL_SHORT[m]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ALL_STARS.map((s) => (
            <tr key={s}>
              <td className="text-text font-medium pr-2 py-1 whitespace-nowrap">{STARS_LABELS[s] || `${s}★`}</td>
              {ALL_MEALS.map((m) => {
                const val = lookup[`${s}-${m}`] || 0;
                return (
                  <td key={m} className="text-center py-1 px-0.5">
                    <div
                      className="rounded-md px-1.5 py-1 font-semibold text-xs cursor-default transition-all hover:ring-2 hover:ring-primary/40 hover:scale-105"
                      style={{
                        backgroundColor: val ? `rgba(0, 56, 255, ${getOpacity(val)})` : '#F1F5F9',
                        color: val && val / maxVal > 0.5 ? '#fff' : val ? '#0038FF' : '#94A3B8',
                      }}
                      onMouseEnter={(e) => {
                        const rect = e.currentTarget.getBoundingClientRect();
                        setTip({ x: rect.left + rect.width / 2, y: rect.top - 8, stars: s, meal: m, count: val });
                      }}
                      onMouseLeave={() => setTip(null)}
                    >
                      {val || '—'}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      {tip && createPortal(
        <div
          className="fixed z-[9999] pointer-events-none animate-fade-in"
          style={{ left: tip.x, top: tip.y, transform: 'translate(-50%, -100%)' }}
        >
          <div className="flex flex-col items-center">
            <div className="bg-[#1E293B] text-white rounded-xl px-3 py-2 shadow-lg text-center whitespace-nowrap">
              <p className="text-[11px] font-semibold">{STARS_LABELS[tip.stars]} × {MEAL_SHORT[tip.meal]} ({MEAL_NAMES[tip.meal]?.split('(')[0]?.trim()})</p>
              <p className="text-[12px] font-bold">{tip.count ? `${tip.count} ${pluralize(tip.count)}` : 'Нет запросов'}</p>
            </div>
            <div className="w-0 h-0 border-l-[5px] border-r-[5px] border-t-[5px] border-l-transparent border-r-transparent border-t-[#1E293B]" />
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

function BudgetVsPrice({ data }) {
  if (!data?.avg_budget && !data?.avg_found) return null;
  const saving = data.avg_budget && data.avg_found && data.avg_budget > data.avg_found
    ? Math.round((1 - data.avg_found / data.avg_budget) * 100)
    : null;

  return (
    <div className="bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-7 h-7 rounded-lg bg-primary-50 flex items-center justify-center">
          <Wallet size={14} className="text-primary" />
        </div>
        <h3 className="text-sm font-semibold text-text">Бюджет vs найденная цена</h3>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {data.avg_budget && (
          <div>
            <p className="text-[10px] text-text-secondary mb-0.5">Средний бюджет</p>
            <p className="text-lg font-bold text-text">{Math.round(data.avg_budget).toLocaleString('ru-RU')} ₽</p>
          </div>
        )}
        {data.avg_found && (
          <div>
            <p className="text-[10px] text-text-secondary mb-0.5">Средняя мин. цена</p>
            <p className="text-lg font-bold text-primary">{Math.round(data.avg_found).toLocaleString('ru-RU')} ₽</p>
          </div>
        )}
      </div>
      {saving != null && saving > 0 && (
        <div className="mt-3 pt-3 border-t border-border/30">
          <p className="text-xs text-success font-medium">
            AI находит варианты на {saving}% дешевле запрошенного бюджета
          </p>
        </div>
      )}
    </div>
  );
}

function ExportButton({ period }) {
  const [loading, setLoading] = useState(false);

  const handleExport = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/dashboard/export/conversations', {
        params: { period },
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = 'conversations.csv';
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [period]);

  return (
    <button
      onClick={handleExport}
      disabled={loading}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary-50 text-primary text-xs font-medium hover:bg-primary/10 transition-colors disabled:opacity-50"
    >
      <Download size={12} />
      {loading ? 'Загрузка...' : 'CSV'}
    </button>
  );
}

export default function Analytics() {
  const [period, setPeriod] = useState('30d');

  const { data: destData, loading: loadDest } = useAnalyticsDestinations(period);
  const { data: depData, loading: loadDep } = useAnalyticsDepartures(period);
  const { data: paramsData, loading: loadParams } = useAnalyticsSearchParams(period);
  const { data: rtData, loading: loadRT } = useAnalyticsResponseTimes(period);
  const { data: typesData } = useAnalyticsSearchTypes(period);
  const { data: demandData, loading: loadDemand } = useAnalyticsDemand(period);
  const { data: operatorsData, loading: loadOps } = useAnalyticsOperators(period);
  const { data: activityData, loading: loadActivity } = useAnalyticsActivity(period);
  const { data: travelDatesData, loading: loadTravelDates } = useAnalyticsTravelDates(period);
  const { data: bizData } = useAnalyticsBusinessMetrics(period);

  const destinations = (destData?.data || []).map((r) => ({
    name: COUNTRY_NAMES[r.country_code] || `#${r.country_code}`,
    value: r.count,
  }));

  const departures = (depData?.data || []).map((r) => ({
    name: DEPARTURE_NAMES[r.departure_code] || `#${r.departure_code}`,
    value: r.count,
  }));

  const starsChart = (paramsData?.stars || []).map((r) => ({
    name: STARS_LABELS[r.stars] || `${r.stars}★`,
    count: r.count,
  }));

  const mealsChart = (paramsData?.meals || []).map((r) => ({
    name: MEAL_NAMES[r.meal] || `#${r.meal}`,
    count: r.count,
  }));

  const budgetsChart = paramsData?.budgets || [];

  const SEARCH_TYPE_LABELS = {
    regular: 'Обычный поиск',
    hot: 'Горящие туры',
    hotel: 'Поиск отеля',
    without_flight: 'Без перелёта',
  };
  const searchTypes = (typesData?.types || []).map((r) => ({
    name: SEARCH_TYPE_LABELS[r.type] || r.type,
    value: r.count,
  }));

  const nightsData = demandData?.nights_distribution || [];
  const groupData = demandData?.group_sizes || [];

  const mskHour = new Date(new Date().toLocaleString('en-US', { timeZone: 'Europe/Moscow' })).getHours();
  const updateLabel = mskHour >= 19 ? 'сегодня в 19:00' : mskHour >= 12 ? 'сегодня в 12:00' : 'вчера в 19:00';

  const topInsights = useMemo(() => {
    const items = [];
    if (destinations.length > 0) {
      items.push(`Топ-направление: ${destinations[0].name} (${destinations[0].value} поисков)`);
    }
    if (typesData?.avg_budget) {
      items.push(`Средний бюджет клиентов: ${new Intl.NumberFormat('ru-RU').format(typesData.avg_budget)} ₽`);
    }
    if (typesData?.avg_nights) {
      const n = typesData.avg_nights;
      const word = n % 10 === 1 && n !== 11 ? 'ночь' : (n % 10 >= 2 && n % 10 <= 4 && (n < 10 || n > 20)) ? 'ночи' : 'ночей';
      items.push(`Средняя длительность: ${n} ${word}`);
    }
    if (bizData?.engagement_pct != null && bizData.engagement_pct > 0) {
      items.push(`Вовлечённость: ${bizData.engagement_pct}% клиентов вели активный диалог`);
    }
    if (bizData?.after_hours_pct != null && bizData.after_hours_pct > 0) {
      items.push(`${bizData.after_hours_pct}% обращений вне рабочих часов`);
    }
    return items.slice(0, 5);
  }, [destinations, typesData, bizData]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-text">Аналитика</h1>
          <p className="text-sm text-text-secondary mt-0.5">Эффективность AI-ассистента и анализ спроса</p>
        </div>
        <div className="flex items-center gap-3">
          <ExportButton period={period} />
          <PeriodSelector value={period} onChange={setPeriod} />
        </div>
      </div>

      <div key={period} className="space-y-6">

      {/* Business-value metric cards — top row: Results */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="animate-fade-in-up stagger-1 h-full">
          <MetricCard
            title="Обработано обращений"
            tooltip="Количество клиентских обращений, обработанных ассистентом"
            value={bizData?.inquiries_handled ?? '—'}
            icon={MessageSquare}
          />
        </div>
        <div className="animate-fade-in-up stagger-2 h-full">
          <MetricCard
            title="Туров подобрано"
            tooltip="Сколько вариантов туров ассистент подобрал и показал клиентам"
            value={bizData?.tours_offered ?? '—'}
            icon={Plane}
          />
        </div>
        <div className="animate-fade-in-up stagger-3 h-full">
          <MetricCard
            title="Потенциальные лиды"
            tooltip="Клиенты, которые активно общались и получили подборку — горячие лиды"
            value={bizData?.potential_leads ?? '—'}
            icon={UserCheck}
            valueColor={bizData?.potential_leads > 0 ? 'text-success' : undefined}
          />
        </div>
      </div>

      {/* Business-value metric cards — bottom row: Value */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="animate-fade-in-up stagger-4 h-full">
          <MetricCard
            title="Работа 24/7"
            tooltip="Обращения вне рабочего времени (до 9:00, после 18:00) — без AI были бы потеряны"
            value={bizData?.after_hours_pct != null ? `${bizData.after_hours_pct}%` : '—'}
            icon={Clock}
            subtitle={bizData?.after_hours_count ? `${bizData.after_hours_count} обращ. вне часов` : undefined}
          />
        </div>
        <div className="animate-fade-in-up stagger-5 h-full">
          <MetricCard
            title="Запросы на бронь"
            tooltip="Количество диалогов, в которых клиент проявил интерес к бронированию тура — запрос контакта менеджера, подтверждение выбора или прямой запрос на оформление"
            value={bizData?.booking_intents ?? '—'}
            icon={BookmarkCheck}
            valueColor={bizData?.booking_intents > 0 ? 'text-success' : undefined}
            subtitle={bizData?.booking_intent_pct ? `${bizData.booking_intent_pct}% от обращений` : undefined}
          />
        </div>
        <div className="animate-fade-in-up stagger-6 h-full">
          <MetricCard
            title="Вовлечённость"
            tooltip="Процент посетителей, которые активно вовлеклись в диалог (2+ сообщений)"
            value={bizData?.engagement_pct != null ? `${bizData.engagement_pct}%` : '—'}
            icon={TrendingUp}
            valueColor={bizData?.engagement_pct > 20 ? 'text-success' : bizData?.engagement_pct > 10 ? 'text-warning' : undefined}
            subtitle={bizData?.engaged_count ? `${bizData.engaged_count} из ${bizData.total_conversations}` : undefined}
          />
        </div>
      </div>

      {/* Quick insights */}
      {topInsights.length > 0 && (
        <div className="bg-white rounded-2xl shadow-sm p-4 animate-fade-in-up stagger-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <TrendingUp size={14} className="text-primary" />
              <span className="text-xs font-semibold text-text">Ключевые выводы:</span>
            </div>
            <span className="text-[10px] text-text-secondary">Обновлено: {updateLabel}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {topInsights.map((t, i) => (
              <span key={i} className="text-xs px-2.5 py-1 rounded-lg bg-primary-50 text-primary font-medium">{t}</span>
            ))}
          </div>
        </div>
      )}

      {/* Geography */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Популярные страны" subtitle="Куда ваши клиенты хотят путешествовать" icon={Globe}>
          {loadDest ? <LoadingSkeleton rows={3} /> : <HorizontalBarList data={destinations} nameKey="name" valueKey="value" modalTitle="Популярные страны" />}
        </ChartCard>
        <ChartCard title="Города вылета" subtitle="Откуда летят ваши клиенты" icon={MapPin}>
          {loadDep ? <LoadingSkeleton rows={3} /> : <HorizontalBarList data={departures} nameKey="name" valueKey="value" modalTitle="Города вылета" />}
        </ChartCard>
      </div>

      {/* Demand analytics: nights + group sizes */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Распределение по ночам" subtitle="Какую длительность выбирают клиенты" icon={Moon}>
          {loadDemand ? <LoadingSkeleton rows={3} /> : nightsData.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={nightsData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="nights" tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false}
                  label={{ value: 'ночей', position: 'insideBottomRight', offset: -5, fontSize: 10, fill: '#94A3B8' }} />
                <YAxis tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val) => [val, 'Поисков']} />
                <Bar dataKey="count" radius={[6, 6, 0, 0]} fill="#0038FF" isAnimationActive={true} />
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyState title="Нет данных" description="" />}
        </ChartCard>

        <ChartCard title="Размер группы" subtitle="Состав путешественников" icon={Users}>
          {loadDemand ? <LoadingSkeleton rows={3} /> :
            <HorizontalBarList data={groupData} nameKey="group" valueKey="count" modalTitle="Размер группы" />
          }
        </ChartCard>
      </div>

      {/* Search params: stars, meals, budget */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Звёздность отелей" subtitle="Предпочтения по категории отелей">
          {loadParams ? <LoadingSkeleton rows={3} /> : starsChart.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={starsChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val) => [val, 'Поисков']} />
                <Bar dataKey="count" radius={[6, 6, 0, 0]} isAnimationActive={true}>
                  {starsChart.map((_, i) => (
                    <Cell key={i} fill={SEMANTIC_COLORS[i % SEMANTIC_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyState title="Нет данных" description="" />}
        </ChartCard>

        <ChartCard title="Тип питания" subtitle="Предпочтения по питанию">
          {loadParams ? <LoadingSkeleton rows={3} /> : mealsChart.length ? (
            <HorizontalBarList data={mealsChart} nameKey="name" valueKey="count" modalTitle="Тип питания" />
          ) : <EmptyState title="Нет данных" description="" />}
        </ChartCard>
      </div>

      {/* Stars x Meal + Budget */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Звёзды × Питание" subtitle="Популярные комбинации запросов">
          {loadParams ? <LoadingSkeleton rows={3} /> :
            <CombinationGrid combos={paramsData?.stars_meal_combos} />
          }
        </ChartCard>

        <ChartCard title="Бюджет клиентов" subtitle="Распределение по ценовым диапазонам">
          {budgetsChart.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={budgetsChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="range" tick={{ fontSize: 10 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val) => [val, 'Поисков']} />
                <Bar dataKey="count" radius={[6, 6, 0, 0]} isAnimationActive={true}>
                  {budgetsChart.map((_, i) => (
                    <Cell key={i} fill={SEMANTIC_COLORS[i % SEMANTIC_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyState title="Нет данных" description="" />}
        </ChartCard>
      </div>

      {/* Search types + Travel dates */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Типы поисков" subtitle="Распределение по способам поиска">
          {searchTypes.length ? (
            <div>
              <SimplePie data={searchTypes} nameKey="name" valueKey="value" />
              {typesData?.avg_nights && (
                <p className="text-xs text-text-secondary text-center mt-2">
                  Средняя длительность: {typesData.avg_nights} {typesData.avg_nights % 10 === 1 && typesData.avg_nights !== 11 ? 'ночь' : (typesData.avg_nights % 10 >= 2 && typesData.avg_nights % 10 <= 4 && (typesData.avg_nights < 10 || typesData.avg_nights > 20)) ? 'ночи' : 'ночей'}
                </p>
              )}
            </div>
          ) : <EmptyState title="Нет данных" description="" />}
        </ChartCard>

        <ChartCard title="Востребованные даты вылета" subtitle="В какие месяцы клиенты хотят путешествовать" icon={Calendar}>
          {loadTravelDates ? <LoadingSkeleton rows={3} /> : travelDatesData?.data?.length ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={travelDatesData.data}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="month" tick={{ fontSize: 10 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val) => [val, 'Запросов']} />
                <Bar dataKey="count" radius={[6, 6, 0, 0]} isAnimationActive={true}>
                  {travelDatesData.data.map((_, i) => (
                    <Cell key={i} fill={SEMANTIC_COLORS[i % SEMANTIC_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyState title="Нет данных" description="" />}
        </ChartCard>
      </div>

      {/* Budget vs Price (shown only when data exists) */}
      <BudgetVsPrice data={paramsData?.budget_vs_price} />

      {/* Activity heatmap */}
      <ChartCard
        title="Активность по часам и дням"
        subtitle="Когда ваши клиенты обращаются к ассистенту"
        icon={Calendar}
      >
        {loadActivity ? <LoadingSkeleton rows={5} /> :
          <HeatmapGrid heatmap={activityData?.heatmap} dayNames={activityData?.day_names} />
        }
      </ChartCard>

      {/* Day-of-week distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Распределение по дням недели">
          {activityData?.day_distribution?.length ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={activityData.day_distribution}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val) => [val, 'Диалогов']} />
                <Bar dataKey="count" radius={[6, 6, 0, 0]} fill="#0038FF" isAnimationActive={true} />
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyState title="Нет данных" description="" />}
        </ChartCard>

        <ChartCard title="Распределение по часам">
          {activityData?.hour_distribution?.length ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={activityData.hour_distribution}>
                <defs>
                  <linearGradient id="colorHour" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0038FF" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#0038FF" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="hour" tick={{ fontSize: 10 }} stroke="#94A3B8" axisLine={false} tickLine={false}
                  tickFormatter={(h) => `${h}:00`} />
                <YAxis tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE}
                  labelFormatter={(h) => `${h}:00`}
                  formatter={(val) => [val, 'Диалогов']} />
                <Area type="monotone" dataKey="count" stroke="#0038FF" strokeWidth={2} fill="url(#colorHour)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : <EmptyState title="Нет данных" description="" />}
        </ChartCard>
      </div>

      {/* Tour operators */}
      <ChartCard
        title="Туроператоры в результатах"
        subtitle="Какие операторы чаще всего появляются в выдаче"
        icon={Building2}
      >
        {loadOps ? <LoadingSkeleton rows={5} /> : <OperatorsChart data={operatorsData} />}
      </ChartCard>

      {/* Response times with P50/P90 */}
      <ChartCard title="Время ответа по дням" subtitle="Среднее, медиана (P50) и 90-й перцентиль (P90)">
        {loadRT ? <LoadingSkeleton rows={3} /> : rtData?.data?.length ? (
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={rtData.data}>
              <defs>
                <linearGradient id="colorRt" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#0038FF" stopOpacity={0.12} />
                  <stop offset="95%" stopColor="#0038FF" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
              <XAxis dataKey="date" tickFormatter={formatShortDate} tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11 }} stroke="#94A3B8" unit="мс" axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelFormatter={formatShortDate}
                formatter={(val, name) => {
                  const labels = { avg_ms: 'Среднее', p50_ms: 'Медиана (P50)', p90_ms: '90-й перц. (P90)' };
                  return [`${val} мс`, labels[name] || name];
                }}
              />
              <Area type="monotone" dataKey="avg_ms" stroke="#0038FF" strokeWidth={2} fill="url(#colorRt)" isAnimationActive={true} />
              <Line type="monotone" dataKey="p50_ms" stroke="#10B981" strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
              <Line type="monotone" dataKey="p90_ms" stroke="#F59E0B" strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
              <Legend
                verticalAlign="top"
                height={30}
                formatter={(value) => {
                  const labels = { avg_ms: 'Среднее', p50_ms: 'P50', p90_ms: 'P90' };
                  return <span className="text-[10px] text-text-secondary">{labels[value] || value}</span>;
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        ) : <EmptyState title="Нет данных" description="" />}
      </ChartCard>

      </div>
    </div>
  );
}
