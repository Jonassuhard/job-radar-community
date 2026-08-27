import * as Tooltip from "@radix-ui/react-tooltip";
import { BarChart3, Database, Radar, RefreshCw, SlidersHorizontal } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { useSession } from "./SessionContext";

const navigation = [
  { to: "/radar", label: "Radar", icon: Radar },
  { to: "/insights", label: "Insights", icon: BarChart3 },
  { to: "/sources", label: "Sources", icon: Database },
  { to: "/configuration", label: "Configuration", icon: SlidersHorizontal },
];

export function AppShell() {
  const session = useSession();
  return (
    <Tooltip.Provider delayDuration={450}>
      <div className="app-shell">
        <header className="brand-bar">
          <NavLink className="wordmark" to="/radar" aria-label="Job Radar, accueil">
            <span className="wordmark-mark" aria-hidden="true">
              JR
            </span>
            <span>JOB RADAR</span>
          </NavLink>
          {session.hasError ? (
            <button
              className="session-retry"
              type="button"
              aria-label="Réessayer la session locale"
              onClick={session.retry}
            >
              <RefreshCw aria-hidden="true" size={14} /> Réessayer
            </button>
          ) : (
            <span
              className="local-status"
              aria-label={session.isAvailable ? "Session locale active" : "Initialisation de la session locale"}
            >
              <i aria-hidden="true" /> {session.isAvailable ? "Local" : "Connexion"}
            </span>
          )}
        </header>

        <nav className="primary-nav" aria-label="Navigation principale">
          {navigation.map(({ to, label, icon: Icon }) => (
            <Tooltip.Root key={to}>
              <Tooltip.Trigger asChild>
                <NavLink className="nav-link" to={to}>
                  <Icon aria-hidden="true" size={19} strokeWidth={1.8} />
                  <span>{label}</span>
                </NavLink>
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Content className="tooltip" side="right" sideOffset={8}>
                  {label}
                  <Tooltip.Arrow className="tooltip-arrow" />
                </Tooltip.Content>
              </Tooltip.Portal>
            </Tooltip.Root>
          ))}
        </nav>

        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </Tooltip.Provider>
  );
}
