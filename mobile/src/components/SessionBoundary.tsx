import React, { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { supabase } from "@/lib/supabase";

/** Unmount private views and remove cached data when the signed-in user changes. */
export function SessionBoundary({ children }: { children: React.ReactNode }) {
  const queries = useQueryClient();
  const [identity, setIdentity] = useState<string | null>(supabase ? null : "demo");
  useEffect(() => {
    if (!supabase) return;
    let previous: string | null = null;
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      const next = session?.user.id ?? "signed-out";
      if (next !== previous) {
        queries.clear();
        if (previous && previous !== "signed-out") {
          void import("@/lib/notifications").then(n => n.clearLocalNotifications()).catch(() => {});
        }
        previous = next;
        setIdentity(next);
      }
    });
    return () => data.subscription.unsubscribe();
  }, [queries]);
  if (identity === null) return null;
  return <React.Fragment key={identity}>{children}</React.Fragment>;
}
