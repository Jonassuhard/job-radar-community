import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { lazy, Suspense, useCallback, useState } from "react";

import { RadarPage } from "../features/radar/RadarPage";
import { ApiError, fetchSessionToken } from "../lib/api";
import { AppShell } from "./AppShell";
import { SessionContext, type RunAuthenticated } from "./SessionContext";

const InsightsPage = lazy(() =>
  import("../features/insights/InsightsPage").then((module) => ({ default: module.InsightsPage })),
);
const SourcesPage = lazy(() =>
  import("../features/sources/SourcesPage").then((module) => ({ default: module.SourcesPage })),
);
const ConfigurationPage = lazy(() =>
  import("../features/config/ConfigurationPage").then((module) => ({ default: module.ConfigurationPage })),
);

function DeferredPage({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<div className="route-loading" role="status">Ouverture de la vue…</div>}>
      {children}
    </Suspense>
  );
}

function RoutedApp() {
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: fetchSessionToken,
    staleTime: Number.POSITIVE_INFINITY,
    retry: (failureCount, error) =>
      failureCount < 1 && (!(error instanceof ApiError) || error.status >= 500),
    retryDelay: 50,
  });
  const rebootstrap = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["session"], refetchType: "none" });
    return queryClient.fetchQuery({
      queryKey: ["session"],
      queryFn: fetchSessionToken,
      staleTime: Number.POSITIVE_INFINITY,
      retry: false,
    });
  }, [queryClient]);
  const runAuthenticated = useCallback<RunAuthenticated>(
    async (operation) => {
      const initialToken = session.data ?? (await rebootstrap());
      try {
        return await operation(initialToken);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        const refreshedToken = await rebootstrap();
        return operation(refreshedToken);
      }
    },
    [rebootstrap, session.data],
  );
  return (
    <SessionContext.Provider
      value={{
        token: session.data ?? null,
        isPending: session.isPending,
        isAvailable: session.isSuccess,
        hasError: session.isError,
        retry: () => void session.refetch(),
        runAuthenticated,
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Navigate replace to="/radar" />} />
            <Route path="radar" element={<RadarPage />} />
            <Route path="insights" element={<DeferredPage><InsightsPage /></DeferredPage>} />
            <Route path="sources" element={<DeferredPage><SourcesPage /></DeferredPage>} />
            <Route path="configuration" element={<DeferredPage><ConfigurationPage /></DeferredPage>} />
            <Route path="*" element={<Navigate replace to="/radar" />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </SessionContext.Provider>
  );
}

export function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <RoutedApp />
    </QueryClientProvider>
  );
}
