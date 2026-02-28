export default function LoadingSkeleton({ rows = 3, className = '' }) {
  return (
    <div className={`space-y-3 animate-pulse ${className}`}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-4 bg-surface-sunken rounded-lg" style={{ width: `${85 - i * 8}%` }} />
      ))}
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="bg-white rounded-2xl shadow-sm p-5 animate-pulse">
      <div className="h-3 w-24 bg-surface-sunken rounded mb-3" />
      <div className="h-7 w-16 bg-surface-sunken rounded" />
    </div>
  );
}
