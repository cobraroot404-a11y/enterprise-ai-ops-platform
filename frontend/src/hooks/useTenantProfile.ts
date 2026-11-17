import { api } from "../services/api";
import type { TenantProfileInfo } from "../types";
import { useAsync } from "./useAsync";

/** The tenant's domain profile (document kinds, asset wording). Null data means "use platform defaults". */
export function useTenantProfile() {
  return useAsync(() => api<TenantProfileInfo>("/tenant-profile"), []);
}

export function assetLabel(info: TenantProfileInfo | null): string {
  return info?.profile?.asset_label ?? "equipment";
}

export function profileKinds(info: TenantProfileInfo | null): string[] {
  const p = info?.profile;
  if (!p) return [];
  return [...p.guidance_kinds, p.register_kind, ...(p.history_kind ? [p.history_kind] : []), ...p.document_kinds];
}
