import { afterEach, describe, expect, it, vi } from "vitest";
import { connectRaAccount, disconnectRaAccount, fetchWantToPlay, getRaProfile, getRaStatus } from "./wantToPlay";
import type { RaConnectResponse, RaProfile, RaStatusResponse, WantToPlayResponse } from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("connectRaAccount", () => {
  it("posts api_key and username as form fields and returns the parsed JSON", async () => {
    const mockResponse: RaConnectResponse = { success: true };
    const fetchMock = vi.fn().mockResolvedValue({ json: () => Promise.resolve(mockResponse) });
    vi.stubGlobal("fetch", fetchMock);

    const result = await connectRaAccount("my-key", "my-user");

    expect(result).toEqual(mockResponse);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/ra/connect");
    expect(options.method).toBe("POST");

    const form = options.body as FormData;
    expect(form.get("api_key")).toBe("my-key");
    expect(form.get("username")).toBe("my-user");
  });

  it("propagates the error response as-is", async () => {
    const mockResponse: RaConnectResponse = { success: false, message: "boom" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: () => Promise.resolve(mockResponse) }));

    const result = await connectRaAccount("bad-key", "someone");

    expect(result).toEqual(mockResponse);
  });
});

describe("disconnectRaAccount", () => {
  it("posts to /api/ra/disconnect with no body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ json: () => Promise.resolve({ success: true }) });
    vi.stubGlobal("fetch", fetchMock);

    const result = await disconnectRaAccount();

    expect(result).toEqual({ success: true });
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/ra/disconnect");
    expect(options.method).toBe("POST");
  });
});

describe("getRaStatus", () => {
  it("gets /api/ra/status and returns the parsed JSON", async () => {
    const mockResponse: RaStatusResponse = { connected: true, username: "pipetboy" };
    const fetchMock = vi.fn().mockResolvedValue({ json: () => Promise.resolve(mockResponse) });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getRaStatus();

    expect(result).toEqual(mockResponse);
    expect(fetchMock).toHaveBeenCalledWith("/api/ra/status");
  });
});

describe("getRaProfile", () => {
  it("gets /api/ra/profile and returns the parsed JSON", async () => {
    const mockResponse: RaProfile = {
      success: true,
      avatar_url: "https://media.retroachievements.org/UserPic/pipetboy.png",
      total_points: 12345,
      total_true_points: 45678,
      motto: "Jugando RA",
    };
    const fetchMock = vi.fn().mockResolvedValue({ json: () => Promise.resolve(mockResponse) });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getRaProfile();

    expect(result).toEqual(mockResponse);
    expect(fetchMock).toHaveBeenCalledWith("/api/ra/profile");
  });
});

describe("fetchWantToPlay", () => {
  it("gets /api/want_to_play with no arguments (credenciales vía cookie de sesión)", async () => {
    const mockResponse: WantToPlayResponse = { success: true, items: [], total: 0, requested: 0 };
    const fetchMock = vi.fn().mockResolvedValue({ json: () => Promise.resolve(mockResponse) });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchWantToPlay();

    expect(result).toEqual(mockResponse);
    expect(fetchMock).toHaveBeenCalledWith("/api/want_to_play");
  });
});
