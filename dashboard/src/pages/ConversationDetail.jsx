import { useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Clock, Globe, Cpu, Search,
  Image, Smartphone, Laptop, CheckCircle, Play,
  ChevronDown, ChevronUp,
} from 'lucide-react';
import MessageBubble from '../components/chat/MessageBubble';
import TourCardModal from '../components/chat/TourCardModal';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import { useConversationDetail, useConversationSearches } from '../hooks/useDashboardAPI';
import { formatDate, formatMs, COUNTRY_NAMES, DEPARTURE_NAMES } from '../lib/constants';

function parseUA(ua) {
  if (!ua) return { browser: '—', os: '—', device: 'unknown' };
  let browser = '—', os = '—', device = 'desktop';
  if (/Chrome\//.test(ua) && !/Edg/.test(ua)) browser = 'Chrome';
  else if (/Firefox\//.test(ua)) browser = 'Firefox';
  else if (/Safari\//.test(ua) && !/Chrome/.test(ua)) browser = 'Safari';
  else if (/Edg\//.test(ua)) browser = 'Edge';
  if (/Windows/.test(ua)) os = 'Windows';
  else if (/Mac OS/.test(ua)) os = 'macOS';
  else if (/Android/.test(ua)) { os = 'Android'; device = 'mobile'; }
  else if (/iPhone|iPad/.test(ua)) { os = 'iOS'; device = 'mobile'; }
  else if (/Linux/.test(ua)) os = 'Linux';
  return { browser, os, device };
}

function formatDuration(start, end) {
  if (!start || !end) return '—';
  const ms = new Date(end) - new Date(start);
  if (ms < 60000) return `${Math.round(ms / 1000)} сек`;
  if (ms < 3600000) return `${Math.round(ms / 60000)} мин`;
  return `${(ms / 3600000).toFixed(1)} ч`;
}

function DateSeparator({ date }) {
  return (
    <div className="flex items-center gap-3 my-4">
      <div className="flex-1 h-px bg-border/40" />
      <span className="text-[10px] font-medium text-text-secondary/60 px-2">{date}</span>
      <div className="flex-1 h-px bg-border/40" />
    </div>
  );
}

function SearchIndicator() {
  return (
    <div className="flex justify-center my-2 animate-fade-in">
      <div className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-primary-50 text-[11px] text-primary/70">
        <Search size={11} />
        <span>Ассистент выполнил поиск туров</span>
      </div>
    </div>
  );
}

function TimelineEvent({ icon: Icon, label, detail, color = 'bg-primary-50 text-primary', isLast }) {
  return (
    <div className="flex gap-2.5">
      <div className="flex flex-col items-center">
        <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${color}`}>
          <Icon size={11} />
        </div>
        {!isLast && <div className="w-px flex-1 bg-border/50 my-0.5" />}
      </div>
      <div className="pb-3 min-w-0">
        <p className="text-[11px] font-medium text-text leading-tight">{label}</p>
        {detail && <p className="text-[10px] text-text-secondary truncate">{detail}</p>}
      </div>
    </div>
  );
}

export default function ConversationDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: conv, loading } = useConversationDetail(id);
  const { data: searchesData } = useConversationSearches(id);
  const [selectedCard, setSelectedCard] = useState(null);
  const [showTechInfo, setShowTechInfo] = useState(false);

  const ua = useMemo(() => parseUA(conv?.user_agent), [conv?.user_agent]);
  const searches = searchesData?.searches || [];

  const dialogMessageCount = useMemo(() => {
    if (!conv?.messages) return conv?.message_count || 0;
    return conv.messages.filter((m) => m.role !== 'tool').length;
  }, [conv]);

  const funnelSteps = useMemo(() => {
    if (!conv) return [];
    return [
      { label: 'Сообщений', value: dialogMessageCount },
      { label: 'Поисков', value: conv.search_count || 0 },
      { label: 'Карточек', value: conv.tour_cards_shown || 0 },
    ];
  }, [conv, dialogMessageCount]);

  const timelineEvents = useMemo(() => {
    if (!conv) return [];
    const events = [];
    events.push({ icon: Play, label: 'Диалог начат', detail: formatDate(conv.started_at), color: 'bg-primary-50 text-primary' });

    const msgs = conv.messages || [];
    msgs.forEach((msg) => {
      if (msg.role === 'assistant' && msg.tool_calls?.length) {
        msg.tool_calls.forEach((tc) => {
          const fn = tc.function?.name || '';
          if (fn.includes('search') || fn.includes('hot')) {
            let args = {};
            try { args = JSON.parse(tc.function?.arguments || '{}'); } catch {}
            const country = args.country ? (COUNTRY_NAMES[args.country] || `#${args.country}`) : '';
            events.push({
              icon: Search,
              label: `Поиск: ${country || 'туры'}`,
              detail: formatDate(msg.created_at),
              color: 'bg-info-light text-info',
            });
          }
        });
      }
      if (msg.tour_cards?.length) {
        events.push({
          icon: Image,
          label: `Показано ${msg.tour_cards.length} карточ.`,
          detail: formatDate(msg.created_at),
          color: 'bg-success-light text-success',
        });
      }
    });

    events.push({ icon: CheckCircle, label: 'Диалог завершён', detail: formatDate(conv.last_active_at), color: 'bg-surface-sunken text-text-secondary' });
    return events;
  }, [conv]);

  const chatItems = useMemo(() => {
    if (!conv?.messages) return [];
    const items = [];
    let lastDateStr = '';
    for (const msg of conv.messages) {
      if (msg.created_at) {
        const dateStr = new Date(msg.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
        if (dateStr !== lastDateStr) {
          items.push({ type: 'separator', date: dateStr, key: `sep_${dateStr}` });
          lastDateStr = dateStr;
        }
      }
      if (msg.tour_cards?.length > 0) {
        items.push({ type: 'search_indicator', key: `search_${msg.id}` });
      }
      items.push({ type: 'message', msg, key: `msg_${msg.id}` });
    }
    return items;
  }, [conv?.messages]);

  const lastUserMsg = useMemo(() => {
    if (!conv?.messages) return null;
    const userMsgs = conv.messages.filter((m) => m.role === 'user');
    return userMsgs.length ? userMsgs[userMsgs.length - 1] : null;
  }, [conv?.messages]);

  if (loading) {
    return <div className="p-6"><LoadingSkeleton rows={10} /></div>;
  }
  if (!conv) {
    return <div className="p-6 text-text-secondary">Диалог не найден</div>;
  }

  return (
    <div className="space-y-4 animate-fade-in">
      <button
        onClick={() => navigate('/conversations')}
        className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-primary transition-colors group"
      >
        <ArrowLeft size={16} className="group-hover:-translate-x-0.5 transition-transform" />
        Назад к диалогам
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Chat replay */}
        <div className="lg:col-span-2 bg-surface-sunken rounded-2xl shadow-sm overflow-hidden">
          {/* Chat header */}
          <div className="px-5 py-3 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-3">
              <h2 className="text-sm font-semibold text-text">Переписка</h2>
              <span className="text-[10px] text-text-secondary bg-white/60 px-2 py-0.5 rounded-md">
                {dialogMessageCount} сообщений
              </span>
            </div>
            <span className="flex items-center gap-1 text-[10px] text-text-secondary bg-white/60 px-2 py-0.5 rounded-md">
              {ua.device === 'mobile' ? <Smartphone size={10} /> : <Laptop size={10} />}
              {ua.browser}
            </span>
          </div>

          {/* Messages */}
          <div className="p-5">
            {chatItems.map((item) =>
              item.type === 'separator' ? (
                <DateSeparator key={item.key} date={item.date} />
              ) : item.type === 'search_indicator' ? (
                <SearchIndicator key={item.key} />
              ) : (
                <MessageBubble
                  key={item.key}
                  message={item.msg}
                  onTourCardClick={(card) => setSelectedCard(card)}
                />
              )
            )}
            {chatItems.length === 0 && (
              <p className="text-sm text-text-secondary text-center py-8">Нет сообщений</p>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Client profile */}
          <div className="bg-white rounded-2xl shadow-sm p-5 space-y-4">
            <h3 className="text-sm font-semibold text-text">Профиль клиента</h3>

            <div className="flex items-center gap-3 pb-3 border-b border-border/40">
              <div className="w-10 h-10 rounded-xl bg-surface-sunken flex items-center justify-center">
                {ua.device === 'mobile' ? <Smartphone size={18} className="text-text-secondary" /> : <Laptop size={18} className="text-text-secondary" />}
              </div>
              <div>
                <p className="text-xs font-medium text-text">{ua.browser} · {ua.os}</p>
                <p className="text-[11px] text-text-secondary">{conv.ip_address || 'IP неизвестен'}</p>
              </div>
            </div>

            <div className="space-y-2.5">
              <InfoRow icon={Clock} label="Начало" value={formatDate(conv.started_at)} />
              <InfoRow icon={Clock} label="Длительность" value={formatDuration(conv.started_at, conv.last_active_at)} />
              <InfoRow icon={Clock} label="Ср. время отв." value={formatMs(conv.avg_latency_ms)} />
            </div>

            <div className="pt-2 border-t border-border/40">
              <button
                onClick={() => setShowTechInfo(!showTechInfo)}
                className="flex items-center gap-1 text-[11px] text-text-secondary/60 hover:text-text-secondary transition-colors"
              >
                {showTechInfo ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                Техническая информация
              </button>
              {showTechInfo && (
                <div className="mt-2 space-y-2 animate-fade-in">
                  <InfoRow icon={Cpu} label="Модель" value={`${conv.llm_provider} / ${conv.model}`} />
                  <InfoRow icon={Globe} label="Session" value={conv.session_id || '—'} />
                </div>
              )}
            </div>

            {lastUserMsg && (
              <div className="pt-3 border-t border-border/40">
                <p className="text-[10px] text-text-secondary mb-1">Последнее сообщение клиента:</p>
                <p className="text-xs text-text italic leading-relaxed line-clamp-2">
                  "{lastUserMsg.content?.slice(0, 120)}{lastUserMsg.content?.length > 120 ? '...' : ''}"
                </p>
              </div>
            )}
          </div>

          {/* Stats funnel */}
          <div className="bg-white rounded-2xl shadow-sm p-5">
            <h3 className="text-sm font-semibold text-text mb-3">Статистика диалога</h3>
            <div className="grid grid-cols-3 gap-2">
              {funnelSteps.map((step) => (
                <div key={step.label} className="text-center p-2 rounded-xl bg-surface-sunken/60">
                  <p className="text-lg font-bold text-text">{step.value}</p>
                  <p className="text-[10px] text-text-secondary">{step.label}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Client journey timeline */}
          {timelineEvents.length > 2 && (
            <div className="bg-white rounded-2xl shadow-sm p-5">
              <h3 className="text-sm font-semibold text-text mb-3">Путь клиента</h3>
              <div>
                {timelineEvents.map((ev, i) => (
                  <TimelineEvent
                    key={i}
                    icon={ev.icon}
                    label={ev.label}
                    detail={ev.detail}
                    color={ev.color}
                    isLast={i === timelineEvents.length - 1}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Tour searches */}
          {searches.length > 0 && (
            <div className="bg-white rounded-2xl shadow-sm p-5">
              <h3 className="text-sm font-semibold text-text mb-3">Поиски туров</h3>
              <div className="space-y-2.5">
                {searches.map((s) => (
                  <div key={s.id} className="text-xs bg-surface-sunken/60 rounded-xl p-3 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className={`font-semibold px-1.5 py-0.5 rounded-md text-[10px] ${
                        s.search_type === 'hot'
                          ? 'bg-warning-light text-warning'
                          : 'bg-primary-50 text-primary'
                      }`}>
                        {s.search_type === 'hot' ? 'Горящий' : 'Обычный'}
                      </span>
                      <span className="text-text-secondary text-[10px]">{formatDate(s.created_at)}</span>
                    </div>
                    {s.country && <div className="text-text">Страна: {COUNTRY_NAMES[s.country] || s.country}</div>}
                    {s.departure && <div>Вылет: {DEPARTURE_NAMES[s.departure] || s.departure}</div>}
                    {s.date_from && <div>Даты: {s.date_from} — {s.date_to || '?'}</div>}
                    {s.nights_from && <div>Ночей: {s.nights_from}—{s.nights_to}</div>}
                    {s.adults && <div>Туристы: {s.adults} взр.{s.children ? ` + ${s.children} дет.` : ''}</div>}
                    {s.price_to && <div>Бюджет до: {new Intl.NumberFormat('ru-RU').format(s.price_to)} ₽</div>}
                    {s.tours_found != null && (
                      <div className="pt-1 border-t border-border/40 mt-1 text-text-secondary">
                        Найдено: {s.hotels_found || 0} отелей, {s.tours_found || 0} туров
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Tour card modal */}
      {selectedCard && (
        <TourCardModal card={selectedCard} onClose={() => setSelectedCard(null)} />
      )}
    </div>
  );
}

function InfoRow({ icon: Icon, label, value }) {
  return (
    <div className="flex items-start gap-2.5 text-xs">
      <Icon size={13} className="text-primary/60 mt-0.5 shrink-0" />
      <span className="text-text-secondary shrink-0 min-w-[80px]">{label}</span>
      <span className="text-text font-medium break-all">{value}</span>
    </div>
  );
}
