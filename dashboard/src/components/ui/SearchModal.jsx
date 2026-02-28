import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, X, MessageSquare, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import api from '../../lib/api';

export default function SearchModal({ open, onClose }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (open) {
      setQuery('');
      setResults([]);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [open]);

  const search = useCallback(async (q) => {
    if (!q || q.length < 2) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.get('/dashboard/conversations', {
        params: { search: q, per_page: 8 },
      });
      setResults(data.items || []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => search(query), 300);
    return () => clearTimeout(timer);
  }, [query, search]);

  const handleSelect = (conv) => {
    onClose();
    navigate(`/conversations/${conv.id}`);
  };

  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    if (open) window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]" onClick={onClose}>
      <div className="absolute inset-0 bg-text/20 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-lg bg-white rounded-2xl shadow-lg overflow-hidden animate-fade-in-up"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <Search size={18} className="text-text-secondary shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по диалогам..."
            className="flex-1 text-sm bg-transparent outline-none placeholder:text-text-secondary/60"
          />
          <kbd className="hidden sm:flex items-center text-[10px] text-text-secondary bg-surface-sunken px-1.5 py-0.5 rounded font-mono">ESC</kbd>
          <button onClick={onClose} className="text-text-secondary hover:text-text transition-colors sm:hidden">
            <X size={18} />
          </button>
        </div>

        <div className="max-h-[320px] overflow-y-auto">
          {loading && (
            <div className="px-4 py-8 text-center text-sm text-text-secondary">Поиск...</div>
          )}
          {!loading && query.length >= 2 && results.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-text-secondary">Ничего не найдено</div>
          )}
          {!loading && results.map((conv) => (
            <button
              key={conv.id}
              onClick={() => handleSelect(conv)}
              className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-surface transition-colors group"
            >
              <div className="w-8 h-8 rounded-lg bg-primary-50 flex items-center justify-center shrink-0">
                <MessageSquare size={14} className="text-primary" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-text truncate">{conv.preview || 'Без текста'}</p>
                <p className="text-xs text-text-secondary mt-0.5">
                  {conv.message_count} сообщ. · {conv.search_count} поиск.
                </p>
              </div>
              <ArrowRight size={14} className="text-text-secondary opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
            </button>
          ))}
          {!loading && !query && (
            <div className="px-4 py-8 text-center text-sm text-text-secondary">
              Введите текст для поиска по содержимому диалогов
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
