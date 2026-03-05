import { useState, useEffect, useRef, useCallback } from 'react';
import { Copy, Check, Code2, Upload, Trash2, RotateCcw, Save, Image as ImageIcon, Sparkles } from 'lucide-react';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import { useWidgetConfig, useWidgetEmbedCode } from '../hooks/useDashboardAPI';
import { useToast } from '../hooks/useToast';
import api from '../lib/api';

function presetSvgDataUrl(type, color) {
  const svgs = {
    robot: `<svg xmlns="http://www.w3.org/2000/svg" width="88" height="88" viewBox="0 0 88 88"><circle cx="44" cy="44" r="44" fill="${color}"/><g transform="translate(20,20)" fill="white"><rect x="4" y="10" width="40" height="30" rx="8" fill="white"/><circle cx="17" cy="23" r="5" fill="${color}"/><circle cx="31" cy="23" r="5" fill="${color}"/><circle cx="17" cy="22" r="2" fill="white"/><circle cx="31" cy="22" r="2" fill="white"/><path d="M18 33c0 0 3 4 6 4s6-4 6-4" stroke="${color}" stroke-width="2.5" fill="none" stroke-linecap="round"/><rect x="21" y="1" width="6" height="9" rx="3" fill="white"/><circle cx="24" cy="1" r="3.5" fill="white" opacity="0.85"/></g></svg>`,
    globe: `<svg xmlns="http://www.w3.org/2000/svg" width="88" height="88" viewBox="0 0 88 88"><circle cx="44" cy="44" r="44" fill="${color}"/><g transform="translate(22,22) scale(1.833)"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" fill="white"/></g></svg>`,
  };
  return `data:image/svg+xml,${encodeURIComponent(svgs[type])}`;
}

const PRESET_LIST = [
  { id: 'manager-male', type: 'photo', url: '/static/presets/preset-manager-male.png', label: 'Менеджер' },
  { id: 'manager-female', type: 'photo', url: '/static/presets/preset-manager-female.png', label: 'Менеджер' },
  { id: 'robot', type: 'svg', label: 'AI робот' },
  { id: 'globe', type: 'svg', label: 'Глобус' },
];

const DEFAULTS = {
  welcome_message:
    '\u{1f44b} Здравствуйте! Я — ИИ-ассистент туристического агентства.\n\nЯ помогу вам:\n• \u{1f50d} Подобрать тур по вашим параметрам\n• \u{1f525} Найти горящие предложения\n• \u2753 Ответить на вопросы о визах, оплате, документах\n\nКуда бы вы хотели поехать?',
  primary_color: '#E30613',
  position: 'bottom-right',
  title: 'AI Ассистент',
  subtitle: 'Турагентство',
  logo_url: null,
};

function darkenHex(hex, amount) {
  hex = hex.replace('#', '');
  const r = Math.max(0, parseInt(hex.substring(0, 2), 16) - amount);
  const g = Math.max(0, parseInt(hex.substring(2, 4), 16) - amount);
  const b = Math.max(0, parseInt(hex.substring(4, 6), 16) - amount);
  return '#' + [r, g, b].map(c => c.toString(16).padStart(2, '0')).join('');
}

