import { useState, useCallback, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import SearchModal from '../ui/SearchModal';
import ErrorBoundary from '../ui/ErrorBoundary';

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [pathname]);
  return null;
}

export default function Layout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const location = useLocation();

  const handleSearchOpen = useCallback(() => setSearchOpen(true), []);
  const handleSearchClose = useCallback(() => setSearchOpen(false), []);

  return (
    <div className="flex min-h-screen bg-surface">
      <ScrollToTop />
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
      />
      <div className="flex flex-col flex-1 min-w-0">
        <Header
          onMobileMenuToggle={() => setMobileOpen(true)}
          onSearchOpen={handleSearchOpen}
        />
        <main className="flex-1 p-4 lg:p-6 overflow-y-auto">
          <ErrorBoundary>
            <div key={location.pathname} className="animate-fade-in">
              <Outlet />
            </div>
          </ErrorBoundary>
        </main>
      </div>
      <SearchModal open={searchOpen} onClose={handleSearchClose} />
    </div>
  );
}
