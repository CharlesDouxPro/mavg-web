// La file vue depuis le formulaire : les dernières tâches et leur statut.

import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type TaskStatus, type TaskSummary } from "./api";

const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: "en attente",
  working: "en cours",
  done: "terminée",
  failed: "échouée",
};

const dateFormat = new Intl.DateTimeFormat("fr-FR", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function RecentTasks({ refreshKey }: { refreshKey: number }) {
  const [tasks, setTasks] = useState<TaskSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTasks(await api.tasks());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  return (
    <section className="card recent" aria-labelledby="recent-title">
      <header>
        <h2 id="recent-title">File de tâches</h2>
        <button type="button" className="ghost" onClick={() => void load()} disabled={loading}>
          {loading ? "…" : "Rafraîchir"}
        </button>
      </header>
      <p className="help">
        Le worker prend la tâche <code>pending</code> la plus récente en premier, et ne tourne que lorsqu'il est lancé.
      </p>
      {error && <p className="notice error">{error}</p>}
      {tasks && tasks.length === 0 && <p className="help">Aucune tâche dans la collection.</p>}
      <ul>
        {tasks?.map((task) => (
          <li key={task.task_id + (task.created_at ?? "")}>
            <div className="task-line">
              <span className={`status ${task.status}`}>{STATUS_LABELS[task.status] ?? task.status}</span>
              <code className="task-id" title={task.task_id}>
                {task.task_id}
              </code>
            </div>
            <div className="task-meta">
              {task.channel_name}
              {task.created_at && ` · ${dateFormat.format(new Date(task.created_at))}`}
            </div>
            {task.error && (
              <details>
                <summary>Erreur</summary>
                <pre>{task.error}</pre>
              </details>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
