// What every page of the Super Admin portal shares: loading from the backend, and the states a
// page can be in besides showing its data.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { EmptyState, ErrorState } from "../../ui";

// Loads with load() now and whenever one of deps changes. An answer that arrives after a newer
// request was made, or after the page was left, is thrown away.
export function useLoaded(load, deps) {
  const [state, setState] = useState({ loading: true, error: null, value: null });
  const latest = useRef(0);
  const reload = useCallback(async () => {
    const mine = ++latest.current;
    setState(previous => ({ ...previous, loading: true, error: null }));
    try {
      const value = await load();
      if (mine === latest.current) setState({ loading: false, error: null, value });
    } catch (error) {
      if (mine === latest.current) setState(previous => ({ loading: false, error, value: previous.value }));
    }
  }, deps);
  useEffect(() => {
    reload();
    return () => { latest.current += 1; };
  }, [reload]);
  return { ...state, reload };
}

export function NotAllowed() {
  return <EmptyState icon={ShieldAlert} title="Not allowed" message="Only a super admin can see this. If your role was changed a moment ago, log in again." />;
}

export function LoadFailed({ error, onRetry, what }) {
  return <ErrorState title={`Could not load ${what}`} message={error?.message || "The backend did not answer."} onRetry={onRetry} />;
}
