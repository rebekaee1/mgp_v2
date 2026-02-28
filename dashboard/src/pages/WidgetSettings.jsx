import { useState, useEffect } from 'react';
import { Copy, Check, Code2 } from 'lucide-react';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import { useWidgetConfig, useWidgetEmbedCode } from '../hooks/useDashboardAPI';
import { useToast } from '../hooks/useToast';
import api from '../lib/api';

export default function WidgetSettings() {
  const { data: config, loading: loadingConfig, refetch } = useWidgetConfig();
  const { data: embedData } = useWidgetEmbedCode();
  const { toast } = useToast();

  const [welcomeMsg, setWelcomeMsg] = useState('');
  const [position, setPosition] = useState('bottom-right');
  const [primaryColor, setPrimaryColor] = useState('#0038FF');
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (config) {
      setWelcomeMsg(config.welcome_message || '');
      setPosition(config.position || 'bottom-right');
      setPrimaryColor(config.primary_color || '#0038FF');
    }
  }, [config]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.put('/dashboard/widget/config', {
        welcome_message: welcomeMsg,
        position,
        primary_color: primaryColor,
      });
      refetch();
      toast('Настройки виджета сохранены', 'success');
    } catch {
      toast('Ошибка сохранения', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(embedData?.embed_code || '');
    setCopied(true);
    toast('Код скопирован в буфер обмена', 'success');
    setTimeout(() => setCopied(false), 2000);
  };

  if (loadingConfig) return <LoadingSkeleton rows={6} />;

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-xl font-bold text-text">Настройки виджета</h1>
        <p className="text-sm text-text-secondary mt-0.5">Настройте внешний вид чат-виджета на вашем сайте</p>
      </div>

      {/* Widget preview */}
      <div className="bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-1">
        <h3 className="text-sm font-semibold text-text mb-4">Предварительный просмотр</h3>
        <div className="relative bg-surface-sunken rounded-xl p-6 min-h-[200px]">
          <div className={`absolute ${position === 'bottom-left' ? 'bottom-4 left-4' : 'bottom-4 right-4'}`}>
            <div className="w-14 h-14 rounded-full shadow-lg flex items-center justify-center transition-colors" style={{ backgroundColor: primaryColor }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="m3 21 1.9-5.7a8.5 8.5 0 1 1 3.8 3.8z" />
              </svg>
            </div>
          </div>
          {welcomeMsg && (
            <div className={`absolute ${position === 'bottom-left' ? 'bottom-20 left-4' : 'bottom-20 right-4'} max-w-[220px]`}>
              <div className="bg-white rounded-xl shadow-md px-4 py-3 text-sm text-text">
                {welcomeMsg}
              </div>
            </div>
          )}
          <p className="text-xs text-text-secondary text-center mt-4">Так виджет будет выглядеть на сайте</p>
        </div>
      </div>

      {/* Settings form */}
      <div className="bg-white rounded-2xl shadow-sm p-5 space-y-4 animate-fade-in-up stagger-2">
        <h3 className="text-sm font-semibold text-text">Параметры</h3>

        <div>
          <label className="block text-sm text-text-secondary mb-1.5">Приветственное сообщение</label>
          <textarea
            value={welcomeMsg}
            onChange={(e) => setWelcomeMsg(e.target.value)}
            rows={3}
            className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary resize-none shadow-xs"
            placeholder="Привет! Помогу подобрать тур."
          />
        </div>

        <div>
          <label className="block text-sm text-text-secondary mb-1.5">Позиция</label>
          <div className="flex gap-2">
            {[
              { value: 'bottom-right', label: 'Справа внизу' },
              { value: 'bottom-left', label: 'Слева внизу' },
            ].map((opt) => (
              <button
                key={opt.value}
                onClick={() => setPosition(opt.value)}
                className={`px-3.5 py-2 rounded-xl text-xs font-medium border transition-all ${
                  position === opt.value
                    ? 'bg-primary text-white border-primary shadow-sm'
                    : 'bg-white text-text-secondary border-border/60 hover:border-primary'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm text-text-secondary mb-1.5">Основной цвет</label>
          <div className="flex items-center gap-3">
            <input
              type="color"
              value={primaryColor}
              onChange={(e) => setPrimaryColor(e.target.value)}
              className="w-10 h-10 rounded-xl border border-border/60 cursor-pointer shadow-xs"
            />
            <input
              type="text"
              value={primaryColor}
              onChange={(e) => setPrimaryColor(e.target.value)}
              className="px-3 py-2 border border-border/60 rounded-xl text-sm w-28 font-mono focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-xs"
            />
          </div>
        </div>

        <button
          onClick={handleSave}
          disabled={saving}
          className="bg-gradient-to-r from-primary to-[#2557E8] hover:from-primary-dark hover:to-primary text-white text-sm font-medium px-5 py-2.5 rounded-xl transition-all disabled:opacity-60 shadow-sm hover:shadow-md"
        >
          {saving ? 'Сохранение...' : 'Сохранить'}
        </button>
      </div>

      {/* Embed code */}
      <div className="bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-3">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-7 h-7 rounded-lg bg-primary-50 flex items-center justify-center">
            <Code2 size={14} className="text-primary" />
          </div>
          <h3 className="text-sm font-semibold text-text">Код для встраивания</h3>
        </div>

        <div className="relative">
          <pre className="bg-surface-sunken rounded-xl p-4 text-xs font-mono overflow-x-auto whitespace-pre-wrap break-all">
            {embedData?.embed_code || 'Загрузка...'}
          </pre>
          <button
            onClick={handleCopy}
            className="absolute top-2 right-2 p-2 rounded-lg bg-white shadow-xs border border-border/40 hover:shadow-sm transition-all"
          >
            {copied ? <Check size={14} className="text-success" /> : <Copy size={14} className="text-text-secondary" />}
          </button>
        </div>

        <div className="mt-4 text-xs text-text-secondary space-y-1">
          <p className="font-medium text-text">Инструкция по установке:</p>
          <ol className="list-decimal list-inside space-y-0.5 ml-1">
            <li>Скопируйте код выше</li>
            <li>Вставьте перед закрывающим тегом <code className="bg-surface-sunken px-1.5 py-0.5 rounded-md font-mono">&lt;/body&gt;</code> на вашем сайте</li>
          </ol>
        </div>
      </div>
    </div>
  );
}
