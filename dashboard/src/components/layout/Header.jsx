import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router-dom';
import { Menu, Search, ChevronRight, LogOut, User, Settings, Clock, BarChart3, Code2 } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { useDataFreshness, useRelativeTimeLabel } from '../../lib/dataFreshness';

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

function useRealFreshness() {
  const ts = useDataFreshness();
  const label = useRelativeTimeLabel(ts);
  return { label };
}

function ProfileDropdown({ anchorRef, open, onClose, user, onNavigate, onLogout }) {
  const [visible, setVisible] = useState(false);
  const [mounted, setMounted] = useState(false);
  const menuRef = useRef(null);
  const [pos, setPos] = useState({ top: 0, right: 0 });

  useEffect(() => {
    if (open) {
      setMounted(true);
      if (anchorRef.current) {
        const rect = anchorRef.current.getBoundingClientRect();
        setPos({ top: rect.bottom + 8, right: window.innerWidth - rect.right });
      }
      requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)));
    } else {
      setVisible(false);
      const timer = setTimeout(() => setMounted(false), 200);
      return () => clearTimeout(timer);
    }
  }, [open, anchorRef]);

  useEffect(() => {
    if (!mounted) return;
    const handler = (e) => {
      if (
        menuRef.current && !menuRef.current.contains(e.target) &&
        anchorRef.current && !anchorRef.current.contains(e.target)
      ) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [mounted, onClose, anchorRef]);

  useEffect(() => {
    if (!mounted) return;
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [mounted, onClose]);

  if (!mounted) return null;

  const initials = (user?.name || user?.email || 'U').charAt(0).toUpperCase();

  const items = [
    { icon: User, label: 'Профиль', to: '/account' },
    { icon: BarChart3, label: 'Аналитика', to: '/analytics' },
    { icon: Code2, label: 'Настройки виджета', to: '/widget' },
  ];

  return createPortal(
    <div
      ref={menuRef}
      className="fixed z-[9999]"
      style={{ top: pos.top, right: pos.right }}
    >
      <div
        className={`w-56 bg-white rounded-2xl shadow-xl border border-border/50 overflow-hidden transition-all duration-200 ease-out origin-top-right ${
          visible ? 'opacity-100 scale-100 translate-y-0' : 'opacity-0 scale-95 -translate-y-1'
        }`}
      >
        <div className="px-4 py-3 bg-gradient-to-br from-primary/5 to-transparent">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary to-[#3B82F6] flex items-center justify-center text-white text-sm font-semibold shrink-0">
              {initials}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-text truncate">{user?.name || user?.email}</p>
              <p className="text-xs text-text-secondary truncate">{user?.company?.name || 'AIMPACT+'}</p>
            </div>
          </div>
        </div>

        <div className="py-1.5 px-1.5">
          {items.map(({ icon: Icon, label, to }, i) => (
            <button
              key={i}
              onClick={() => { onClose(); onNavigate(to); }}
              className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-text-secondary hover:bg-surface-sunken hover:text-text rounded-lg transition-colors"
            >
              <Icon size={15} strokeWidth={1.7} className="shrink-0" />
              {label}
            </button>
          ))}
        </div>

        <div className="border-t border-border/50 px-1.5 py-1.5">
          <button
            onClick={() => { onClose(); onLogout(); }}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-danger hover:bg-red-50 rounded-lg transition-colors"
          >
            <LogOut size={15} strokeWidth={1.7} className="shrink-0" />
            Выйти
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

export default function Header({ onMobileMenuToggle, onSearchOpen }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const avatarRef = useRef(null);
  const meta = getRouteMeta(location.pathname);
  const { label: lastUpdated } = useRealFreshness();

  const closeDropdown = useCallback(() => setDropdownOpen(false), []);

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

  useEffect(() => { setDropdownOpen(false); }, [location.pathname]);

  const initials = (user?.name || user?.email || 'U').charAt(0).toUpperCase();

  return (
    <header className="flex items-center justify-between h-14 px-4 lg:px-6 bg-white/80 backdrop-blur-sm border-b border-border/60 shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onMobileMenuToggle}
          aria-label="Открыть меню"
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
          aria-label="Поиск"
          className="flex items-center gap-2 h-8 px-3 rounded-lg bg-surface-sunken text-text-secondary text-xs hover:bg-border/40 transition-colors"
        >
          <Search size={14} />
          <span className="hidden sm:inline">Поиск</span>
          <kbd className="hidden md:inline text-[10px] bg-white px-1 py-0.5 rounded border border-border/60 font-mono ml-1">⌘K</kbd>
        </button>

        <button
          ref={avatarRef}
          onClick={() => setDropdownOpen(!dropdownOpen)}
          aria-label="Меню пользователя"
          aria-expanded={dropdownOpen}
          aria-haspopup="true"
          className={`w-8 h-8 rounded-full bg-gradient-to-br from-primary to-[#3B82F6] flex items-center justify-center text-white text-xs font-semibold transition-all ${
            dropdownOpen ? 'ring-2 ring-primary/30 shadow-md' : 'hover:shadow-md'
          }`}
        >
          {initials}
        </button>

        <ProfileDropdown
          anchorRef={avatarRef}
          open={dropdownOpen}
          onClose={closeDropdown}
          user={user}
          onNavigate={navigate}
          onLogout={logout}
        />
      </div>
    </header>
  );
}
