/** TanStack Query hooks â€” the app's only data layer. */
import { useQuery, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { isJobPending } from "@/lib/jobStatus";
import { api } from "./client";
import type { PlatformKey, PresetId } from "./types";

export const keys = {
  account: ["account"] as const,
  wallet: ["wallet"] as const,
  jobs: ["jobs"] as const,
  job: (id: string) => ["job", id] as const,
};

export const useAccount = () =>
  useQuery({ queryKey: keys.account, queryFn: api.getAccount });

export const useWallet = () =>
  useQuery({ queryKey: keys.wallet, queryFn: api.getWallet });

export const useJobs = () =>
  useQuery({ queryKey: keys.jobs, queryFn: () => api.listJobs(), refetchInterval: query => query.state.data?.some(isJobPending) ? 2000 : false });

export const useLibraryJobs = () =>
  useInfiniteQuery({ queryKey: [...keys.jobs, "pages"], initialPageParam: "",
    queryFn: ({ pageParam }) => api.listJobPage(pageParam || undefined),
    getNextPageParam: page => page.nextCursor ?? undefined,
    refetchInterval: query => query.state.data?.pages.some(page => page.items.some(isJobPending)) ? 2000 : false });

export const useJob = (id: string) =>
  useQuery({
    queryKey: keys.job(id),
    queryFn: () => api.getJob(id),
    enabled: !!id,
  });

export function useCreateJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      imageUri: string;
      platforms: PlatformKey[];
      fastMode: boolean;
    }) => api.createJob(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.jobs });
      qc.invalidateQueries({ queryKey: keys.wallet });
    },
  });
}

export function useChooseStyle(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ choice, expectedVersion }: { choice: PresetId | { direction: string }; expectedVersion: number }) =>
      api.chooseStyle(id, choice, expectedVersion),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(id) }),
  });
}

export function useDecision(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ action, expectedVersion, key }: { action: "accept" | "spend_more" | "abort"; expectedVersion: number; key?: string }) =>
      api.decide(id, action, expectedVersion, key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.job(id) });
      qc.invalidateQueries({ queryKey: keys.wallet });
    },
  });
}

export function useRegen(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (expectedVersion: number) => api.regen(id, expectedVersion),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.job(id) });
      qc.invalidateQueries({ queryKey: keys.wallet });
    },
  });
}
