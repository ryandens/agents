import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useConfirmation } from "../useConfirmation";
import SetEditor from "../SetEditor";
import { newSet } from "../types";

// jsdom does not implement the native dialog methods.
function showModal(this: HTMLDialogElement) {
  this.setAttribute("open", "");
}
function close(this: HTMLDialogElement) {
  this.removeAttribute("open");
}
beforeEach(() => {
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: {configurable:true, value:showModal},
    close: {configurable:true, value:close},
  });
});
afterEach(() => {
  Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
  Reflect.deleteProperty(HTMLDialogElement.prototype, "close");
});

function Harness({ decided }: { decided: (answer: boolean) => void }) {
  const { requestConfirmation, confirmationDialog } = useConfirmation();
  return <>
    <button onClick={async () => decided(await requestConfirmation("Delete this workout?"))}>Delete workout</button>
    {confirmationDialog}
  </>;
}

it("requires an explicit decision and supports cancel, Escape, and continue", async () => {
  const decided = vi.fn();
  render(<Harness decided={decided}/>);
  fireEvent.click(screen.getByText("Delete workout"));
  expect(screen.getByRole("dialog", {name:"Delete this workout?"})).toBeInTheDocument();
  expect(decided).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Cancel"));
  await waitFor(() => expect(decided).toHaveBeenLastCalledWith(false));
  decided.mockClear();
  fireEvent.click(screen.getByText("Delete workout"));
  fireEvent(screen.getByRole("dialog"), new Event("cancel", {cancelable:true}));
  await waitFor(() => expect(decided).toHaveBeenLastCalledWith(false));
  decided.mockClear();
  fireEvent.click(screen.getByText("Delete workout"));
  fireEvent.click(screen.getByText("Continue"));
  await waitFor(() => expect(decided).toHaveBeenCalledExactlyOnceWith(true));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("cancels a pending destructive action when its component unmounts", async () => {
  const decided = vi.fn();
  const view = render(<Harness decided={decided}/>);
  fireEvent.click(screen.getByText("Delete workout"));
  view.unmount();
  await waitFor(() => expect(decided).toHaveBeenCalledExactlyOnceWith(false));
});

it("preserves recorded weight until the bodyweight change is confirmed", async () => {
  const changed = vi.fn();
  render(<SetEditor set={{...newSet(),weight:25}} exercise="Press" number={1} onChange={changed} onRemove={vi.fn()}/>);
  fireEvent.change(screen.getByLabelText("Weight represents"), {target:{value:"bodyweight"}});
  expect(changed).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Cancel"));
  expect(changed).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Weight represents"), {target:{value:"bodyweight"}});
  fireEvent.click(screen.getByText("Continue"));
  await waitFor(() => expect(changed).toHaveBeenCalledExactlyOnceWith({load_basis:"bodyweight",weight:null}));
});