function formatWelcomePreview(text) {
  if (!text) return '';
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

export default function WidgetSettings() {
  const { data: config, loading: loadingConfig } = useWidgetConfig();
  const { data: embedData } = useWidgetEmbedCode();
  const { toast } = useToast();

  const [welcomeMsg, setWelcomeMsg] = useState(DEFAULTS.welcome_message);
  const [position, setPosition] = useState(DEFAULTS.position);
  const [primaryColor, setPrimaryColor] = useState(DEFAULTS.primary_color);
  const [title, setTitle] = useState(DEFAULTS.title);
  const [subtitle, setSubtitle] = useState(DEFAULTS.subtitle);
  const [logoUrl, setLogoUrl] = useState(null);
  const [logoPreview, setLogoPreview] = useState(null);
  const [activePreset, setActivePreset] = useState(null);
  const [botServerUrl, setBotServerUrl] = useState('');
  const [allowedDomains, setAllowedDomains] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [copied, setCopied] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const fileInputRef = useRef(null);
  const initializedRef = useRef(false);
  const pendingResetRef = useRef(false);

  useEffect(() => {
    if (!config) return;
    if (initializedRef.current && !pendingResetRef.current) return;
    initializedRef.current = true;
    pendingResetRef.current = false;
    setWelcomeMsg(config.welcome_message || DEFAULTS.welcome_message);
    setPosition(config.position || DEFAULTS.position);
    setPrimaryColor(config.primary_color || DEFAULTS.primary_color);
    setTitle(config.title || DEFAULTS.title);
    setSubtitle(config.subtitle || DEFAULTS.subtitle);
    setLogoUrl(config.logo_url || null);
    setActivePreset(config.active_preset || null);
    setBotServerUrl(config.bot_server_url || '');
    setAllowedDomains(config.allowed_domains || '');
  }, [config]);

  useEffect(() => {
    if (activePreset && (activePreset === 'robot' || activePreset === 'globe')) {
      setLogoUrl(presetSvgDataUrl(activePreset, primaryColor));
    }
  }, [primaryColor, activePreset]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        welcome_message: welcomeMsg,
        position,
        primary_color: primaryColor,
        title,
        subtitle,
        logo_url: logoUrl,
        active_preset: activePreset,
        bot_server_url: botServerUrl,
        allowed_domains: allowedDomains,
      };
      if (activePreset && (activePreset === 'robot' || activePreset === 'globe')) {
        payload.logo_url = presetSvgDataUrl(activePreset, primaryColor);
        setLogoUrl(payload.logo_url);
      }
      await api.put('/dashboard/widget/config', payload);
      toast('Настройки виджета сохранены', 'success');
    } catch {
      toast('Ошибка сохранения', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleLogoUpload = useCallback(async (file) => {
    if (!file) return;

    const ext = file.name.split('.').pop().toLowerCase();
    if (!['png', 'jpg', 'jpeg', 'webp'].includes(ext)) {
      toast('Допустимые форматы: PNG, JPG, WebP', 'error');
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      toast('Максимальный размер файла — 2 МБ', 'error');
      return;
    }

    setLogoPreview(URL.createObjectURL(file));
    setUploadingLogo(true);

    try {
      const formData = new FormData();
      formData.append('logo', file);
      const { data } = await api.post('/dashboard/widget/logo', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setLogoUrl(data.logo_url);
      setLogoPreview(null);
      setActivePreset(null);
      await api.put('/dashboard/widget/config', { logo_url: data.logo_url, active_preset: null });
      toast('Логотип загружен', 'success');
    } catch (err) {
      setLogoPreview(null);
      const msg = err.response?.data?.error || 'Ошибка загрузки логотипа';
      toast(msg, 'error');
    } finally {
      setUploadingLogo(false);
    }
  }, [toast]);

  const handleLogoDelete = async () => {
    try {
      const isUploadedFile = logoUrl && logoUrl.startsWith('/static/logos/');
      if (isUploadedFile) {
        await api.delete('/dashboard/widget/logo');
      }
      await api.put('/dashboard/widget/config', { logo_url: null, active_preset: null });
      setLogoUrl(null);
      setLogoPreview(null);
      setActivePreset(null);
      toast('Логотип удалён', 'success');
    } catch {
      toast('Ошибка удаления логотипа', 'error');
    }
  };

  const handlePresetSelect = (preset) => {
    if (activePreset === preset.id) return;
    const isSvg = preset.type === 'svg';
    const url = isSvg ? presetSvgDataUrl(preset.id, primaryColor) : preset.url;
    setActivePreset(preset.id);
    setLogoUrl(url);
    setLogoPreview(null);
  };

  const [showResetConfirm, setShowResetConfirm] = useState(false);

  const handleReset = async () => {
    setShowResetConfirm(false);
    setWelcomeMsg(DEFAULTS.welcome_message);
    setPosition(DEFAULTS.position);
    setPrimaryColor(DEFAULTS.primary_color);
    setTitle(DEFAULTS.title);
    setSubtitle(DEFAULTS.subtitle);
    setActivePreset(null);
    setLogoUrl(null);
    setLogoPreview(null);
    try {
      await api.put('/dashboard/widget/config', {
        welcome_message: DEFAULTS.welcome_message,
        position: DEFAULTS.position,
        primary_color: DEFAULTS.primary_color,
        title: DEFAULTS.title,
        subtitle: DEFAULTS.subtitle,
        logo_url: null,
        active_preset: null,
      });
      toast('Настройки сброшены к стандартным', 'success');
    } catch {
      toast('Ошибка сброса настроек', 'error');
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(embedData?.embed_code || '');
    setCopied(true);
    toast('Код скопирован в буфер обмена', 'success');
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleLogoUpload(file);
  }, [handleLogoUpload]);

  const displayLogo = logoPreview || logoUrl;
  const gradientBg = `linear-gradient(135deg, ${primaryColor} 0%, ${darkenHex(primaryColor, 30)} 100%)`;

  if (loadingConfig) return <LoadingSkeleton rows={6} />;

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="animate-fade-in-up">
        <h1 className="text-xl font-bold text-text">Настройки виджета</h1>
        <p className="text-sm text-text-secondary mt-0.5">
          Настройте внешний вид и содержание чат-виджета
        </p>
      </div>

      {/* Bot Server Connection */}
      <div className="bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-1">
        <h3 className="text-sm font-semibold text-text mb-1">Подключение к серверу бота</h3>
        <p className="text-xs text-text-secondary mb-4">
          Укажите адрес сервера, на котором установлен AI-ассистент. Без этого виджет не будет работать.
        </p>

        <div className="space-y-3">
          <div>
            <label className="block text-sm text-text-secondary mb-1.5">URL сервера бота</label>
            <input
              type="url"
              value={botServerUrl}
              onChange={(e) => setBotServerUrl(e.target.value)}
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-xs font-mono"
              placeholder="http://72.56.88.193"
            />
            <p className="text-[11px] text-text-secondary mt-1">
              Адрес сервера, где работает бот (например, http://72.56.88.193)
            </p>
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1.5">Разрешённые домены <span className="text-text-secondary/50">(необязательно)</span></label>
            <input
              type="text"
              value={allowedDomains}
              onChange={(e) => setAllowedDomains(e.target.value)}
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-xs"
              placeholder="example.com, shop.example.com"
            />
            <p className="text-[11px] text-text-secondary mt-1">
              Домены, на которых разрешено встраивание виджета. Через запятую. Если пусто — без ограничений.
            </p>
          </div>
        </div>

        {!botServerUrl && (
          <div className="mt-4 bg-amber-50 border border-amber-200 rounded-xl p-3 flex items-start gap-2">
            <svg className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            <p className="text-xs text-amber-800">
              Укажите URL сервера бота и сохраните настройки, чтобы получить код для встраивания виджета.
            </p>
          </div>
        )}
      </div>

      {/* Live Preview */}
      <div className="bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-2">
        <h3 className="text-sm font-semibold text-text mb-4">Предварительный просмотр</h3>
        <div className="bg-surface-sunken rounded-xl overflow-hidden" style={{ maxWidth: 380, margin: '0 auto' }}>
          {/* Preview header */}
          <div className="flex items-center gap-3 px-4 py-3" style={{ background: gradientBg }}>
            <div className="w-10 h-10 rounded-full bg-white/20 flex items-center justify-center overflow-hidden flex-shrink-0">
              {displayLogo ? (
                <img src={displayLogo} alt="logo" className="w-full h-full object-cover rounded-full" />
              ) : (
                <svg viewBox="0 0 24 24" fill="white" className="w-6 h-6">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
                </svg>
              )}
            </div>
            <div className="text-white min-w-0">
              <div className="text-sm font-semibold leading-tight truncate">{title || 'AI Ассистент'}</div>
              <div className="text-xs opacity-90 truncate">{subtitle || 'Турагентство'}</div>
            </div>
          </div>

          {/* Preview messages area */}
          <div className="bg-[#F8F9FA] px-4 py-4 min-h-[160px]">
            <div className="flex gap-2 items-start">
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 overflow-hidden"
                style={{ background: displayLogo ? 'transparent' : gradientBg }}
              >
                {displayLogo ? (
                  <img src={displayLogo} alt="" className="w-full h-full object-cover rounded-full" />
                ) : (
                  <svg viewBox="0 0 24 24" fill="white" className="w-4 h-4">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
                  </svg>
                )}
              </div>
              <div className="bg-white rounded-2xl rounded-bl-md shadow-sm px-3 py-2.5 text-xs text-text leading-relaxed max-w-[280px]">
                <span dangerouslySetInnerHTML={{ __html: formatWelcomePreview(welcomeMsg) }} />
              </div>
            </div>
          </div>

          {/* Preview footer */}
          <div className="bg-white border-t border-border/40 px-4 py-3 flex gap-2 items-center">
            <div className="flex-1 bg-[#F8F9FA] rounded-full px-3 py-2 text-xs text-text-secondary">
              Введите ваш запрос...
            </div>
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center"
              style={{ background: gradientBg }}
            >
              <svg viewBox="0 0 24 24" fill="white" className="w-4 h-4">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            </div>
          </div>
        </div>
        <p className="text-xs text-text-secondary text-center mt-3">
          Так виджет будет выглядеть на вашем сайте
        </p>
      </div>

      {/* Logo Upload */}
      <div className="bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-3">
        <h3 className="text-sm font-semibold text-text mb-4">Логотип</h3>
        <p className="text-xs text-text-secondary mb-3">
          Отображается в шапке виджета и в аватаре бота. PNG, JPG или WebP, до 2 МБ.
        </p>

        <div className="flex items-start gap-4">
          {displayLogo ? (
            <div className="relative group">
              <img
                src={displayLogo}
                alt="Логотип"
                className="w-20 h-20 rounded-full object-cover border-2 border-border/40 shadow-sm"
              />
              {uploadingLogo && (
                <div className="absolute inset-0 bg-black/40 rounded-full flex items-center justify-center">
                  <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                </div>
              )}
              <button
                onClick={handleLogoDelete}
                className="absolute -top-1 -right-1 w-6 h-6 rounded-full bg-red-500 text-white flex items-center justify-center shadow-sm opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600"
                title="Удалить логотип"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ) : (
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              className={`w-20 h-20 rounded-full border-2 border-dashed flex flex-col items-center justify-center cursor-pointer transition-all ${
                dragOver
                  ? 'border-primary bg-primary/5'
                  : 'border-border/60 hover:border-primary/50 hover:bg-primary/5'
              }`}
            >
              {uploadingLogo ? (
                <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              ) : (
                <>
                  <ImageIcon size={18} className="text-text-secondary mb-0.5" />
                  <span className="text-[10px] text-text-secondary">Загрузить</span>
                </>
              )}
            </div>
          )}

          <div className="flex flex-col gap-1.5 pt-1">
            <button
              onClick={() => fileInputRef.current?.click()}
              className="text-xs font-medium text-primary hover:text-primary-dark transition-colors flex items-center gap-1"
            >
              <Upload size={12} />
              {logoUrl ? 'Заменить логотип' : 'Загрузить логотип'}
            </button>
            <span className="text-[10px] text-text-secondary">
              Рекомендуемый размер: 88×88 px
            </span>
          </div>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleLogoUpload(file);
            e.target.value = '';
          }}
        />

        <div className="mt-5 pt-5 border-t border-border/40">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles size={14} className="text-primary" />
            <h4 className="text-sm font-semibold text-text">Готовые аватары</h4>
          </div>
          <p className="text-xs text-text-secondary mb-3">
            Выберите один из готовых вариантов, если не хотите загружать свой логотип
          </p>
          <div className="flex flex-wrap gap-3">
            {PRESET_LIST.map((preset) => {
              const isActive = activePreset === preset.id;
              const src = preset.type === 'svg'
                ? presetSvgDataUrl(preset.id, primaryColor)
                : preset.url;
              return (
                <button
                  key={preset.id}
                  onClick={() => handlePresetSelect(preset)}
                  className={`flex flex-col items-center gap-1.5 p-2 rounded-xl transition-all ${
                    isActive
                      ? 'bg-primary/10 ring-2 ring-primary shadow-sm'
                      : 'bg-surface-sunken hover:bg-primary/5 hover:ring-1 hover:ring-primary/30'
                  }`}
                  title={preset.label}
                >
                  <img
                    src={src}
                    alt={preset.label}
                    className="w-14 h-14 rounded-full object-cover"
                    draggable={false}
                  />
                  <span className={`text-[10px] font-medium leading-tight text-center max-w-[72px] ${
                    isActive ? 'text-primary' : 'text-text-secondary'
                  }`}>
                    {preset.label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Settings form */}
      <div className="bg-white rounded-2xl shadow-sm p-5 space-y-4 animate-fade-in-up stagger-4">
        <h3 className="text-sm font-semibold text-text">Параметры</h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-text-secondary mb-1.5">Заголовок виджета</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={40}
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-xs"
              placeholder="AI Ассистент"
            />
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1.5">Подзаголовок</label>
            <input
              type="text"
              value={subtitle}
              onChange={(e) => setSubtitle(e.target.value)}
              maxLength={40}
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-xs"
              placeholder="Турагентство"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm text-text-secondary mb-1.5">Приветственное сообщение</label>
          <textarea
            value={welcomeMsg}
            onChange={(e) => setWelcomeMsg(e.target.value)}
            rows={5}
            className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary resize-none shadow-xs"
            placeholder="Привет! Помогу подобрать тур."
          />
        </div>

        <div>
          <label className="block text-sm text-text-secondary mb-1.5">Позиция на странице</label>
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
                    ? 'text-white border-transparent shadow-sm'
                    : 'bg-white text-text-secondary border-border/60 hover:border-primary'
                }`}
                style={position === opt.value ? { background: gradientBg } : {}}
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
            <div
              className="w-10 h-10 rounded-xl shadow-inner border border-border/20"
              style={{ background: gradientBg }}
              title="Предварительный просмотр градиента"
            />
          </div>
        </div>

        <div className="flex gap-3 pt-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="text-white text-sm font-medium px-5 py-2.5 rounded-xl transition-all disabled:opacity-60 shadow-sm hover:shadow-md flex items-center gap-2"
            style={{ background: gradientBg }}
          >
            <Save size={14} />
            {saving ? 'Сохранение...' : 'Сохранить'}
          </button>
          <button
            onClick={() => setShowResetConfirm(true)}
            className="bg-surface-sunken text-text-secondary text-sm font-medium px-4 py-2.5 rounded-xl transition-all hover:bg-border/30 flex items-center gap-2"
          >
            <RotateCcw size={14} />
            Сбросить к стандартным
          </button>
        </div>

        {/* Reset confirmation */}
        {showResetConfirm && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3 animate-fade-in-up">
            <div className="flex-1">
              <p className="text-sm font-medium text-red-800">Сбросить все настройки?</p>
              <p className="text-xs text-red-600 mt-0.5">
                Все параметры виджета будут возвращены к значениям по умолчанию. Это действие нельзя отменить.
              </p>
            </div>
            <div className="flex gap-2 flex-shrink-0">
              <button
                onClick={() => setShowResetConfirm(false)}
                className="px-3 py-1.5 text-xs font-medium text-text-secondary bg-white border border-border/60 rounded-lg hover:bg-surface-sunken transition-all"
              >
                Отмена
              </button>
              <button
                onClick={handleReset}
                className="px-3 py-1.5 text-xs font-medium text-white bg-red-500 rounded-lg hover:bg-red-600 transition-all"
              >
                Да, сбросить
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Embed code */}
      <div className="bg-white rounded-2xl shadow-sm p-5 animate-fade-in-up stagger-5">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-7 h-7 rounded-lg bg-primary-50 flex items-center justify-center">
            <Code2 size={14} className="text-primary" />
          </div>
          <h3 className="text-sm font-semibold text-text">Код для встраивания</h3>
        </div>

        {embedData?.embed_code ? (
          <>
            <div className="relative">
              <pre className="bg-surface-sunken rounded-xl p-4 text-xs font-mono overflow-x-auto whitespace-pre-wrap break-all">
                {embedData.embed_code}
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
                <li>
                  Вставьте перед закрывающим тегом{' '}
                  <code className="bg-surface-sunken px-1.5 py-0.5 rounded-md font-mono">&lt;/body&gt;</code>{' '}
                  на вашем сайте
                </li>
                <li>Виджет автоматически появится на странице</li>
              </ol>
            </div>
          </>
        ) : (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-xs text-amber-800">
            {embedData?.error || 'Для получения кода встраивания сначала укажите URL сервера бота в настройках выше и сохраните.'}
          </div>
        )}
      </div>
    </div>
  );
}
