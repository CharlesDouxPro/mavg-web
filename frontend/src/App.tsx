import { useEffect, useState } from "react";
import { ApiError, api, type FormConfig } from "./api";
import { RecentTasks } from "./RecentTasks";
import { TaskForm } from "./TaskForm";

export function App() {
  const [config, setConfig] = useState<FormConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api
      .form()
      .then(setConfig)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  return (
    <div className="page">
      <header className="page-header">
        <h1>Nouvelle tâche</h1>
        <p>Pousse une tâche en <code>pending</code> dans la file MongoDB du worker MAVG.</p>
      </header>
      {error && <p className="notice error">Impossible de charger le formulaire : {error}</p>}
      {!config && !error && <p className="help">Chargement…</p>}
      {config && (
        <div className="layout">
          <TaskForm config={config} onPushed={() => setRefreshKey((key) => key + 1)} />
          <aside>
            <RecentTasks refreshKey={refreshKey} />
          </aside>
        </div>
      )}
    </div>
  );
}
