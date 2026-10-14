import React from "react";
import { Redirect } from "expo-router";

/** Preserve old links while routing new work through the durable template flow. */
export default function UploadScreen() {
  return <Redirect href="/create/browse" />;
}
