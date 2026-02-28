import { ChevronLeft, ChevronRight } from 'lucide-react';

export default function DataTable({ columns, rows, page, pages, onPageChange, onRowClick }) {
  return (
    <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-sunken/60">
              {columns.map((col) => (
                <th key={col.key} className="px-4 py-3 text-left text-[11px] font-semibold text-text-secondary uppercase tracking-wider">
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={row.id || i}
                onClick={() => onRowClick?.(row)}
                className={`border-t border-border/40 transition-colors ${
                  onRowClick ? 'cursor-pointer hover:bg-primary-50/40' : ''
                }`}
              >
                {columns.map((col) => (
                  <td key={col.key} className="px-4 py-3 text-text whitespace-nowrap">
                    {col.render ? col.render(row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-border/40 bg-surface-sunken/40">
          <span className="text-xs text-text-secondary">
            Страница {page} из {pages}
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => onPageChange?.(page - 1)}
              disabled={page <= 1}
              className="p-1.5 rounded-lg hover:bg-white hover:shadow-xs disabled:opacity-30 transition-all"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              onClick={() => onPageChange?.(page + 1)}
              disabled={page >= pages}
              className="p-1.5 rounded-lg hover:bg-white hover:shadow-xs disabled:opacity-30 transition-all"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
