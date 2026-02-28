import { useState, useRef, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { Menu, Search, ChevronRight, LogOut, User, Settings, Clock } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { useNavigate } from 'react-router-dom';

const ROUTE_META = {
  '/': { title: 'Обзор', breadcrumbs: [] },
  '/conversations': { title: 'Диалоги', breadcrumbs: [] },
  '/analytics': { title: 'Аналитика', breadcrumbs: [] },
  '/widget': { title: 'Настройки виджета', breadcrumbs: [] },
  '/system': { title: 'Статус системы', breadcrumbs: [] },
  '/account': { title: 'Аккаунт', breadcrumbs: [] },
};

function getRouteMeta(pathname) {
  if (pathname.startsWith('/conversations/') && pathname.length > '/conversations/'.length) {
    return {
      title: 'Детали диалога',
      breadcrumbs: [{ label: 'Диалоги', to: '/conversations' }],
    };
  }
  return ROUTE_META[pathname] || { title: '', breadcrumbs: [] };
}

function useRelativeTime() {
  const [now, setNow] = useState(Date.now());
  const [lastFetch, setLastFetch] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);

  const markFetched = () => setLastFetch(Date.now());
  const diffSec = Math.floor((now - lastFetch) / 1000);

  let label;
  if (diffSec < 60) label = 'Только что';
  else if (diffSec < 3600) label = `${Math.floor(diffSec / 60)} мин. назад`;
  else label = `${Math.floor(diffSec / 3600)} ч. назад`;

  return { label, markFetched };
}

export default function Header({ onMobileMenuToggle, onSearchOpen }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);
  const meta = getRouteMeta(location.pathname);
  const { label: lastUpdated } = useRelativeTime();

  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        onSearchOpen?.();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onSearchOpen]);

  const initials = (user?.name || user?.email || 'U').charAt(0).toUpperCase();

  return (
    <header className="flex items-center justify-between h-14 px-4 lg:px-6 bg-white/80 backdrop-blur-sm border-b border-border/60 shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onMobileMenuToggle}
          className="lg:hidden p-1.5 -ml-1 rounded-lg text-text-secondary hover:text-text hover:bg-surface-sunken transition-colors"
        >
          <Menu size={20} />
        </button>

        <div className="flex items-center gap-1.5 text-sm min-w-0">
          {meta.breadcrumbs.map((bc, i) => (
            <span key={i} className="flex items-center gap-1.5 shrink-0">
              <button
                onClick={() => navigate(bc.to)}
                className="text-text-secondary hover:text-primary transition-colors"
              >
                {bc.label}
              </button>
              <ChevronRight size={12} className="text-text-secondary/50" />
            </span>
          ))}
          <h1 className="font-semibold text-text truncate">{meta.title}</h1>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <div className="hidden sm:flex items-center gap-1.5 text-xs text-text-secondary mr-1">
          <Clock size={12} />
          <span>{lastUpdated}</span>
        </div>

        <button
          onClick={onSearchOpen}
          className="flex items-center gap-2 h-8 px-3 rounded-lg bg-surface-sunken text-text-secondary text-xs hover:bg-border/40 transition-colors"
        >
          <Search size={14} />
          <span className="hidden sm:inline">Поиск</span>
          <kbd className="hidden md:inline text-[10px] bg-white px-1 py-0.5 rounded border border-border/60 font-mono ml-1">⌘K</kbd>
        </button>

        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-[#3B82F6] flex items-center justify-center text-white text-xs font-semibold hover:shadow-md transition-shadow"
          >
            {initials}
          </button>

          {dropdownOpen && (
            <div className="absolute right-0 top-full mt-1.5 w-48 bg-white rounded-xl shadow-lg border border-border/60 py-1 z-50 animate-fade-in-up">
              <div className="px-3 py-2 border-b border-border/60">
                <p className="text-xs font-medium text-text truncate">{user?.name || user?.email}</p>
                <p className="text-[10px] text-text-secondary">{user?.company?.name}</p>
              </div>
              <button
                onClick={() => { setDropdownOpen(false); navigate('/account'); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-text-secondary hover:bg-surface-sunken hover:text-text transition-colors"
              >
                <User size={13} />
                Профиль
              </button>
              <button
                onClick={() => { setDropdownOpen(false); navigate('/widget'); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-text-secondary hover:bg-surface-sunken hover:text-text transition-colors"
              >
                <Settings size={13} />
                Настройки
              </button>
              <div className="border-t border-border/60 mt-1 pt-1">
                <button
                  onClick={() => { setDropdownOpen(false); logout(); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-danger hover:bg-danger-light transition-colors"
                >
                  <LogOut size={13} />
                  Выйти
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
