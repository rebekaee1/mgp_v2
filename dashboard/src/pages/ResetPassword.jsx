import { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Mail, KeyRound, ArrowLeft, Eye, EyeOff, CheckCircle2, RefreshCw } from 'lucide-react';
import api from '../lib/api';

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const [step, setStep] = useState(1);
  const [email, setEmail] = useState(searchParams.get('email') || '');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const [cooldown, setCooldown] = useState(0);
  const codeRef = useRef(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown(c => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  useEffect(() => {
    if (step === 2 && codeRef.current) codeRef.current.focus();
  }, [step]);

  const handleSendCode = useCallback(async (e) => {
    if (e) e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);
    try {
      const { data } = await api.post('/auth/forgot-password', { email });
      setSuccess(data.message || 'Код отправлен на почту');
      setStep(2);
      setCooldown(60);
    } catch (err) {
      setError(err.response?.data?.error || 'Не удалось отправить код');
    } finally {
      setLoading(false);
    }
  }, [email]);

  const handleReset = useCallback(async (e) => {
    e.preventDefault();
    setError('');

    if (newPassword.length < 6) {
      setError('Пароль должен быть не менее 6 символов');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('Пароли не совпадают');
      return;
    }

    setLoading(true);
    try {
      await api.post('/auth/reset-password', {
        email,
        code,
        new_password: newPassword,
      });
      setStep(3);
    } catch (err) {
      setError(err.response?.data?.error || 'Не удалось сбросить пароль');
    } finally {
      setLoading(false);
    }
  }, [email, code, newPassword, confirmPassword]);

  const handleResend = useCallback(() => {
    if (cooldown > 0) return;
    handleSendCode(null);
  }, [cooldown, handleSendCode]);

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden"
      style={{ background: 'linear-gradient(135deg, #FFFFFF 0%, #F0F4FF 50%, #E8EEFF 100%)' }}
    >
      <div className="absolute top-[-120px] right-[-80px] w-[400px] h-[400px] rounded-full opacity-[0.07]"
        style={{ background: 'radial-gradient(circle, #0038FF, transparent)' }} />
      <div className="absolute bottom-[-100px] left-[-60px] w-[300px] h-[300px] rounded-full opacity-[0.05]"
        style={{ background: 'radial-gradient(circle, #3B82F6, transparent)' }} />

      <div className="w-full max-w-sm relative z-10 animate-fade-in-up">
        <div className="text-center mb-8">
          <img src="/logo.svg" alt="навылет" className="h-12 w-auto mx-auto mb-4" draggable={false} />
          <p className="text-sm text-text-secondary mt-1">Восстановление доступа</p>
        </div>

        {/* Step 1: Enter email */}
        {step === 1 && (
          <form
            onSubmit={handleSendCode}
            className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-lg p-6 space-y-4 border border-white/60"
          >
            {error && (
              <div className="bg-danger-light border border-danger/20 text-danger text-sm rounded-xl px-4 py-2.5 animate-fade-in">
                {error}
              </div>
            )}

            <p className="text-sm text-text-secondary leading-relaxed">
              Введите email, привязанный к вашему аккаунту. Мы отправим код для сброса пароля.
            </p>

            <div>
              <label className="block text-sm font-medium text-text mb-1.5">Email</label>
              <div className="relative">
                <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-10 pr-3.5 py-2.5 rounded-xl border border-border/60 bg-white text-sm
                    focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all shadow-xs"
                  placeholder="email@company.ru"
                  required
                  autoFocus
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-primary to-[#2557E8] hover:from-primary-dark hover:to-primary
                text-white font-medium py-2.5 rounded-xl transition-all disabled:opacity-60 shadow-md hover:shadow-lg"
            >
              {loading ? 'Отправка...' : 'Отправить код'}
            </button>

            <div className="text-center">
              <Link to="/login" className="inline-flex items-center gap-1.5 text-xs text-text-secondary hover:text-primary transition-colors">
                <ArrowLeft size={12} />
                Вернуться к входу
              </Link>
            </div>
          </form>
        )}

        {/* Step 2: Enter code + new password */}
        {step === 2 && (
          <form
            onSubmit={handleReset}
            className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-lg p-6 space-y-4 border border-white/60"
          >
            {error && (
              <div className="bg-danger-light border border-danger/20 text-danger text-sm rounded-xl px-4 py-2.5 animate-fade-in">
                {error}
              </div>
            )}
            {success && (
              <div className="bg-success/5 border border-success/20 text-success text-sm rounded-xl px-4 py-2.5 animate-fade-in">
                {success}
              </div>
            )}

            <p className="text-sm text-text-secondary leading-relaxed">
              Код отправлен на <strong className="text-text">{email}</strong>. Введите его ниже вместе с новым паролем.
            </p>

            <div>
              <label className="block text-sm font-medium text-text mb-1.5">Код из письма</label>
              <div className="relative">
                <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
                <input
                  ref={codeRef}
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  className="w-full pl-10 pr-3.5 py-2.5 rounded-xl border border-border/60 bg-white text-sm tracking-[0.3em] font-mono
                    focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all shadow-xs"
                  placeholder="000000"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-text mb-1.5">Новый пароль</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full px-3.5 py-2.5 pr-10 rounded-xl border border-border/60 bg-white text-sm
                    focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all shadow-xs"
                  placeholder="Минимум 6 символов"
                  required
                  minLength={6}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text transition-colors"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-text mb-1.5">Подтвердите пароль</label>
              <input
                type={showPassword ? 'text' : 'password'}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl border border-border/60 bg-white text-sm
                  focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all shadow-xs"
                placeholder="Повторите пароль"
                required
                minLength={6}
              />
              {confirmPassword && newPassword !== confirmPassword && (
                <p className="text-xs text-danger mt-1">Пароли не совпадают</p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading || code.length < 6}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-primary to-[#2557E8] hover:from-primary-dark hover:to-primary
                text-white font-medium py-2.5 rounded-xl transition-all disabled:opacity-60 shadow-md hover:shadow-lg"
            >
              {loading ? 'Сброс...' : 'Сбросить пароль'}
            </button>

            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={() => { setStep(1); setError(''); setSuccess(''); setCode(''); }}
                className="inline-flex items-center gap-1.5 text-xs text-text-secondary hover:text-primary transition-colors"
              >
                <ArrowLeft size={12} />
                Изменить email
              </button>
              <button
                type="button"
                onClick={handleResend}
                disabled={cooldown > 0}
                className="inline-flex items-center gap-1.5 text-xs text-primary hover:text-primary-dark transition-colors disabled:text-text-secondary disabled:cursor-default"
              >
                <RefreshCw size={12} />
                {cooldown > 0 ? `Повторить (${cooldown}с)` : 'Отправить повторно'}
              </button>
            </div>
          </form>
        )}

        {/* Step 3: Success */}
        {step === 3 && (
          <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-lg p-6 border border-white/60 text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-success/10 flex items-center justify-center mx-auto">
              <CheckCircle2 size={32} className="text-success" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-text">Пароль изменён</h3>
              <p className="text-sm text-text-secondary mt-1">
                Теперь вы можете войти с новым паролем
              </p>
            </div>
            <button
              onClick={() => navigate('/login')}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-primary to-[#2557E8] hover:from-primary-dark hover:to-primary
                text-white font-medium py-2.5 rounded-xl transition-all shadow-md hover:shadow-lg"
            >
              Войти
            </button>
          </div>
        )}

        <p className="text-center text-[11px] text-text-secondary/60 mt-6">
          Powered by AIMPACT+
        </p>
      </div>
    </div>
  );
}
