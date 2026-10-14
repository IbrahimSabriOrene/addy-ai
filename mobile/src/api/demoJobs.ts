import AsyncStorage from "@react-native-async-storage/async-storage";
import type { Job } from "./types";

const STORAGE = "addy:demo-creations:v1";
export const DEMO_DURATION_MS = 20000;
let writes: Promise<unknown> = Promise.resolve();

export async function listDemoJobs(): Promise<Job[]> {
  await writes.catch(() => {});
  const saved = JSON.parse(await AsyncStorage.getItem(STORAGE) ?? "[]") as Job[];
  return saved.map(job => ({ ...job, state: Date.now() - Date.parse(job.createdAt) >= DEMO_DURATION_MS ? "delivered" : "generating" }));
}

export async function createDemoJob(input: Pick<Job, "title" | "platforms" | "exports" | "sourceImage" | "outputKind">): Promise<Job> {
  const job: Job = { ...input, id: `demo_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`, version: 1, state: "generating", createdAt: new Date().toISOString() };
  const write = writes.catch(() => {}).then(async () => {
    const saved = JSON.parse(await AsyncStorage.getItem(STORAGE) ?? "[]") as Job[];
    await AsyncStorage.setItem(STORAGE, JSON.stringify([job, ...saved]));
  });
  writes = write;
  await write;
  return job;
}
