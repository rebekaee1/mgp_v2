import { useState, useEffect } from 'react';
import { User, Building2, Lock, Shield, AlertTriangle } from 'lucide-react';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import { useAccount } from '../hooks/useDashboardAPI';
import { useToast } from '../hooks/useToast';
import api from '../lib/api';

export default function Account() {
  const { data, loading, refetch } = useAccount();
  const { toast } = useToast();

  const [name, setName] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [saving, setSaving] = useState(false);

  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');

  const [resetOpen, setResetOpen] = useState(false);
  const [resetPassword, setResetPassword] = useState('');
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    if (data) {
      setName(data.user?.name || '');
      setCompanyName(data.company?.name || '');
    }
  }, [data]);

  const handleProfileSave = async () => {
    setSaving(true);
    try {
      await api.put('/dashboard/account/profile', { name, company_name: companyName });
      refetch();
      toast('Профиль сохранён', 'success');
    } catch (err) {
      toast(err.response?.data?.error || 'Ошибка сохранения', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    try {
      await api.put('/dashboard/account/password', {
        old_password: oldPassword,
        new_password: newPassword,
      });
      toast('Пароль успешно изменён', 'success');
      setOldPassword('');
      setNewPassword('');
    } catch (err) {
      toast(err.response?.data?.error || 'Ошибка смены пароля', 'error');
    }
  };

  const handleResetData = async (e) => {
    e.preventDefault();
    setResetting(true);
    try {
      await api.post('/dashboard/account/reset-data', { password: resetPassword });
      toast('Все данные успешно сброшены', 'success');
      setResetOpen(false);
      setResetPassword('');
      setTimeout(() => window.location.reload(), 800);
    } catch (err) {
      toast(err.response?.data?.error || 'Ошибка сброса данных', 'error');
    } finally {
      setResetting(false);
    }
  };

  if (loading) return <LoadingSkeleton rows={8} />;

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h1 className="text-xl font-bold text-text">Аккаунт</h1>
        <p className="text-sm text-text-secondary mt-0.5">Управление профилем и безопасностью</p>
      </div>

      {/* Profile */}
      <div className="bg-white rounded-2xl shadow-sm p-5 space-y-4 animate-fade-in-up stagger-1">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-primary-50 flex items-center justify-center">
            <User size={16} className="text-primary" />
          </div>
          <h3 className="text-sm font-semibold text-text">Профиль</h3>
        </div>

        <div>
          <label className="block text-xs text-text-secondary mb-1.5">Email</label>
          <input
            type="email"
            value={data?.user?.email || ''}
            disabled
            className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm bg-surface-sunken/60 text-text-secondary"
          />
        </div>

        <div>
          <label className="block text-xs text-text-secondary mb-1.5">Имя</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-xs"
          />
        </div>

        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <Building2 size={12} className="text-primary" />
            <label className="text-xs text-text-secondary">Компания</label>
          </div>
          <input
            type="text"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-xs"
          />
        </div>

        <button
          onClick={handleProfileSave}
          disabled={saving}
          className="bg-gradient-to-r from-primary to-[#2557E8] hover:from-primary-dark hover:to-primary text-white text-sm font-medium px-5 py-2.5 rounded-xl transition-all disabled:opacity-60 shadow-sm hover:shadow-md"
        >
          {saving ? 'Сохранение...' : 'Сохранить'}
        </button>
      </div>

      {/* Password change */}
      <div className="bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-2">
        <div className="flex items-center gap-2.5 mb-4">
          <div className="w-8 h-8 rounded-xl bg-primary-50 flex items-center justify-center">
            <Shield size={16} className="text-primary" />
          </div>
          <h3 className="text-sm font-semibold text-text">Безопасность</h3>
        </div>

        <form onSubmit={handlePasswordChange} className="space-y-3">
          <input
            type="password"
            value={oldPassword}
            onChange={(e) => setOldPassword(e.target.value)}
            placeholder="Текущий пароль"
            required
            className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-xs"
          />
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="Новый пароль (мин. 6 символов)"
            required
            minLength={6}
            className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-xs"
          />
          <button
            type="submit"
            className="bg-gradient-to-r from-primary to-[#2557E8] hover:from-primary-dark hover:to-primary text-white text-sm font-medium px-5 py-2.5 rounded-xl transition-all shadow-sm hover:shadow-md"
          >
            Сменить пароль
          </button>
        </form>
      </div>

      {/* Danger zone */}
      <div className="border border-red-200 bg-red-50/30 rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-3">
        <div className="flex items-center gap-2.5 mb-2">
          <div className="w-8 h-8 rounded-xl bg-red-100 flex items-center justify-center">
            <AlertTriangle size={16} className="text-red-500" />
          </div>
          <h3 className="text-sm font-semibold text-red-600">Опасная зона</h3>
        </div>
        <p className="text-xs text-text-secondary mb-4">
          Все диалоги, сообщения и аналитика будут удалены. Настройки ассистента и аккаунт сохранятся. Это действие необратимо.
        </p>

        {!resetOpen ? (
          <button
            onClick={() => setResetOpen(true)}
            className="bg-red-500 hover:bg-red-600 text-white text-sm font-medium px-5 py-2.5 rounded-xl transition-all shadow-sm hover:shadow-md"
          >
            Сбросить все данные
          </button>
        ) : (
          <form onSubmit={handleResetData} className="space-y-3">
            <p className="text-xs font-medium text-red-600">
              Для подтверждения введите пароль от аккаунта:
            </p>
            <input
              type="password"
              value={resetPassword}
              onChange={(e) => setResetPassword(e.target.value)}
              placeholder="Пароль"
              required
              autoFocus
              className="w-full px-3.5 py-2.5 border border-red-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-red-200 focus:border-red-400 shadow-xs"
            />
            <div className="flex items-center gap-2">
              <button
                type="submit"
                disabled={resetting || !resetPassword}
                className="bg-red-500 hover:bg-red-600 text-white text-sm font-medium px-5 py-2.5 rounded-xl transition-all disabled:opacity-60 shadow-sm hover:shadow-md"
              >
                {resetting ? 'Сброс...' : 'Подтвердить сброс'}
              </button>
              <button
                type="button"
                onClick={() => { setResetOpen(false); setResetPassword(''); }}
                className="text-sm text-text-secondary hover:text-text px-4 py-2.5 rounded-xl transition-colors"
              >
                Отмена
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
