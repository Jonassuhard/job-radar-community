import { createContext, useContext } from "react";

export type RunAuthenticated = <T>(operation: (token: string) => Promise<T>) => Promise<T>;

export type SessionState = {
  token: string | null;
  isPending: boolean;
  isAvailable: boolean;
  hasError: boolean;
  retry: () => void;
  runAuthenticated: RunAuthenticated;
};

const unavailableRequest: RunAuthenticated = async () => {
  throw new Error("Session locale indisponible.");
};

export const SessionContext = createContext<SessionState>({
  token: null,
  isPending: true,
  isAvailable: false,
  hasError: false,
  retry: () => undefined,
  runAuthenticated: unavailableRequest,
});

export function useSession(): SessionState {
  return useContext(SessionContext);
}
