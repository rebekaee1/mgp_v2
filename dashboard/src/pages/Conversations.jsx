import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, MessageSquare, Clock, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';
import DataTable from '../components/ui/DataTable';
import EmptyState from '../components/ui/EmptyState';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import { useConversations } from '../hooks/useDashboardAPI';
import { formatDate, formatRelativeTime } from '../lib/constants';

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
  const [hasSearch, setHasSearch] = useState(undefined);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [sortBy, setSortBy] = useState('started_at');
  const [sortDir, setSortDir] = useState('desc');
  const navigate = useNavigate();

  const { data, loading } = useConversations(page, 20, period, hasSearch, searchQuery, sortBy, sortDir);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setSearchQuery(searchInput);
    setPage(1);
  };

  const handleSort = (field, dir) => {
    setSortBy(field);
    setSortDir(dir);
    setPage(1);
  };

  const columns = [
    {
      key: 'status_dot',
      label: '',
      render: (row) => {
        const hasCards = row.tour_cards_shown > 0;
        const hasSearches = row.search_count > 0;
        const color = hasCards ? 'bg-success' : hasSearches ? 'bg-primary' : 'bg-text-secondary/30';
        return <span className={`block w-2 h-2 rounded-full ${color}`} />;
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
    { key: 'tour_cards_shown', label: 'Карточки' },
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

  const totalAll = data?.total || 0;
  const totalWithSearch = data?.total_with_search || 0;
  const totalWithCards = data?.total_with_cards || 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-bold text-text">Диалоги</h1>
        <div className="flex items-center gap-2 flex-wrap">
          <form onSubmit={handleSearchSubmit} className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-secondary" />
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Поиск по содержимому..."
              className="h-8 pl-8 pr-3 w-48 sm:w-56 text-xs border border-border/60 rounded-xl bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
            />
          </form>

          <select
            value={hasSearch === undefined ? '' : hasSearch}
            onChange={(e) => {
              const v = e.target.value;
              setHasSearch(v === '' ? undefined : v);
              setPage(1);
            }}
            className="h-8 text-xs border border-border/60 rounded-xl px-2.5 bg-white text-text focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="">Все</option>
            <option value="true">С поиском</option>
            <option value="false">Без поиска</option>
          </select>

          <div className="flex bg-white rounded-xl p-0.5 shadow-xs">
            {[
              { value: 'all', label: 'Все' },
              { value: '7d', label: '7д' },
              { value: '30d', label: '30д' },
              { value: '90d', label: '90д' },
            ].map((p) => (
              <button
                key={p.value}
                onClick={() => { setPeriod(p.value); setPage(1); }}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                  period === p.value
                    ? 'bg-primary text-white shadow-sm'
                    : 'text-text-secondary hover:text-text'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Summary stats strip + legend */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3 text-[11px] text-text-secondary">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-success" />Карточки показаны</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-primary" />Были поиски</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-text-secondary/30" />Только чат</span>
        </div>
        {!loading && data && (
          <div className="flex items-center gap-2">
            <span className="text-[11px] px-2 py-0.5 rounded-lg bg-surface-sunken text-text-secondary font-medium">
              Всего: {totalAll}
            </span>
            <span className="text-[11px] px-2 py-0.5 rounded-lg bg-primary-50 text-primary font-medium">
              С поисками: {totalWithSearch}
            </span>
            <span className="text-[11px] px-2 py-0.5 rounded-lg bg-success-light text-success font-medium">
              С карточками: {totalWithCards}
            </span>
          </div>
        )}
      </div>

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
  );
}
