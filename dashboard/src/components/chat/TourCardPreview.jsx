import { MapPin, Star, Utensils, Calendar, Moon, Plane, ExternalLink } from 'lucide-react';

export default function TourCardPreview({ card, onClick }) {
  const stars = card.hotel_stars || card.stars || 0;

  return (
    <div
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={`
        bg-white border border-border/60 rounded-xl p-3 flex gap-3 text-xs shadow-xs
        transition-all group/card
        ${onClick ? 'cursor-pointer hover:shadow-md hover:border-primary/30 hover:-translate-y-0.5' : 'hover:shadow-sm'}
      `}
    >
      {card.hotel_image && (
        <img
          src={card.hotel_image}
          alt={card.hotel_name}
          className="w-20 h-20 rounded-lg object-cover shrink-0"
          onError={(e) => { e.target.style.display = 'none'; }}
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-1">
          <span className="font-semibold text-text truncate text-[13px]">{card.hotel_name || 'Отель'}</span>
          {stars > 0 && (
            <span className="flex items-center text-warning shrink-0">
              {Array.from({ length: stars }).map((_, i) => (
                <Star key={i} size={10} fill="currentColor" />
              ))}
            </span>
          )}
          {onClick && (
            <ExternalLink size={10} className="text-text-secondary/0 group-hover/card:text-primary transition-colors shrink-0 ml-auto" />
          )}
        </div>

        <div className="flex items-center gap-1 text-text-secondary">
          <MapPin size={10} className="shrink-0" />
          <span className="truncate">{card.country}{card.resort ? ` / ${card.resort}` : ''}</span>
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1.5 text-text-secondary">
          {card.meal_description && (
            <span className="flex items-center gap-1">
              <Utensils size={10} />
              {card.meal_description}
            </span>
          )}
          {(card.date || card.flydate) && (
            <span className="flex items-center gap-1">
              <Calendar size={10} />
              {card.date || card.flydate}
            </span>
          )}
          {card.nights && (
            <span className="flex items-center gap-1">
              <Moon size={10} />
              {card.nights} ноч.
            </span>
          )}
          {card.operator && (
            <span className="flex items-center gap-1">
              <Plane size={10} />
              {card.operator}
            </span>
          )}
        </div>

        {card.price && (
          <div className="mt-1.5 text-primary font-bold text-sm">
            {new Intl.NumberFormat('ru-RU').format(card.price)} ₽
          </div>
        )}
      </div>
    </div>
  );
}
