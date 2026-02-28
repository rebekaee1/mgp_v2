import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare, Search, Clock, MessagesSquare, ArrowRight, TrendingUp, Zap, Users } from 'lucide-react';
import { LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import MetricCard, { CardSkeleton } from '../components/ui/MetricCard';
import EmptyState from '../components/ui/EmptyState';
import StatusBadge from '../components/ui/StatusBadge';
import PeriodSelector from '../components/ui/PeriodSelector';
import { useOverview, useOverviewChart, useRecentConversations, useFetch } from '../hooks/useDashboardAPI';
import { useAuth } from '../hooks/useAuth';
import { formatNumber, formatMs, formatDate, formatShortDate } from '../lib/constants';

function getGreeting() {
  const h = new Date().getHours();
  if (h < 6) return 'Доброй ночи';
  if (h < 12) return 'Доброе утро';
  if (h < 18) return 'Добрый день';
  return 'Добрый вечер';
}

function ConversionFunnel({ funnel }) {
  const steps = [
    { label: 'Все диалоги', value: funnel?.total || 0, color: 'bg-primary' },
    { label: 'Вовлечённые (2+ сообщ.)', value: funnel?.engaged || 0, color: 'bg-[#1A4FFF]' },
    { label: 'С поиском туров', value: funnel?.with_search || 0, color: 'bg-[#3B82F6]' },
    { label: 'С результатами', value: funnel?.with_results || 0, color: 'bg-[#60A5FA]' },
    { label: 'Потенциальные лиды', value: funnel?.potential_leads || 0, color: 'bg-[#93C5FD]' },
  ];
  const max = Math.max(...steps.map((s) => s.value), 1);

  return (
    <div className="space-y-2.5">
      {steps.map((step, i) => {
        const pct = max > 0 ? (step.value / max) * 100 : 0;
        const convRate = i > 0 && steps[i - 1].value > 0
          ? ((step.value / steps[i - 1].value) * 100).toFixed(0)
          : null;
        return (
          <div key={step.label}>
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[11px] font-medium text-text">{step.label}</span>
              <div className="flex items-center gap-2">
                {convRate !== null && (
                  <span className="text-[10px] text-text-secondary">{convRate}%</span>
                )}
                <span className="text-xs font-semibold text-text">{formatNumber(step.value)}</span>
              </div>
            </div>
            <div className="h-2 bg-surface-sunken rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${step.color} transition-all duration-700`}
                style={{ width: `${Math.max(pct, 2)}%` }}
              />
            </div>
          </div>
        );
      })}
      {funnel?.total > 0 && funnel?.potential_leads > 0 && (
        <div className="pt-2 border-t border-border/30 mt-1">
          <p className="text-[10px] text-text-secondary text-center">
            Общая конверсия: <span className="font-semibold text-primary">{((funnel.potential_leads / funnel.total) * 100).toFixed(1)}%</span>
          </p>
        </div>
      )}
    </div>
  );
}

function InsightCard({ insights, funnel }) {
  const items = useMemo(() => {
    if (!insights && !funnel) return [];
    const list = [];
    if (funnel?.engaged > 0 && funnel?.total > 0) {
      const pct = Math.round((funnel.engaged / funnel.total) * 100);
      list.push(`${pct}% посетителей вовлекаются в диалог — отправляют 2 и более сообщений`);
    }
    if (funnel?.with_search > 0 && funnel?.total > 0) {
      const pct = Math.round((funnel.with_search / funnel.total) * 100);
      list.push(`${pct}% диалогов содержат поиск туров`);
    }
    if (insights?.after_hours_pct > 0) {
      list.push(`${Math.round(insights.after_hours_pct)}% диалогов проходят вне рабочего времени (до 9:00 и после 18:00)`);
    }
    if (insights?.avg_duration_minutes > 0) {
      const mins = insights.avg_duration_minutes;
      const durationText = mins < 1
        ? `${Math.round(mins * 60)} секунд`
        : mins < 2
        ? `около 1 минуты`
        : `${Math.round(mins)} минут`;
      list.push(`Средняя длительность диалога: ${durationText}`);
    }
    if (insights?.avg_user_messages > 0) {
      list.push(`Среднее количество сообщений от клиента: ${Math.round(insights.avg_user_messages)}`);
    }
    return list;
  }, [insights, funnel]);

  if (!items.length) return null;
  return (
    <div className="bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-6">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-7 h-7 rounded-lg bg-warning-light flex items-center justify-center">
          <Zap size={14} className="text-warning" />
        </div>
        <h3 className="text-sm font-semibold text-text">Быстрые инсайты</h3>
      </div>
      <div className="space-y-2">
        {items.map((item, i) => {
          const text = typeof item === 'string' ? item : item.text;
          const colorClass = typeof item === 'object' ? item.color : 'text-primary';
          return (
            <p key={i} className="text-xs text-text-secondary leading-relaxed flex items-start gap-2">
              <TrendingUp size={12} className={`${colorClass} mt-0.5 shrink-0`} />
              {text}
            </p>
          );
        })}
      </div>
    </div>
  );
}

export default function Overview() {
  const [period, setPeriod] = useState('30d');
  const [chartMetric, setChartMetric] = useState('conversations');
  const navigate = useNavigate();
  const { user } = useAuth();

  const { data: overview, loading: loadingOverview } = useOverview(period);
  const { data: chartData, loading: loadingChart } = useOverviewChart(period, chartMetric);
  const { data: recent, loading: loadingRecent } = useRecentConversations(5);
  const { data: health } = useFetch('/dashboard/system/health');

  const sparklineConv = useOverviewChart(period, 'conversations');
  const sparklineMsg = useOverviewChart(period, 'messages');
  const sparklineSrch = useOverviewChart(period, 'searches');

  const funnel = overview?.funnel || null;
  const apiInsights = overview?.insights || null;

  return (
    <div className="space-y-6">
      {/* Greeting + period */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-text">
            {getGreeting()}, {user?.name || 'Администратор'}
          </h1>
          <p className="text-sm text-text-secondary mt-0.5">
            Вот что происходит с вашим AI-ассистентом
          </p>
        </div>
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      <div key={period} className="space-y-6">

      {/* Metric cards with sparklines */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {loadingOverview ? (
          Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} />)
        ) : (
          <>
            <div className="animate-fade-in-up stagger-1 h-full">
              <MetricCard
                title="Диалогов"
                value={formatNumber(overview?.conversations?.value)}
                delta={overview?.conversations?.delta}
                icon={MessagesSquare}
                sparklineData={sparklineConv.data?.data}
              />
            </div>
            <div className="animate-fade-in-up stagger-2 h-full">
              <MetricCard
                title="Сообщений"
                value={formatNumber(overview?.messages?.value)}
                icon={MessageSquare}
                sparklineData={sparklineMsg.data?.data}
              />
            </div>
            <div className="animate-fade-in-up stagger-3 h-full">
              <MetricCard
                title="Поисков туров"
                value={formatNumber(overview?.searches?.value)}
                icon={Search}
                sparklineData={sparklineSrch.data?.data}
              />
            </div>
            <div className="animate-fade-in-up stagger-4 h-full">
              <MetricCard
                title="Среднее время ответа"
                value={formatMs(overview?.avg_response_ms?.value)}
                icon={Clock}
              />
            </div>
          </>
        )}
      </div>

      {/* Chart + funnel + health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-text">Динамика</h3>
            <div className="flex bg-surface-sunken rounded-xl p-0.5">
              {[
                { value: 'conversations', label: 'Диалоги' },
                { value: 'messages', label: 'Сообщения' },
                { value: 'searches', label: 'Поиски' },
              ].map((m) => (
                <button
                  key={m.value}
                  onClick={() => setChartMetric(m.value)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                    chartMetric === m.value
                      ? 'bg-primary text-white shadow-sm'
                      : 'text-text-secondary hover:text-text'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          {loadingChart ? (
            <div className="h-56 flex items-center justify-center text-text-secondary text-sm">Загрузка...</div>
          ) : chartData?.data?.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={chartData.data}>
                <defs>
                  <linearGradient id="colorVal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0038FF" stopOpacity={0.12} />
                    <stop offset="95%" stopColor="#0038FF" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="date" tickFormatter={formatShortDate} tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11 }} stroke="#94A3B8" axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ borderRadius: 12, border: 'none', boxShadow: '0 4px 12px rgba(0,56,255,0.08)', fontSize: 12 }}
                  labelFormatter={formatShortDate}
                  formatter={(val) => {
                    const labels = { conversations: 'Диалогов', messages: 'Сообщений', searches: 'Поисков' };
                    return [val, labels[chartMetric] || 'Значение'];
                  }}
                />
                <Area type="monotone" dataKey="value" stroke="#0038FF" strokeWidth={2} fill="url(#colorVal)" isAnimationActive={true} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-56 flex items-center justify-center text-text-secondary text-sm">Нет данных за выбранный период</div>
          )}
        </div>

        <div className="space-y-4">
          {/* Conversion funnel */}
          <div className="bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-5">
            <h3 className="text-sm font-semibold text-text mb-3">Воронка конверсии</h3>
            <ConversionFunnel funnel={funnel} />
          </div>

          {/* Compact system health */}
          <div className="bg-white rounded-2xl shadow-sm p-4 animate-fade-in-up stagger-6">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-text">Статус системы</span>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-text-secondary">DB</span>
                  <span className={`w-2 h-2 rounded-full ${health?.postgres === 'ok' ? 'bg-success' : 'bg-danger'} animate-pulse`} />
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-text-secondary">Cache</span>
                  <span className={`w-2 h-2 rounded-full ${health?.redis === 'ok' ? 'bg-success' : 'bg-danger'} animate-pulse`} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Insights */}
      <InsightCard insights={apiInsights} funnel={funnel} />

      {/* Recent conversations */}
      <div className="bg-white rounded-2xl shadow-sm animate-fade-in-up">
        <div className="flex items-center justify-between px-5 py-4">
          <h3 className="text-sm font-semibold text-text">Последние диалоги</h3>
          <button
            onClick={() => navigate('/conversations')}
            className="flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-dark transition-colors"
          >
            Все диалоги
            <ArrowRight size={12} />
          </button>
        </div>

        {loadingRecent ? (
          <div className="p-5 text-sm text-text-secondary">Загрузка...</div>
        ) : recent?.conversations?.length ? (
          <div className="border-t border-border/40">
            {recent.conversations.map((conv) => {
              const hasCards = conv.tour_cards_shown > 0;
              const hasSearches = conv.search_count > 0;
              const dotColor = hasCards ? 'bg-success' : hasSearches ? 'bg-primary' : 'bg-text-secondary/30';

              return (
                <div
                  key={conv.id}
                  onClick={() => navigate(`/conversations/${conv.id}`)}
                  className="flex items-center gap-3 px-5 py-3 cursor-pointer hover:bg-primary-50/30 transition-colors border-b border-border/30 last:border-0"
                >
                  <span className={`w-2 h-2 rounded-full ${dotColor} shrink-0`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text truncate">{conv.preview || 'Без текста'}</p>
                    <p className="text-[11px] text-text-secondary mt-0.5">{formatDate(conv.started_at)}</p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0 text-[11px] text-text-secondary">
                    <span className="flex items-center gap-1"><MessageSquare size={10} />{conv.message_count}</span>
                    <span className="flex items-center gap-1"><Search size={10} />{conv.search_count}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState
            title="Ещё нет диалогов"
            description="Ваш AI-ассистент готов к работе. Диалоги появятся, когда клиенты начнут общаться."
          />
        )}
      </div>

      </div>
    </div>
  );
}
