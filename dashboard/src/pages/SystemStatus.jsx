import { Database, Server, HardDrive, Bot } from 'lucide-react';
import StatusBadge from '../components/ui/StatusBadge';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import { useSystemHealth, useAssistants } from '../hooks/useDashboardAPI';

function StatusCard({ icon: Icon, title, status, details }) {
  return (
    <div className="bg-white rounded-2xl shadow-sm p-5 hover:shadow-md transition-shadow">
      <div className="flex items-center gap-3 mb-3">
        <div className="w-10 h-10 rounded-xl bg-primary-50 flex items-center justify-center">
          <Icon size={20} className="text-primary" strokeWidth={1.8} />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-text">{title}</h3>
          <StatusBadge status={status} />
        </div>
      </div>
      {details && (
        <div className="text-xs text-text-secondary space-y-0.5 mt-2">
          {details.map((d, i) => (
            <div key={i} className="flex justify-between">
              <span>{d.label}</span>
              <span className="text-text font-medium">{d.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function SystemStatus() {
  const { data: health, loading: loadingHealth } = useSystemHealth();
  const { data: assistantsData, loading: loadingAssistants } = useAssistants();

  if (loadingHealth || loadingAssistants) return <LoadingSkeleton rows={6} />;

  const assistants = assistantsData?.assistants || [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-text">Статус системы</h1>
        <p className="text-sm text-text-secondary mt-0.5">Мониторинг компонентов инфраструктуры</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="animate-fade-in-up stagger-1">
          <StatusCard
            icon={Database}
            title="PostgreSQL"
            status={health?.postgres || 'unavailable'}
          />
        </div>
        <div className="animate-fade-in-up stagger-2">
          <StatusCard
            icon={HardDrive}
            title="Redis"
            status={health?.redis || 'unavailable'}
          />
        </div>
        <div className="animate-fade-in-up stagger-3">
          <StatusCard
            icon={Server}
            title="Backend"
            status={health ? 'ok' : 'unavailable'}
          />
        </div>
      </div>

      {assistants.length > 0 && (
        <div className="bg-white rounded-2xl shadow-sm animate-fade-in-up stagger-4">
          <div className="px-5 py-4">
            <h3 className="text-sm font-semibold text-text">AI-ассистенты</h3>
          </div>
          <div className="border-t border-border/40">
            {assistants.map((a) => (
              <div key={a.id} className="flex items-center justify-between px-5 py-3 border-b border-border/30 last:border-0">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-xl bg-primary-50 flex items-center justify-center">
                    <Bot size={16} className="text-primary" />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-text">{a.name}</div>
                    <div className="text-xs text-text-secondary">
                      {a.llm_provider} / {a.llm_model}
                    </div>
                  </div>
                </div>
                <StatusBadge status={a.is_active ? 'active' : 'unavailable'} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
