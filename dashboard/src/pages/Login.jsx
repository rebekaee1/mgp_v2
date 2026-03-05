import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { LogIn, Eye, EyeOff } from 'lucide-react';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate('/');
    } catch (err) {
      setError(err.response?.data?.error || 'Ошибка входа');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden"
      style={{ background: 'linear-gradient(135deg, #FFFFFF 0%, #F0F4FF 50%, #E8EEFF 100%)' }}>

      {/* Decorative shapes */}
      <div className="absolute top-[-120px] right-[-80px] w-[400px] h-[400px] rounded-full opacity-[0.07]"
        style={{ background: 'radial-gradient(circle, #0038FF, transparent)' }} />
      <div className="absolute bottom-[-100px] left-[-60px] w-[300px] h-[300px] rounded-full opacity-[0.05]"
        style={{ background: 'radial-gradient(circle, #3B82F6, transparent)' }} />

      <div className="w-full max-w-sm relative z-10 animate-fade-in-up">
        <div className="text-center mb-8">
          <img
            src="/logo.svg"
            alt="навылет"
            className="h-12 w-auto mx-auto mb-4"
            draggable={false}
          />
          <p className="text-sm text-text-secondary mt-1">Личный кабинет AI-ассистента</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-lg p-6 space-y-4 border border-white/60">
          {error && (
            <div className="bg-danger-light border border-danger/20 text-danger text-sm rounded-xl px-4 py-2.5 animate-fade-in">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-text mb-1.5">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-xl border border-border/60 bg-white text-sm
                focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all shadow-xs"
              placeholder="admin@company.ru"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-text mb-1.5">Пароль</label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3.5 py-2.5 pr-10 rounded-xl border border-border/60 bg-white text-sm
                  focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all shadow-xs"
                placeholder="••••••••"
                required
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

          <div className="flex justify-end -mt-1">
            <Link
              to={`/reset-password${email ? `?email=${encodeURIComponent(email)}` : ''}`}
              className="text-xs text-primary hover:underline transition-colors"
            >
              Забыли пароль?
            </Link>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-primary to-[#2557E8] hover:from-primary-dark hover:to-primary
              text-white font-medium py-2.5 rounded-xl transition-all disabled:opacity-60 shadow-md hover:shadow-lg"
          >
            <LogIn size={16} />
            {loading ? 'Вход...' : 'Войти'}
          </button>
        </form>

        <p className="text-center text-[11px] text-text-secondary/60 mt-6">
          Powered by AIMPACT+
        </p>
      </div>
    </div>
  );
}
