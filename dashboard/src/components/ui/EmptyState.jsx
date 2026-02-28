import { Inbox } from 'lucide-react';

export default function EmptyState({
  title = 'Нет данных',
  description = 'Данные появятся после первых диалогов с ассистентом.',
  icon: Icon = Inbox,
  action,
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center animate-fade-in">
      <div className="w-16 h-16 rounded-2xl bg-surface-sunken flex items-center justify-center mb-4">
        <Icon size={28} className="text-text-secondary/40" strokeWidth={1.4} />
      </div>
      <h3 className="text-sm font-semibold text-text mb-1">{title}</h3>
      <p className="text-sm text-text-secondary max-w-sm leading-relaxed">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
