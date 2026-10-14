import { useI18n, translate } from "@/i18n";
import React from "react";
import { useRouter } from "expo-router";
import { AuthError } from "@/api/client";
import { draftReturn } from "@/lib/draftReturn";
import { Button } from "./Button";

// These screens retain display messages; match the client's canonical auth failure.
const expiredSession = new AuthError().message;

export function ResumeSignIn({ error, returnTo }: { error: string; returnTo: string }) {
  useI18n();
  const router = useRouter();
  if (error !== expiredSession || !draftReturn(returnTo)) return null;
  return <Button label={translate("Sign in to resume your draft")} variant="secondary"
    onPress={() => router.push({ pathname: "/sign-in", params: { returnTo } })} />;
}
