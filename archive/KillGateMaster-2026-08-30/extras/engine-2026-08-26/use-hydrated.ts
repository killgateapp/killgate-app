import { useEffect, useState } from "react";
import { useKillgate } from "./store.ts";

export function useHydrated() {
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const unsub = useKillgate.persist.onFinishHydration(() => setHydrated(true));
    if (useKillgate.persist.hasHydrated()) setHydrated(true);
    return unsub;
  }, []);

  return hydrated;
}
