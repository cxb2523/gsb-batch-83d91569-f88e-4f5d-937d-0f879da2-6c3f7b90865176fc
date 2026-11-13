import type { RaConnectResponse, RaProfile, RaStatusResponse, WantToPlayResponse } from "./types";

export async function connectRaAccount(apiKey: string, username: string): Promise<RaConnectResponse> {
  const form = new FormData();
  form.append("api_key", apiKey);
  form.append("username", username);
  const res = await fetch("/api/ra/connect", { method: "POST", body: form });
  return res.json() as Promise<RaConnectResponse>;
}

export async function disconnectRaAccount(): Promise<{ success: boolean }> {
  const res = await fetch("/api/ra/disconnect", { method: "POST" });
  return res.json() as Promise<{ success: boolean }>;
}

export async function getRaStatus(): Promise<RaStatusResponse> {
  const res = await fetch("/api/ra/status");
  return res.json() as Promise<RaStatusResponse>;
}

export async function getRaProfile(): Promise<RaProfile> {
  const res = await fetch("/api/ra/profile");
  return res.json() as Promise<RaProfile>;
}

export async function fetchWantToPlay(): Promise<WantToPlayResponse> {
  const res = await fetch("/api/want_to_play");
  return res.json() as Promise<WantToPlayResponse>;
}
