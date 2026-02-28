const config = {
  ok: { bg: 'bg-success-light', text: 'text-success', dot: 'bg-success', label: 'Работает' },
  active: { bg: 'bg-info-light', text: 'text-info', dot: 'bg-info', label: 'Активен' },
  unavailable: { bg: 'bg-danger-light', text: 'text-danger', dot: 'bg-danger', label: 'Недоступен' },
  down: { bg: 'bg-danger-light', text: 'text-danger', dot: 'bg-danger', label: 'Недоступен' },
};

export default function StatusBadge({ status }) {
  const c = config[status] || { bg: 'bg-surface', text: 'text-text-secondary', dot: 'bg-text-secondary', label: status };

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${c.bg} ${c.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot} animate-pulse`} />
      {c.label}
    </span>
  );
}
