import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, X, MessageSquare, Clock, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';
import DataTable from '../components/ui/DataTable';
import EmptyState from '../components/ui/EmptyState';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import PeriodSelector from '../components/ui/PeriodSelector';
import { useConversations } from '../hooks/useDashboardAPI';
import { formatDate, formatRelativeTime } from '../lib/constants';

const CONV_PERIODS = [
  { value: 'all', label: 'Все' },
  { value: '7d', label: '7 дней' },
  { value: '30d', label: '30 дней' },
  { value: '90d', label: '90 дней' },
];

function formatDuration(start, end) {
  if (!start || !end) return '—';
  const ms = new Date(end) - new Date(start);
  if (ms < 60000) return `${Math.round(ms / 1000)}с`;
  if (ms < 3600000) return `${Math.round(ms / 60000)} мин`;
  return `${(ms / 3600000).toFixed(1)} ч`;
}

function SortHeader({ label, field, currentSort, currentDir, onSort }) {
  const isActive = currentSort === field;
  return (
    <button
      onClick={() => onSort(field, isActive && currentDir === 'desc' ? 'asc' : 'desc')}
      className="flex items-center gap-1 text-[11px] font-semibold text-text-secondary uppercase tracking-wider hover:text-primary transition-colors group"
    >
      {label}
      {isActive ? (
        currentDir === 'desc' ? <ArrowDown size={11} className="text-primary" /> : <ArrowUp size={11} className="text-primary" />
      ) : (
        <ArrowUpDown size={10} className="opacity-0 group-hover:opacity-50 transition-opacity" />
      )}
    </button>
  );
}

