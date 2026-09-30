// Tiroir latéral et notifications.

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

export function Drawer({
  open,
  onClose,
  wide,
  title,
  subtitle,
  actions,
  footer,
  children,
}: {
  open: boolean;
  onClose: () => void;
  wide?: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <aside className={`drawer${wide ? " wide" : ""}`} role="dialog" aria-modal>
        <header className="drawer-head">
          <div className="grow">
            <h3>{title}</h3>
            {subtitle && <div className="muted small" style={{ marginTop: 4 }}>{subtitle}</div>}
          </div>
          {actions}
          <button className="btn ghost icon" onClick={onClose} aria-label="Fermer">
            <Icon name="x" />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer && <footer className="drawer-foot">{footer}</footer>}
      </aside>
    </>
  );
}

type Tone = "ok" | "error" | "info";
interface Toast {
  id: number;
  tone: Tone;
  title: string;
  body?: ReactNode;
}

const ToastContext = createContext<(tone: Tone, title: string, body?: ReactNode) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Tone, title: string, body?: ReactNode) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current.slice(-3), { id, tone, title, body }]);
    setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), tone === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.tone}`}>
            <Icon name={toast.tone === "ok" ? "check" : toast.tone === "error" ? "alert" : "info"} />
            <div className="grow">
              <strong>{toast.title}</strong>
              {toast.body && <span className="muted">{toast.body}</span>}
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
