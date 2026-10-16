import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import BodyWeightLog from "../BodyWeightLog";
import { changeLog, emptyLog, type LocalLog } from "../database";
import { syncLog } from "../offline";

vi.mock("../database", async importOriginal => {
  const actual = await importOriginal<typeof import("../database")>();
  return {...actual,changeLog:vi.fn()};
});
let log: LocalLog;
beforeEach(() => {
  log = emptyLog();
  vi.mocked(changeLog).mockImplementation(async (_owner,update) => {
    update?.(log);
    if (update) log.generation++;
    return structuredClone(log);
  });
});
afterEach(() => vi.unstubAllGlobals());
const response = (data:unknown) => ({ok:true,json:async () => data});

it("defaults to pounds and saves an independent measurement to the server",async () => {
  const fetch = vi.fn(async (url:string,init?:RequestInit) => {
    if (url === "/api/auth/me") return response({sub:"owner"});
    if (url.endsWith("/sync")) return response({acknowledged:JSON.parse(init!.body as string).id});
    return response(url.endsWith("/body-weight") ? log.bodyWeights : []);
  });
  vi.stubGlobal("fetch",fetch);
  const onChange = vi.fn();
  render(<BodyWeightLog owner="owner" log={log} onChange={onChange}/>);
  expect(screen.queryByLabelText("Weight unit")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Body weight (lbs)",{selector:"input"}),{target:{value:"182.4"}});
  fireEvent.click(screen.getByText("Log weight"));
  expect(await screen.findByText("Weight saved.")).toBeInTheDocument();
  expect(log.queue).toHaveLength(0);
  expect(log.bodyWeights[0]).toMatchObject({weight:182.4,unit:"lbs"});
  expect(log.workouts).toEqual([]);
  expect(onChange).toHaveBeenCalled();
});

it("retains a failed save and retries the identical measurement after recovery",async () => {
  vi.stubGlobal("fetch",vi.fn().mockRejectedValue(new TypeError("offline")));
  render(<BodyWeightLog owner="owner" log={log} onChange={vi.fn()}/>);
  fireEvent.change(screen.getByLabelText("Body weight (lbs)",{selector:"input"}),{target:{value:"180"}});
  fireEvent.click(screen.getByText("Log weight"));
  expect(await screen.findByText(/Weight saved on this device; server save pending/)).toBeInTheDocument();
  const pending = structuredClone(log.queue[0]);
  const fetch = vi.fn(async (url:string,init?:RequestInit) => {
    if (url === "/api/auth/me") return response({sub:"owner"});
    if (url.endsWith("/sync")) {
      expect(JSON.parse(init!.body as string)).toEqual(pending);
      return response({acknowledged:pending.id});
    }
    return response(url.endsWith("/body-weight") ? log.bodyWeights : []);
  });
  vi.stubGlobal("fetch",fetch);
  await syncLog("owner");
  await waitFor(() => expect(log.queue).toHaveLength(0));
  expect(log.bodyWeights).toHaveLength(1);
});