export default function Conversations() {
  const [page, setPage] = useState(1);
  const [period, setPeriod] = useState('all');
  const [hasCards, setHasCards] = useState(undefined);
  const [hasBooking, setHasBooking] = useState(undefined);
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('started_at');
  const [sortDir, setSortDir] = useState('desc');
  const [tableVisible, setTableVisible] = useState(true);
  const prevFilterRef = useRef('undefined-undefined');
  const navigate = useNavigate();
  const inputRef = useRef(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      const q = searchInput.trim();
      const next = q.length >= 2 ? q : '';
      if (next !== searchQuery) {
        setSearchQuery(next);
        setPage(1);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const filterKey = `${hasCards}-${hasBooking}`;
  useEffect(() => {
    if (prevFilterRef.current !== filterKey) {
      setTableVisible(false);
      prevFilterRef.current = filterKey;
    }
  }, [filterKey]);

  const { data, loading } = useConversations(page, 20, period, searchQuery, sortBy, sortDir, hasBooking, hasCards);

  useEffect(() => {
    if (!loading && data) {
      const t = setTimeout(() => setTableVisible(true), 50);
      return () => clearTimeout(t);
    }
  }, [loading, data]);

  const clearSearch = () => {
    setSearchInput('');
    inputRef.current?.focus();
  };

  const handleSort = (field, dir) => {
    setSortBy(field);
    setSortDir(dir);
    setPage(1);
  };

  const activeFilterColor =
    hasCards === 'true' ? 'bg-amber-400'
    : hasBooking === 'true' ? 'bg-success'
    : null;

  const columns = [
    {
      key: 'status_dot',
      label: '',
      render: (row) => {
        if (activeFilterColor) {
          return <span className={`block w-2 h-2 rounded-full ${activeFilterColor} transition-colors duration-200`} />;
        }
        const bk = row.has_booking_intent;
        const cd = row.tour_cards_shown > 0;
        const color = bk ? 'bg-success' : cd ? 'bg-amber-400' : 'bg-text-secondary/30';
        return <span className={`block w-2 h-2 rounded-full ${color} transition-colors duration-200`} />;
      },
    },
    {
      key: 'started_at',
      label: <SortHeader label="Дата" field="started_at" currentSort={sortBy} currentDir={sortDir} onSort={handleSort} />,
      render: (row) => (
        <div>
          <span className="text-xs block">{formatDate(row.started_at)}</span>
          <span className="text-[10px] text-text-secondary">{formatRelativeTime(row.started_at)}</span>
        </div>
      ),
    },
    {
      key: 'preview',
      label: 'Первое сообщение',
      render: (row) => (
        <div className="max-w-[280px] group/preview relative">
          <span className="text-xs truncate block">{row.preview || '—'}</span>
          {row.last_user_message && row.last_user_message !== row.preview && (
            <span className="text-[10px] text-text-secondary truncate block mt-0.5">
              Посл.: {row.last_user_message}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'message_count',
      label: <SortHeader label="Сообщ." field="message_count" currentSort={sortBy} currentDir={sortDir} onSort={handleSort} />,
      render: (row) => (
        <span className="flex items-center gap-1 text-xs">
          <MessageSquare size={11} className="text-text-secondary" />{row.message_count}
        </span>
      ),
    },
    {
      key: 'search_count',
      label: <SortHeader label="Поиски" field="search_count" currentSort={sortBy} currentDir={sortDir} onSort={handleSort} />,
    },
    {
      key: 'tour_cards_shown',
      label: 'Карточки',
      render: (row) => (
        <span className={`text-xs tabular-nums ${hasCards === 'true' ? 'font-semibold text-amber-600' : ''}`}>
          {row.tour_cards_shown}
        </span>
      ),
    },
    {
      key: 'duration',
      label: 'Длительн.',
      render: (row) => (
        <span className="flex items-center gap-1 text-xs text-text-secondary">
          <Clock size={11} />
          {formatDuration(row.started_at, row.last_active_at)}
        </span>
      ),
    },
  ];

  const totalAll = data?.total_all ?? data?.total ?? 0;
  const totalWithCards = data?.total_with_cards || 0;
  const totalWithBooking = data?.total_with_booking || 0;
  const isFiltered = hasCards === 'true' || hasBooking === 'true';
  const filteredCount = data?.total || 0;
  const activeFilterLabel =
    hasCards === 'true' ? 'с карточками'
    : hasBooking === 'true' ? 'с запросами на бронь'
    : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3 animate-fade-in-up">
        <h1 className="text-xl font-bold text-text">Диалоги</h1>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative">
            <Search size={14} className={`absolute left-2.5 top-1/2 -translate-y-1/2 transition-colors ${loading && searchQuery ? 'text-primary animate-pulse' : 'text-text-secondary'}`} />
            <input
              ref={inputRef}
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Поиск по сообщениям, странам, городам..."
              className="h-8 pl-8 pr-8 w-52 sm:w-64 text-xs border border-border/60 rounded-xl bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
            />
            {searchInput && (
              <button
                onClick={clearSearch}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded-full text-text-secondary hover:text-text hover:bg-border/30 transition-all"
                title="Очистить поиск"
              >
                <X size={13} />
              </button>
            )}
          </div>

          <PeriodSelector
            value={period}
            onChange={(v) => { setPeriod(v); setPage(1); }}
            periods={CONV_PERIODS}
          />
        </div>
      </div>

      {/* Clickable filter badges + legend */}
      <div className="flex items-center justify-between flex-wrap gap-3 animate-fade-in-up stagger-1">
        <div className="flex items-center gap-3 text-[11px] text-text-secondary flex-wrap">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-success" />Запрос на бронь</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-amber-400" />Карточки показаны</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-text-secondary/30" />Только чат</span>
        </div>
        {!loading && data && (
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => { setHasCards(undefined); setHasBooking(undefined); setPage(1); }}
              className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                hasCards === undefined && hasBooking === undefined
                  ? 'bg-text text-white shadow-sm'
                  : 'bg-surface-sunken text-text-secondary hover:bg-border/50'
              }`}
            >
              Всего: {totalAll}
            </button>
            <button
              onClick={() => {
                const active = hasCards === 'true' && hasBooking === undefined;
                setHasCards(active ? undefined : 'true');
                setHasBooking(undefined);
                setPage(1);
              }}
              className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                hasCards === 'true' && hasBooking === undefined
                  ? 'bg-amber-400 text-white shadow-sm'
                  : 'bg-amber-50 text-amber-600 hover:bg-amber-100'
              }`}
            >
              С карточками: {totalWithCards}
            </button>
            <button
              onClick={() => {
                const active = hasBooking === 'true' && hasCards === undefined;
                setHasBooking(active ? undefined : 'true');
                setHasCards(undefined);
                setPage(1);
              }}
              className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                hasBooking === 'true' && hasCards === undefined
                  ? 'bg-success text-white shadow-sm'
                  : 'bg-success-light text-success hover:bg-success/10'
              }`}
            >
              Запросы на бронь: {totalWithBooking}
            </button>
          </div>
        )}
      </div>

      {isFiltered && !loading && data && (
        <div className="flex items-center gap-2 text-[11px] text-text-secondary animate-fade-in-up">
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${activeFilterColor}`} />
          <span>
            Показано <span className="font-semibold text-text">{filteredCount}</span> из {totalAll} диалогов {activeFilterLabel}
          </span>
        </div>
      )}

      <div
        className="transition-all duration-300 ease-out"
        style={{
          opacity: tableVisible && !loading ? 1 : 0,
          transform: tableVisible && !loading ? 'translateY(0)' : 'translateY(6px)',
        }}
      >
        {loading ? (
          <LoadingSkeleton rows={8} />
        ) : data?.items?.length ? (
          <DataTable
            columns={columns}
            rows={data.items}
            page={data.page}
            pages={data.pages}
            onPageChange={setPage}
            onRowClick={(row) => navigate(`/conversations/${row.id}`)}
          />
        ) : (
          <EmptyState
            title="Нет диалогов"
            description={searchQuery
              ? `Ничего не найдено по запросу "${searchQuery}". Попробуйте другой запрос.`
              : 'Диалоги появятся после первого общения клиентов с виджетом на вашем сайте.'
            }
          />
        )}
      </div>
    </div>
  );
}
