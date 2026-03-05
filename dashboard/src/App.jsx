import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './hooks/useAuth';
import { ToastProvider } from './hooks/useToast';
import ErrorBoundary from './components/ui/ErrorBoundary';
import Layout from './components/layout/Layout';
import Login from './pages/Login';
import Overview from './pages/Overview';
import Conversations from './pages/Conversations';
import ConversationDetail from './pages/ConversationDetail';
import Analytics from './pages/Analytics';
import WidgetSettings from './pages/WidgetSettings';
import SystemStatus from './pages/SystemStatus';
import Account from './pages/Account';
import ResetPassword from './pages/ResetPassword';

function LoadingScreen() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-surface">
      <div className="flex flex-col items-center gap-5 animate-fade-in">
        <img
          src="/globe.svg"
          alt="навылет"
          className="h-20 w-auto animate-globe-pulse"
          draggable={false}
        />
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-primary animate-dot-pulse" style={{ animationDelay: '0ms' }} />
          <span className="w-2 h-2 rounded-full bg-primary animate-dot-pulse" style={{ animationDelay: '200ms' }} />
          <span className="w-2 h-2 rounded-full bg-primary animate-dot-pulse" style={{ animationDelay: '400ms' }} />
        </div>
      </div>
    </div>
  );
}

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <LoadingScreen />;
  return user ? children : <Navigate to="/login" replace />;
}

function PublicRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? <Navigate to="/" replace /> : children;
}

export default function App() {
  return (
    <ErrorBoundary fallbackMessage="Критическая ошибка приложения. Перезагрузите страницу.">
      <AuthProvider>
        <ToastProvider>
          <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '') || '/'}>
            <Routes>
              <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
              <Route path="/reset-password" element={<PublicRoute><ResetPassword /></PublicRoute>} />
              <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
                <Route index element={<Overview />} />
                <Route path="conversations" element={<Conversations />} />
                <Route path="conversations/:id" element={<ConversationDetail />} />
                <Route path="analytics" element={<Analytics />} />
                <Route path="widget" element={<WidgetSettings />} />
                <Route path="system" element={<SystemStatus />} />
                <Route path="account" element={<Account />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </ToastProvider>
      </AuthProvider>
    </ErrorBoundary>
  );
}
