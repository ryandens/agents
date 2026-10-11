import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import OfflineSetup from "./OfflineSetup";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("reports an incomplete install and retries automatically after reconnection", async () => {
  vi.useFakeTimers();
  vi.stubEnv("NODE_ENV","production");
  const serviceWorker = {
    register: vi.fn().mockResolvedValue({}),
    ready: new Promise(() => {}),
  };
  vi.stubGlobal("navigator",{serviceWorker,storage:{persist:vi.fn().mockResolvedValue(false)}});
  render(<OfflineSetup/>);
  await act(async () => {await vi.advanceTimersByTimeAsync(15000);});
  expect(screen.getByRole("status")).toHaveTextContent("setup will retry automatically");
  serviceWorker.ready = Promise.resolve({});
  await act(async () => {window.dispatchEvent(new Event("online"));});
  expect(serviceWorker.register).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("status")).toHaveTextContent("Ready to open offline");
});

it("does not mark a rejected registration as ready", async () => {
  vi.stubEnv("NODE_ENV","production");
  vi.stubGlobal("navigator",{serviceWorker:{
    register:vi.fn().mockRejectedValue(new Error("VPN unavailable")),
    ready:new Promise(() => {}),
  }});
  await act(async () => {render(<OfflineSetup/>);});
  expect(screen.getByRole("status")).toHaveTextContent("Offline launch isn't ready");
});
