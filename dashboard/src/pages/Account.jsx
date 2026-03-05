import { useState, useEffect } from 'react';
import { User, Building2, Shield, AlertTriangle, Eye, EyeOff, Lock, CheckCircle2 } from 'lucide-react';
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
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showOldPw, setShowOldPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);
  const [changingPw, setChangingPw] = useState(false);
  const [pwSuccess, setPwSuccess] = useState(false);

  const [resetOpen, setResetOpen] = useState(false);
  const [resetPassword, setResetPassword] = useState('');
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    if (data) {
      setName(data.user?.name || '');
      setCompanyName(data.company?.name || '');
    }
  }, [data]);

  const pwMismatch = confirmPassword && newPassword !== confirmPassword;
  const pwTooShort = newPassword && newPassword.length < 6;
  const pwValid = oldPassword && newPassword.length >= 6 && newPassword === confirmPassword;

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
    if (!pwValid) return;
    setChangingPw(true);
    try {
      await api.put('/dashboard/account/password', {
        old_password: oldPassword,
        new_password: newPassword,
      });
      setPwSuccess(true);
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
      toast('Пароль успешно изменён', 'success');
      setTimeout(() => setPwSuccess(false), 3000);
    } catch (err) {
      toast(err.response?.data?.error || 'Ошибка смены пароля', 'error');
    } finally {
      setChangingPw(false);
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
          <div>
            <h3 className="text-sm font-semibold text-text">Безопасность</h3>
            {data?.user?.last_login_at && (
              <p className="text-[11px] text-text-secondary mt-0.5">
                Последний вход: {new Date(data.user.last_login_at).toLocaleString('ru-RU')}
              </p>
            )}
          </div>
        </div>

        <div className="mb-4">
          <label className="block text-xs text-text-secondary mb-1.5">Email аккаунта</label>
          <div className="relative">
            <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary/50" />
            <input
              type="email"
              value={data?.user?.email || ''}
              disabled
              className="w-full pl-9 pr-3.5 py-2.5 border border-border/60 rounded-xl text-sm bg-surface-sunken/60 text-text-secondary"
            />
          </div>
        </div>

        {pwSuccess ? (
          <div className="flex items-center gap-3 py-4 animate-fade-in">
            <div className="w-10 h-10 rounded-full bg-success/10 flex items-center justify-center">
              <CheckCircle2 size={20} className="text-success" />
            </div>
            <div>
              <p className="text-sm font-medium text-success">Пароль успешно изменён</p>
              <p className="text-xs text-text-secondary">Используйте новый пароль при следующем входе</p>
            </div>
          </div>
        ) : (
          <form onSubmit={handlePasswordChange} className="space-y-3">
            <div>
              <label className="block text-xs text-text-secondary mb-1.5">Текущий пароль</label>
              <div className="relative">
                <input
                  type={showOldPw ? 'text' : 'password'}
                  value={oldPassword}
                  onChange={(e) => setOldPassword(e.target.value)}
                  placeholder="Введите текущий пароль"
                  required
                  className="w-full px-3.5 py-2.5 pr-10 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-xs"
                />
                <button
                  type="button"
                  onClick={() => setShowOldPw(!showOldPw)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text transition-colors"
                >
                  {showOldPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-xs text-text-secondary mb-1.5">Новый пароль</label>
              <div className="relative">
                <input
                  type={showNewPw ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Минимум 6 символов"
                  required
                  minLength={6}
                  className={`w-full px-3.5 py-2.5 pr-10 border rounded-xl text-sm focus:outline-none focus:ring-2 shadow-xs transition-all ${
                    pwTooShort
                      ? 'border-danger/40 focus:ring-danger/20 focus:border-danger'
                      : 'border-border/60 focus:ring-primary/20 focus:border-primary'
                  }`}
                />
                <button
                  type="button"
                  onClick={() => setShowNewPw(!showNewPw)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text transition-colors"
                >
                  {showNewPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {pwTooShort && (
                <p className="text-xs text-danger mt-1">Минимум 6 символов</p>
              )}
            </div>

            <div>
              <label className="block text-xs text-text-secondary mb-1.5">Повторите новый пароль</label>
              <input
                type={showNewPw ? 'text' : 'password'}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Повторите пароль"
                required
                className={`w-full px-3.5 py-2.5 border rounded-xl text-sm focus:outline-none focus:ring-2 shadow-xs transition-all ${
                  pwMismatch
                    ? 'border-danger/40 focus:ring-danger/20 focus:border-danger'
                    : 'border-border/60 focus:ring-primary/20 focus:border-primary'
                }`}
              />
              {pwMismatch && (
                <p className="text-xs text-danger mt-1">Пароли не совпадают</p>
              )}
            </div>

            <button
              type="submit"
              disabled={!pwValid || changingPw}
              className="bg-gradient-to-r from-primary to-[#2557E8] hover:from-primary-dark hover:to-primary text-white text-sm font-medium px-5 py-2.5 rounded-xl transition-all disabled:opacity-60 shadow-sm hover:shadow-md"
            >
              {changingPw ? 'Сохранение...' : 'Сменить пароль'}
            </button>
          </form>
        )}
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
