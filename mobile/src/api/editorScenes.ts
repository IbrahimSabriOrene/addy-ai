import AsyncStorage from "@react-native-async-storage/async-storage";
import { writeAccountDraft } from "../lib/accountDrafts";
import { req, USE_MOCK, uploadImage } from "./client";
import { createFromDraft, getCatalogue, type CreationCommand } from "./creation";

export const EDITOR_SCENES = [
  { id: "editor_lifestyle", name: "Lifestyle" },
  { id: "editor_studio", name: "Studio" },
  { id: "editor_minimal", name: "Minimal" },
  { id: "editor_editorial", name: "Editorial" },
] as const;
export type EditorSceneId = typeof EDITOR_SCENES[number]["id"];
type SceneDraft = { assetKey?: string; scenes: Partial<Record<EditorSceneId, { command: CreationCommand; jobId?: string }>> };
const pending = new Map<string, Promise<string>>();

/** One source upload and one durable command per scene, scoped to the original editor draft. */
export function generateEditorScene(draftKey: string, sourceUri: string, sceneId: EditorSceneId, confirmedCredits: number, outputKind: "photo" | "video" = "photo", referenceAssetKey?: string, photoPlatform: "feed"|"stories" = "feed"): Promise<string> {
  if (!draftKey.startsWith("addy:create:") || !EDITOR_SCENES.some(scene => scene.id === sceneId)) return Promise.reject(Error("Invalid editing scene."));
  // Serialize all scenes for this source so parallel taps also share the source asset.
  const previous = pending.get(draftKey) ?? Promise.resolve("");
  const task = previous.catch(() => "").then(async () => {
    if (USE_MOCK) throw Error("AI scene generation is unavailable in this demo.");
    const key = draftKey + ":scenes";
    const raw = await AsyncStorage.getItem(key);
    const saved: SceneDraft = raw ? JSON.parse(raw) : { scenes: {} };
    if (!saved || typeof saved.scenes !== "object" || !saved.scenes || Array.isArray(saved.scenes)) throw Error("Could not read your saved scene request.");
    const templateId=sceneId+(outputKind==="video"?"_video":"");
    let scene = saved.scenes[sceneId];
    if(scene&&scene.command?.body?.outputKind!==outputKind)throw Error("This saved scene has a different media type.");
    if (scene?.jobId) return scene.jobId;
    if (!scene) {
      if(outputKind==="video"&&!referenceAssetKey)throw Error("Review a generated scene photo before creating its video.");
      const catalogue = await getCatalogue();
      const mode = catalogue.modes?.[outputKind] ?? catalogue;
      const template = catalogue.items.find(item => item.id === templateId && item.outputKinds.includes(outputKind));
      if (!mode.generationEnabled || mode.executionMode !== "google" || !template) throw Error("AI scene generation is unavailable.");
      // The existing job admission endpoint currently reserves exactly one credit.
      if (catalogue.prices[outputKind] !== 1 || confirmedCredits !== catalogue.prices[outputKind]) throw Error("The scene price changed. Review it before generating.");
      const consent = await req<{ granted: boolean }>("/v1/account/ai-consent");
      if (!consent.granted) throw Error("AI-sharing permission is required before creating a scene.");
      if (outputKind==="photo"&&!saved.assetKey) {
        saved.assetKey = await uploadImage(sourceUri);
        await writeAccountDraft(key, JSON.stringify(saved));
      }
      scene = { command: { key: "editor-scene-" + Date.now() + "-" + Math.random().toString(36).slice(2), body: {
        assetKey: outputKind==="video"?referenceAssetKey!:saved.assetKey!, platforms: [outputKind==="photo"?photoPlatform:"reels"], fastMode: true, quality: "fast",
        templateId, templateVersion: template.version, outputKind, direction: "",
      } } };
      saved.scenes[sceneId] = scene;
      await writeAccountDraft(key, JSON.stringify(saved));
    }
    // An uncertain response must reuse the frozen command, even after configuration changes.
    if (scene.command?.body?.templateId !== templateId || scene.command.body.outputKind !== outputKind || !scene.command.key) throw Error("Could not read your saved scene request.");
    const job = await createFromDraft(scene.command);
    scene.jobId = job.id;
    await writeAccountDraft(key, JSON.stringify(saved));
    return job.id;
  });
  pending.set(draftKey, task);
  void task.finally(() => { if (pending.get(draftKey) === task) pending.delete(draftKey); }).catch(() => {});
  return task;
}
