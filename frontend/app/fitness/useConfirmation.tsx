"use client";

import { useEffect, useId, useRef, useState } from "react";

export function useConfirmation() {
  const [message, setMessage] = useState<string | null>(null);
  const pending = useRef<((answer: boolean) => void) | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const labelId = useId();

  useEffect(() => () => {
    pending.current?.(false);
    pending.current = null;
  }, []);

  useEffect(() => {
    if (message !== null) dialogRef.current?.showModal();
  }, [message]);

  function finish(answer: boolean) {
    const resolve = pending.current;
    pending.current = null;
    dialogRef.current?.close();
    setMessage(null);
    resolve?.(answer);
  }

  function requestConfirmation(text: string): Promise<boolean> {
    // Never replace a pending decision with a second destructive action.
    if (pending.current) return Promise.resolve(false);
    return new Promise(resolve => {
      pending.current = resolve;
      setMessage(text);
    });
  }

  const confirmationDialog = message !== null ? <dialog ref={dialogRef}
    className="fitness-confirmation" aria-labelledby={labelId}
    onCancel={event => { event.preventDefault(); finish(false); }}
    onClose={() => finish(false)}>
    <p id={labelId}>{message}</p>
    <div className="flex gap-3 mt-4 justify-end">
      <button type="button" autoFocus onClick={() => finish(false)}>Cancel</button>
      <button type="button" onClick={() => finish(true)}>Continue</button>
    </div>
  </dialog> : null;

  return { requestConfirmation, confirmationDialog };
}
