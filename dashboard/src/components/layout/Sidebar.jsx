import { NavLink } from 'react-router-dom';
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

function LogoMark({ collapsed }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-[#3B82F6] flex items-center justify-center shadow-sm shrink-0">
        <span className="text-white font-bold text-sm leading-none">A+</span>
      </div>
      {!collapsed && (
        <span className="text-base font-bold bg-gradient-to-r from-primary to-[#3B82F6] bg-clip-text text-transparent tracking-tight">
          AIMPACT+
        </span>
      )}
    </div>
  );
}

export default function Sidebar({ collapsed, onToggle, mobileOpen, onMobileClose }) {
  const { user } = useAuth();

  const initials = (user?.name || user?.email || 'U').charAt(0).toUpperCase();

  const sidebarContent = (
    <>
      <div className="flex items-center justify-between px-4 h-16 shrink-0">
        <LogoMark collapsed={collapsed} />
        {mobileOpen && (
          <button onClick={onMobileClose} className="lg:hidden text-text-secondary hover:text-text transition-colors">
            <X size={20} />
          </button>
        )}
      </div>

      <nav className="flex-1 py-3 space-y-0.5 overflow-y-auto px-2">
        {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onClick={onMobileClose}
            title={collapsed ? label : undefined}
            className={({ isActive }) => `
              relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-150
              ${isActive
                ? 'bg-primary-50 text-primary shadow-xs'
                : 'text-text-secondary hover:bg-surface-sunken hover:text-text'
              }
              ${collapsed ? 'justify-center px-2' : ''}
            `}
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-primary" />
                )}
                <Icon size={20} strokeWidth={1.8} className="shrink-0" />
                {!collapsed && <span>{label}</span>}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className={`border-t border-border/60 ${collapsed ? 'px-2' : 'px-3'} py-3`}>
        {!collapsed && (
          <div className="flex items-center gap-2.5 px-2 mb-3">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-[#3B82F6] flex items-center justify-center text-white text-xs font-semibold shrink-0">
              {initials}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-text truncate">{user?.name || user?.email}</p>
              <p className="text-[10px] text-text-secondary capitalize">{user?.role || 'admin'}</p>
            </div>
          </div>
        )}
        <button
          onClick={onToggle}
          className="hidden lg:flex w-full items-center justify-center h-8 rounded-lg text-text-secondary hover:text-text hover:bg-surface-sunken transition-colors"
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
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
        {sidebarContent}
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-text/20 backdrop-blur-sm" onClick={onMobileClose} />
          <aside className="relative w-64 h-full bg-white shadow-lg flex flex-col animate-slide-in">
            {sidebarContent}
          </aside>
        </div>
      )}
    </>
  );
}
