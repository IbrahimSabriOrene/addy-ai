import {readLocalEdit} from "./localEdits";
import {req,USE_MOCK} from "@/api/client";
import { Platform } from "react-native";
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";
import { getToken } from "./auth";

export async function exportPrivateMedia(url: string, filename: string, mimeType: "image/png" | "image/jpeg" | "image/webp" | "video/mp4" | "video/webm", action: "download" | "prepare-share" = "download") {
  if(url.startsWith("addy-edit://")){
    const email=USE_MOCK?"demo":(await req<{email:string}>("/v1/account")).email;
    const local=await readLocalEdit(email,url.slice("addy-edit://".length));
    try{
      if(local.mimeType!==mimeType)throw Error("Export format does not match this edited file.");
      if(Platform.OS==="web"){
        const blob=await (await fetch(local.uri)).blob();
        if(action==="prepare-share")return new File([blob],filename,{type:mimeType});
        const link=document.createElement("a");link.href=local.uri;link.download=filename;document.body.appendChild(link);link.click();link.remove();
      }else{
        if(!await Sharing.isAvailableAsync())throw Error("Sharing is unavailable on this device.");
        await Sharing.shareAsync(local.uri,{mimeType,dialogTitle:"Save or share your edited creation"});
      }
    }finally{if(Platform.OS==="web")setTimeout(()=>URL.revokeObjectURL(local.uri),1000);}
    return;
  }
  const api = process.env.EXPO_PUBLIC_API_URL;
  const samples = ["pedestal_spin", "skincare_glow", "bakery_morning", "jewelry_detail", "coffee_ritual", "leather_editorial", "candle_dusk", "gift_unwrap", "tech_light", "pet_boutique"];
  const demo = !api && Platform.OS === "web" && (
    (mimeType === "video/mp4" && (url === "/mock/sample-ad.mp4" || samples.filter(id => id !== "pet_boutique").some(id => url === `/previews/${id}.mp4`))) ||
    (mimeType === "image/png" && samples.some(id => url === `/previews/${id}.png`)));

  if (demo && action === "download") {
    const link = document.createElement("a");
    link.href = url; link.download = mimeType === "video/mp4" ? "addy-demo-sample.mp4" : "addy-demo-sample.png";
    document.body.appendChild(link); link.click(); link.remove();
    return;
  }
  if (!demo && (!api || new URL(url).origin !== new URL(api).origin)) throw Error("This file is not from your connected account service.");
  const token = demo ? null : await getToken();
  if (!demo && !token) throw Error("Sign in again to export this file.");
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  const safeName = filename.replace(/[^a-zA-Z0-9._-]/g, "_");
  if (Platform.OS === "web") {
    const response = await fetch(url, { headers, redirect: "error" });
    if (!response.ok || response.headers.get("content-type")?.split(";")[0] !== mimeType) throw Error("Could not download this file. Refresh and try again.");
    const blob = await response.blob();
    if (!blob.size) throw Error("The downloaded file is empty.");
    if (action === "prepare-share") return new File([blob], safeName, { type: mimeType });
    const objectUrl = URL.createObjectURL(blob);
    try {
      const link = document.createElement("a");
      link.href = objectUrl; link.download = safeName;
      document.body.appendChild(link); link.click(); link.remove();
    } finally { setTimeout(() => URL.revokeObjectURL(objectUrl), 1000); }
    return;
  }
  if (!FileSystem.cacheDirectory || !await Sharing.isAvailableAsync()) throw Error("File sharing is unavailable on this device.");
  const directory = `${FileSystem.cacheDirectory}export-${Date.now()}-${Math.random().toString(36).slice(2)}/`;
  try {
    await FileSystem.makeDirectoryAsync(directory, { intermediates: true });
    const destination = `${directory}${safeName}`;
    const result = await FileSystem.downloadAsync(url, destination, { headers });
    const contentType = Object.entries(result.headers).find(([key]) => key.toLowerCase() === "content-type")?.[1]?.split(";")[0];
    const info = await FileSystem.getInfoAsync(destination);
    if (result.status !== 200 || contentType !== mimeType || !info.exists || !("size" in info) || !info.size) throw Error("Could not download this file. Refresh and try again.");
    await Sharing.shareAsync(destination, { mimeType, UTI: { "image/png": "public.png", "image/jpeg": "public.jpeg", "image/webp": "org.webmproject.webp", "video/mp4": "public.mpeg-4", "video/webm":"org.webmproject.webm" }[mimeType], dialogTitle: "Save or share your Addy AI file" });
  } finally { await FileSystem.deleteAsync(directory, { idempotent: true }); }
}
