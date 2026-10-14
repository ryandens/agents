import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import WorkoutForm from "../WorkoutForm";
import FitnessPage from "../page";
import { changeLog, emptyLog, type LocalLog } from "../database";

vi.mock("../../components/AuthProvider", () => ({useAuth: () => ({user:{sub:"test-user"}})}));
vi.mock("../database", async importOriginal => {
  const actual = await importOriginal<typeof import("../database")>();
  return {...actual, changeLog:vi.fn()};
});
let log: LocalLog;
beforeEach(() => {
  log = emptyLog();
  vi.mocked(changeLog).mockImplementation(async (_owner, update) => {
    const next = structuredClone(log);
    update?.(next);
    if (update) next.generation++;
    log = next;
    return structuredClone(log);
  });
});
afterEach(() => vi.unstubAllGlobals());

it("saves locally when completely offline and does not wait for an API", async () => {
  const fetch = vi.fn().mockRejectedValue(new TypeError("offline"));
  vi.stubGlobal("fetch", fetch);
  const saved = vi.fn();
  render(<WorkoutForm owner="test-user" exercises={[{id:"press", name:"Press"}]} onSaved={saved} onCancel={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", {name:"Press"}));
  fireEvent.change(screen.getByLabelText("Press set 1 reps"), {target:{value:"7"}});
  fireEvent.click(screen.getByRole("button",{name:"+ Reached failure"}));
  fireEvent.click(screen.getByText("Preview summary"));
  fireEvent.click(screen.getByText("Save workout"));
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(log.workouts[0].exercises[0].sets[0]).toMatchObject({reps:7,weight:null,failure:true});
  expect(log.queue).toHaveLength(1);
  expect(log.draft).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});

it("retains the draft and shows local storage failure", async () => {
  vi.mocked(changeLog).mockRejectedValue(new Error("Storage unavailable"));
  render(<WorkoutForm owner="test-user" exercises={[{id:"press",name:"Press"}]} onSaved={vi.fn()} onCancel={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", {name:"Press"}));
  fireEvent.change(screen.getByLabelText("Press set 1 reps"), {target:{value:"5"}});
  fireEvent.click(screen.getByText("Preview summary"));
  fireEvent.click(screen.getByText("Save workout"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
  fireEvent.click(screen.getByText("Back to sets"));
  expect(screen.getByLabelText("Press set 1 reps")).toHaveValue(5);
});

it("autosaves and restores an unfinished draft", async () => {
  const props = {owner:"test-user",exercises:[{id:"press",name:"Press"}],onSaved:vi.fn(),onCancel:vi.fn()};
  const form = render(<WorkoutForm {...props}/>);
  fireEvent.click(screen.getByRole("button", {name:"Press"}));
  fireEvent.change(screen.getByLabelText("Press set 1 reps"),{target:{value:"9"}});
  await waitFor(() => expect(log.draft?.exercises[0].sets[0].reps).toBe(9));
  form.unmount();
  render(<WorkoutForm {...props} initial={log.draft!}/>);
  expect(screen.getByLabelText("Press set 1 reps")).toHaveValue(9);
});

it("opens local history while the API is unreachable", async () => {
  vi.stubGlobal("fetch",vi.fn().mockRejectedValue(new TypeError("offline")));
  render(<FitnessPage/>);
  expect(await screen.findByText(/No workouts yet/)).toBeInTheDocument();
  expect(await screen.findByText(/API unreachable/)).toBeInTheDocument();
  expect(screen.getByText("+ Log workout")).toBeEnabled();
});

it("repeats recorded values explicitly but does not copy failure or set notes", async () => {
  render(<WorkoutForm owner="test-user" exercises={[{id:"press",name:"Press"}]} onSaved={vi.fn()} onCancel={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button",{name:"Press"}));
  fireEvent.change(screen.getByLabelText("Press set 1 reps"),{target:{value:"6"}});
  fireEvent.change(screen.getByLabelText("Press set 1 weight"),{target:{value:"35"}});
  fireEvent.click(screen.getByRole("button",{name:"+ Reached failure"}));
  fireEvent.click(screen.getByText("Repeat last set"));
  expect(screen.getByLabelText("Press set 2 reps")).toHaveValue(6);
  expect(screen.getByLabelText("Press set 2 weight")).toHaveValue(35);
  expect(screen.getAllByRole("button",{name:"+ Reached failure"})[0]).toHaveAttribute("aria-pressed","false");
  fireEvent.click(screen.getByText("+ Add set"));
  expect(screen.getByLabelText("Press set 3 reps")).toHaveValue(6);
  expect(screen.getByLabelText("Press set 3 weight")).toHaveValue(35);
  await waitFor(() => expect(log.draft?.exercises[0].sets).toHaveLength(3));
});

it("reviews timed sets and lets you return to editing without submitting", async () => {
  const saved = vi.fn();
  render(<WorkoutForm owner="test-user" exercises={[{id:"plank",name:"Plank"}]} onSaved={saved} onCancel={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button",{name:"Plank"}));
  fireEvent.click(screen.getByRole("button",{name:"Time"}));
  fireEvent.change(screen.getByLabelText("Plank set 1 seconds"),{target:{value:"40"}});
  fireEvent.click(screen.getByText("Preview summary"));
  expect(screen.getByRole("region",{name:"Workout review"})).toHaveTextContent("40s");
  expect(saved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Back to sets"));
  expect(screen.getByLabelText("Plank set 1 seconds")).toHaveValue(40);
  await waitFor(() => expect(log.draft?.exercises[0].sets[0].seconds).toBe(40));
});

it("creates and adds a searched exercise offline", async () => {
  const fetch = vi.fn().mockRejectedValue(new Error("Offline"));
  vi.stubGlobal("fetch",fetch);
  render(<WorkoutForm owner="test-user" exercises={[]} onSaved={vi.fn()} onCancel={vi.fn()}/>);
  fireEvent.change(screen.getByLabelText("Search exercises"),{target:{value:"Cable row"}});
  fireEvent.click(screen.getByRole("button",{name:"Create & add “Cable row”"}));
  expect(await screen.findByLabelText("Cable row set 1 reps")).toBeInTheDocument();
  expect(log.queue[0]).toMatchObject({kind:"exercise",exercise:{name:"Cable row"}});
  expect(fetch).not.toHaveBeenCalled();
});

it("keeps every exercise directly editable without switching panels",async () => {
  render(<WorkoutForm owner="test-user" exercises={[{id:"press",name:"Press"},{id:"row",name:"Row"}]} onSaved={vi.fn()} onCancel={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button",{name:"Press"}));
  fireEvent.change(screen.getByLabelText("Press set 1 reps"),{target:{value:"8"}});
  fireEvent.click(screen.getByText("+ Add another exercise"));
  fireEvent.click(screen.getByRole("button",{name:"Row"}));
  expect(screen.getByLabelText("Press set 1 reps")).toHaveValue(8);
  expect(screen.getByLabelText("Row set 1 reps")).toBeInTheDocument();
  expect(screen.getByLabelText("Press set 1 reps")).toHaveValue(8);
  await waitFor(() => expect(log.draft?.exercises).toHaveLength(2));
});

it("updates the exercise picker when a slow sync finishes while the form is open",async () => {
  const props = {owner:"test-user",onSaved:vi.fn(),onCancel:vi.fn()};
  const form = render(<WorkoutForm {...props} exercises={[]}/>);
  form.rerender(<WorkoutForm {...props} exercises={[{id:"press",name:"Synced press"}]}/>);
  fireEvent.click(screen.getByRole("button",{name:"Synced press"}));
  expect(screen.getByLabelText("Synced press set 1 reps")).toBeInTheDocument();
  await waitFor(() => expect(log.draft?.exercises[0].exercise_id).toBe("press"));
});

it("removes a set directly and undo preserves edits made to the remaining set", async () => {
  render(<WorkoutForm owner="test-user" exercises={[{id:"press",name:"Press"}]} onSaved={vi.fn()} onCancel={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button",{name:"Press"}));
  fireEvent.change(screen.getByLabelText("Press set 1 reps"),{target:{value:"8"}});
  fireEvent.click(screen.getByText("Repeat last set"));
  fireEvent.click(screen.getByRole("button",{name:"Remove Press set 1"}));
  expect(screen.queryByLabelText("Press set 2 reps")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Press set 1 reps"),{target:{value:"5"}});
  fireEvent.click(screen.getByRole("button",{name:"Undo"}));
  expect(screen.getByLabelText("Press set 1 reps")).toHaveValue(8);
  expect(screen.getByLabelText("Press set 2 reps")).toHaveValue(5);
  await waitFor(() => expect(log.draft?.exercises[0].sets.map(s => s.reps)).toEqual([8,5]));
});

it("removes an exercise with its sets, can undo, and saves the final deletion", async () => {
  const saved = vi.fn();
  render(<WorkoutForm owner="test-user" exercises={[{id:"press",name:"Press"},{id:"row",name:"Row"}]} onSaved={saved} onCancel={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button",{name:"Press"}));
  fireEvent.change(screen.getByLabelText("Press set 1 reps"),{target:{value:"7"}});
  fireEvent.click(screen.getByText("+ Add another exercise"));
  fireEvent.click(screen.getByRole("button",{name:"Row"}));
  fireEvent.click(screen.getByRole("button",{name:"Remove Press exercise"}));
  expect(screen.queryByLabelText("Press set 1 reps")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Undo"}));
  expect(screen.getByLabelText("Press set 1 reps")).toHaveValue(7);
  fireEvent.click(screen.getByRole("button",{name:"Remove Press exercise"}));
  fireEvent.click(screen.getByText("Save workout"));
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(log.workouts[0].exercises.map(e => e.exercise_id)).toEqual(["row"]);
});

it("lets you undo removing the final exercise without losing the draft", async () => {
  render(<WorkoutForm owner="test-user" exercises={[{id:"press",name:"Press"}]} onSaved={vi.fn()} onCancel={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button",{name:"Press"}));
  fireEvent.click(screen.getByRole("button",{name:"Remove Press exercise"}));
  expect(screen.getByText("Save workout")).toBeDisabled();
  fireEvent.click(screen.getByText("Undo"));
  expect(screen.getByLabelText("Press set 1 reps")).toBeInTheDocument();
  await waitFor(() => expect(log.draft?.exercises).toHaveLength(1));
});

it("browses equipment and body area and saves a workout using only taps, offline", async () => {
  const onSaved = vi.fn();
  render(<WorkoutForm owner="test-user" exercises={[]} onSaved={onSaved} onCancel={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", {name:"Machines"}));
  fireEvent.click(screen.getByRole("button", {name:"Chest"}));
  fireEvent.click(screen.getByRole("button", {name:/Machine chest press/}));
  await screen.findByRole("heading", {name:"Machine chest press"});
  fireEvent.click(screen.getByLabelText("Machine chest press set 1 reps"));
  fireEvent.click(screen.getByRole("button", {name:"8"}));
  fireEvent.click(screen.getByLabelText("Machine chest press set 1 weight"));
  fireEvent.click(screen.getByRole("button", {name:"80"}));
  fireEvent.click(screen.getByRole("button", {name:"Repeat last set"}));
  fireEvent.click(screen.getByRole("button", {name:"Save workout"}));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(log.queue.map(m => m.kind)).toEqual(["exercise","save"]);
  expect(log.workouts[0].exercises[0].sets).toHaveLength(2);
  expect(log.workouts[0].exercises[0].sets[1]).toMatchObject({reps:8,weight:80,load_basis:"machine"});
});

it("browses from body area, navigates back, and starts cardio with time", async () => {
  render(<WorkoutForm owner="test-user" exercises={[]} onSaved={vi.fn()} onCancel={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", {name:"Arms"}));
  fireEvent.click(screen.getByRole("button", {name:"Free weights"}));
  expect(screen.getByRole("button",{name:/Dumbbell curl/})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name:"All categories"}));
  fireEvent.click(screen.getByRole("button", {name:"Cardio"}));
  fireEvent.click(screen.getByRole("button", {name:/Indoor cycle/}));
  await screen.findByRole("heading",{name:"Indoor cycle"});
  fireEvent.click(screen.getByLabelText("Indoor cycle set 1 seconds"));
  fireEvent.click(screen.getByRole("button", {name:"10 min"}));
  expect(screen.getByLabelText("Indoor cycle set 1 seconds")).toHaveValue(600);
});

it("enters fractional loads and clears them without the device keyboard", async () => {
  render(<WorkoutForm owner="test-user" exercises={[{id:"press",name:"Press"}]} onSaved={vi.fn()} onCancel={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button",{name:"Press"}));
  const input = screen.getByLabelText("Press set 1 weight");
  expect(input).toHaveAttribute("readonly");
  fireEvent.click(input);
  for (const digit of ["2","2",".","5"]) fireEvent.click(screen.getByRole("button",{name:digit === "." ? "." : `Digit ${digit}`}));
  fireEvent.click(screen.getByRole("button",{name:"Done"}));
  expect(input).toHaveValue(22.5);
  fireEvent.click(input);
  fireEvent.click(screen.getByRole("button",{name:"Clear value"}));
  expect(input).toHaveValue(null);
});

it("prefills from local history and adds sets from the first, preserving individual edits", async () => {
  const {newSet} = await import("../types");
  const history = [{id:"old",performed_on:"2000-01-01",notes:"",source_note:"",exercises:[
    {exercise_id:"press",notes:"",sets:[{...newSet(),reps:8,weight:65,unit:"kg" as const,failure:true,notes:"old note"}]}]}];
  render(<WorkoutForm owner="test-user" exercises={[{id:"press",name:"Press"}]} workouts={history} onSaved={vi.fn()} onCancel={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button",{name:"Press"}));
  expect(screen.getByLabelText("Press set 1 reps")).toHaveValue(8);
  expect(screen.getByLabelText("Press set 1 weight")).toHaveValue(65);
  expect(screen.getByText(/Last workout/)).toHaveTextContent("2000-01-01");
  fireEvent.click(screen.getByText("+ Add set"));
  fireEvent.change(screen.getByLabelText("Press set 2 weight"),{target:{value:"60"}});
  fireEvent.click(screen.getByText("+ Add set"));
  expect(screen.getByLabelText("Press set 3 weight")).toHaveValue(65);
  fireEvent.change(screen.getByLabelText("Press set 1 weight"),{target:{value:"70"}});
  expect(screen.getByLabelText("Press set 2 weight")).toHaveValue(60);
  expect(screen.getByLabelText("Press set 3 weight")).toHaveValue(65);
  await waitFor(() => expect(log.draft?.exercises[0].sets[0]).toMatchObject({weight:70,unit:"kg",failure:null,notes:""}));
});
