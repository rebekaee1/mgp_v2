import { useEffect, useCallback } from 'react';
import { X, MapPin, Star, Utensils, Calendar, Moon, Plane, Users, DollarSign } from 'lucide-react';

export default function TourCardModal({ card, onClose }) {
  const stars = card.hotel_stars || card.stars || 0;

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [handleKeyDown]);

  const details = [
    card.country && { icon: MapPin, label: 'Страна', value: card.country },
    card.resort && { icon: MapPin, label: 'Курорт', value: card.resort },
    card.meal_description && { icon: Utensils, label: 'Питание', value: card.meal_description },
    (card.date || card.flydate) && { icon: Calendar, label: 'Дата вылета', value: card.date || card.flydate },
    card.nights && { icon: Moon, label: 'Ночей', value: `${card.nights}` },
    card.operator && { icon: Plane, label: 'Оператор', value: card.operator },
    card.adults && { icon: Users, label: 'Взрослых', value: `${card.adults}` },
    card.children && { icon: Users, label: 'Детей', value: `${card.children}` },
    card.room && { icon: DollarSign, label: 'Номер', value: card.room },
  ].filter(Boolean);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
      <div
        className="relative bg-white rounded-2xl shadow-lg max-w-lg w-full overflow-hidden animate-slide-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header image */}
        {card.hotel_image && (
          <div className="relative h-48 bg-surface-sunken">
            <img
              src={card.hotel_image}
              alt={card.hotel_name}
              className="w-full h-full object-cover"
              onError={(e) => { e.target.parentElement.style.display = 'none'; }}
            />
            <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent" />
            <button
              onClick={onClose}
              className="absolute top-3 right-3 w-8 h-8 rounded-full bg-white/90 backdrop-blur flex items-center justify-center text-text hover:bg-white transition-colors shadow-sm"
            >
              <X size={16} />
            </button>
            <div className="absolute bottom-3 left-4 right-4">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-white drop-shadow-md">{card.hotel_name || 'Отель'}</h2>
                {stars > 0 && (
                  <span className="flex items-center text-warning">
                    {Array.from({ length: stars }).map((_, i) => (
                      <Star key={i} size={14} fill="currentColor" />
                    ))}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        {!card.hotel_image && (
          <div className="px-5 pt-5 pb-2 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-bold text-text">{card.hotel_name || 'Отель'}</h2>
              {stars > 0 && (
                <span className="flex items-center text-warning mt-0.5">
                  {Array.from({ length: stars }).map((_, i) => (
                    <Star key={i} size={12} fill="currentColor" />
                  ))}
                </span>
              )}
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-full bg-surface-sunken flex items-center justify-center text-text-secondary hover:text-text transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        )}

        {/* Price highlight */}
        {card.price && (
          <div className="px-5 py-3 bg-primary-50 border-y border-primary/10 flex items-center justify-between">
            <span className="text-xs text-text-secondary">Стоимость тура</span>
            <span className="text-xl font-bold text-primary">
              {new Intl.NumberFormat('ru-RU').format(card.price)} ₽
            </span>
          </div>
        )}

        {/* Details grid */}
        <div className="p-5">
          <div className="grid grid-cols-2 gap-3">
            {details.map((item, i) => (
              <div key={i} className="flex items-start gap-2.5 py-2 px-3 rounded-xl bg-surface-sunken/50">
                <item.icon size={14} className="text-primary/60 mt-0.5 shrink-0" />
                <div>
                  <p className="text-[10px] text-text-secondary">{item.label}</p>
                  <p className="text-xs font-medium text-text">{item.value}</p>
                </div>
              </div>
            ))}
          </div>

          <button
            onClick={onClose}
            className="w-full mt-4 py-2.5 text-sm font-medium text-text-secondary bg-surface-sunken rounded-xl hover:bg-surface hover:text-text transition-colors"
          >
            Закрыть
          </button>
        </div>
      </div>
    </div>
  );
}
