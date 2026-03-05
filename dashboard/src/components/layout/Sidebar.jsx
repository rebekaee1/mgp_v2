import { useState, useEffect, useCallback, useRef } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, MessageSquare, BarChart3, Code2, Activity, UserCircle,
  ChevronLeft, ChevronRight, X,
} from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';

const NAV_ITEMS = [
  { to: '/', icon: LayoutDashboard, label: 'Обзор' },
  { to: '/conversations', icon: MessageSquare, label: 'Диалоги' },
  { to: '/analytics', icon: BarChart3, label: 'Аналитика' },
  { to: '/widget', icon: Code2, label: 'Виджет' },
  { to: '/system', icon: Activity, label: 'Система' },
  { to: '/account', icon: UserCircle, label: 'Аккаунт' },
];

function LogoMark({ collapsed, onClick }) {
  return (
    <button
      onClick={onClick}
      className="relative flex items-center cursor-pointer hover:opacity-80 overflow-hidden shrink-0"
      style={{
        height: 44,
        width: collapsed ? 48 : 200,
        transition: 'width 300ms cubic-bezier(0.4, 0, 0.2, 1)',
      }}
      aria-label="Перейти к обзору"
    >
      <img
        src="/globe.svg"
        alt="навылет"
        className="absolute pointer-events-none object-contain"
        style={{
          height: 40,
          width: 48,
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          opacity: collapsed ? 1 : 0,
          transition: collapsed
            ? 'opacity 220ms ease-out 80ms'
            : 'opacity 100ms ease-out',
        }}
        draggable={false}
      />
      <img
        src="/logo.svg"
        alt="навылет"
        className="shrink-0 pointer-events-none"
        style={{
          height: 44,
          width: 'auto',
          opacity: collapsed ? 0 : 1,
          transition: collapsed
            ? 'opacity 100ms ease-out'
            : 'opacity 220ms ease-out 80ms',
        }}
        draggable={false}
      />
    </button>
  );
}

function ActiveIndicator({ navRef, collapsed }) {
  const location = useLocation();
  const [style, setStyle] = useState({});

  useEffect(() => {
    if (!navRef.current) return;
    const active = navRef.current.querySelector('a[aria-current="page"]');
    if (active) {
      const navRect = navRef.current.getBoundingClientRect();
      const activeRect = active.getBoundingClientRect();
      setStyle({
        top: activeRect.top - navRect.top + activeRect.height / 2 - 10,
        opacity: 1,
      });
    }
  }, [location.pathname, collapsed, navRef]);

  return (
    <div
      className="absolute left-0 w-[3px] h-5 rounded-r-full bg-primary transition-all duration-300 ease-out"
      style={{ ...style, opacity: style.opacity ?? 0 }}
    />
  );
}

export default function Sidebar({ collapsed, onToggle, mobileOpen, onMobileClose }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [mobileMounted, setMobileMounted] = useState(false);
  const [mobileVisible, setMobileVisible] = useState(false);
  const closingRef = useRef(false);
  const navRef = useRef(null);

  const initials = (user?.name || user?.email || 'U').charAt(0).toUpperCase();

  const handleMobileClose = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    setMobileVisible(false);
    setTimeout(() => {
      setMobileMounted(false);
      closingRef.current = false;
      onMobileClose();
    }, 250);
  }, [onMobileClose]);

  useEffect(() => {
    if (mobileOpen) {
      setMobileMounted(true);
      requestAnimationFrame(() => requestAnimationFrame(() => setMobileVisible(true)));
    }
  }, [mobileOpen]);

  const handleLogoClick = () => {
    navigate('/');
    if (mobileOpen) handleMobileClose();
  };

  const sidebarContent = (isMobile) => (
    <>
      <div className={`flex items-center h-16 shrink-0 transition-all duration-300 ${collapsed && !isMobile ? 'px-3 justify-center' : 'px-4 justify-between'}`}>
        <LogoMark collapsed={collapsed && !isMobile} onClick={handleLogoClick} />
        {isMobile && (
          <button onClick={handleMobileClose} className="lg:hidden text-text-secondary hover:text-text transition-colors" aria-label="Закрыть меню">
            <X size={20} />
          </button>
        )}
      </div>

      <nav ref={isMobile ? undefined : navRef} className="flex-1 py-3 space-y-0.5 overflow-y-auto px-2 relative">
        {!isMobile && <ActiveIndicator navRef={navRef} collapsed={collapsed} />}
        {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onClick={isMobile ? handleMobileClose : undefined}
            title={collapsed && !isMobile ? label : undefined}
            className={({ isActive }) => `
              relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-150
              ${isActive
                ? 'bg-primary-50 text-primary shadow-xs'
                : 'text-text-secondary hover:bg-surface-sunken hover:text-text'
              }
              ${collapsed && !isMobile ? 'justify-center px-2' : ''}
            `}
          >
            <Icon size={20} strokeWidth={1.8} className="shrink-0" />
            {(!collapsed || isMobile) && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className={`border-t border-border/60 ${collapsed && !isMobile ? 'px-2' : 'px-3'} py-3`}>
        {(!collapsed || isMobile) ? (
          <button
            onClick={() => { navigate('/account'); if (isMobile) handleMobileClose(); }}
            className="flex items-center gap-2.5 px-2 mb-3 w-full rounded-lg py-1.5 -my-1 hover:bg-surface-sunken transition-colors cursor-pointer group"
            aria-label="Перейти в профиль"
          >
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-[#3B82F6] flex items-center justify-center text-white text-xs font-semibold shrink-0">
              {initials}
            </div>
            <div className="flex-1 min-w-0 text-left">
              <p className="text-xs font-medium text-text truncate group-hover:text-primary transition-colors">{user?.name || user?.email}</p>
              <p className="text-[10px] text-text-secondary capitalize">{user?.role || 'admin'}</p>
            </div>
          </button>
        ) : (
          <button
            onClick={() => navigate('/account')}
            className="flex items-center justify-center w-full mb-3 cursor-pointer hover:opacity-80 transition-opacity"
            aria-label="Перейти в профиль"
            title="Профиль"
          >
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-[#3B82F6] flex items-center justify-center text-white text-xs font-semibold">
              {initials}
            </div>
          </button>
        )}
        {!isMobile && (
          <button
            onClick={onToggle}
            aria-label={collapsed ? 'Развернуть меню' : 'Свернуть меню'}
            className="hidden lg:flex w-full items-center justify-center h-8 rounded-lg text-text-secondary hover:text-text hover:bg-surface-sunken transition-colors"
          >
            {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
        )}
      </div>
    </>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside className={`
        hidden lg:flex flex-col bg-white/80 backdrop-blur-sm border-r border-border/60 h-screen sticky top-0 transition-all duration-200
        ${collapsed ? 'w-[68px]' : 'w-60'}
      `}>
        {sidebarContent(false)}
      </aside>

      {/* Mobile overlay */}
      {mobileMounted && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className={`absolute inset-0 transition-all duration-250 ease-out ${mobileVisible ? 'bg-text/20 backdrop-blur-sm' : 'bg-transparent backdrop-blur-0'}`}
            onClick={handleMobileClose}
          />
          <aside className={`relative w-64 h-full bg-white shadow-lg flex flex-col transition-all duration-250 ease-out ${mobileVisible ? 'translate-x-0 opacity-100' : '-translate-x-full opacity-0'}`}>
            {sidebarContent(true)}
          </aside>
        </div>
      )}
    </>
  );
}
