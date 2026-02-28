import { useState } from 'react';
import { Bot, UserRound } from 'lucide-react';
import TourCardPreview from './TourCardPreview';

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

const COLLAPSE_THRESHOLD = 500;

export default function MessageBubble({ message, onTourCardClick }) {
  const [expanded, setExpanded] = useState(false);
  const isUser = message.role === 'user';

  if (message.role === 'tool') return null;

  const hasTourCards = message.tour_cards && message.tour_cards.length > 0;
  const content = message.content || '';

  if (!isUser && !content.trim() && !hasTourCards) return null;

  const isLong = content.length > COLLAPSE_THRESHOLD;
  const displayContent = isLong && !expanded ? content.slice(0, COLLAPSE_THRESHOLD) + '...' : content;

  return (
    <div className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : ''} mb-3 animate-fade-in`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${
        isUser
          ? 'bg-primary-50 text-primary/70'
          : 'bg-primary-50 text-primary'
      }`}>
        {isUser ? <UserRound size={14} /> : <Bot size={14} />}
      </div>

      <div className={`max-w-[75%] ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        {content.trim() && (
          <div className={`
            rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-xs
            ${isUser
              ? 'bg-primary-50 text-text rounded-br-md border border-primary/10'
              : 'bg-white text-text rounded-bl-md border border-border/40'
            }
          `}>
            <p className="whitespace-pre-wrap">{displayContent}</p>
            {isLong && (
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-primary text-xs font-medium mt-1 hover:underline"
              >
                {expanded ? 'Свернуть' : 'Читать далее'}
              </button>
            )}
          </div>
        )}

        {content.trim() && (
          <div className={`flex items-center gap-2 mt-1 ${isUser ? 'flex-row-reverse' : ''}`}>
            {message.created_at && (
              <span className="text-[10px] text-text-secondary/60">{formatTime(message.created_at)}</span>
            )}
          </div>
        )}

        {hasTourCards && (
          <div className="mt-2 w-full">
            <div className="border-t border-border/30 pt-2 mt-1 mb-2">
              <span className="text-[11px] text-text-secondary">Предложенные варианты</span>
            </div>
            <div className="space-y-2">
              {message.tour_cards.map((card, i) => (
                <TourCardPreview key={i} card={card} onClick={onTourCardClick ? () => onTourCardClick(card) : undefined} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
