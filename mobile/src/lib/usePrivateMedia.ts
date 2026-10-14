import {readLocalEdit} from "./localEdits";
import {req,USE_MOCK} from "@/api/client";
import { useEffect, useState } from "react";
import { Platform } from "react-native";
import { getToken } from "./auth";

export function usePrivateMedia(url: string) {
  const [source, setSource] = useState<{ uri: string; headers?: Record<string, string> } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let objectUrl: string | undefined;
    setSource(null);
    setError("");
    if (!url) return;
    void (async () => {
      try {
        if(url.startsWith("addy-edit://")){
          const email=USE_MOCK?"demo":(await req<{email:string}>("/v1/account")).email;
          const local=await readLocalEdit(email,url.slice("addy-edit://".length));
          if(Platform.OS==="web")objectUrl=local.uri;
          if(active)setSource({uri:local.uri});else if(objectUrl)URL.revokeObjectURL(objectUrl);
          return;
        }
        const token = await getToken();
        const api = process.env.EXPO_PUBLIC_API_URL;
        const headers: Record<string, string> = token && api && new URL(url).origin === new URL(api).origin ? { Authorization: `Bearer ${token}` } : {};
        if (Platform.OS === "web" && headers.Authorization) {
          const response = await fetch(url, { headers });
          if (!response.ok) throw Error("Could not load this media. Refresh the result and try again.");
          const blob = await response.blob();
          if (!active) return;
          objectUrl = URL.createObjectURL(blob);
          setSource({ uri: objectUrl });
        } else if (active) setSource({ uri: url, headers });
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "Could not load media."); }
    })();
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [url]);
  return { source, error };
}
