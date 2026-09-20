import { useEffect, useRef, useState } from "react";
import axios from "axios";

const BASE_URL = "";

/**
 * Ask for the password before something irreversible happens.
 *
 * `window.confirm` asks whether you meant it. This asks whether it is still
 * you: a signed-in laptop left open is the ordinary case in a shared
 * office, and the difference matters only where there is no undo.
 *
 * Returns a short-lived token, not a password. The caller sends that with
 * the delete, so a password never travels with the destructive request and
 * one confirmation can cover a bulk operation.
 *
 * @param title    what is about to happen, in the imperative
 * @param body     what it takes with it - specific, not "this cannot be undone"
 * @param confirmLabel  names the action, never "OK"
 * @param alternative   optional `{ label, onChoose }` for the reversible
 *                      move, which should stay one click away
 */
export default function ConfirmDestructive({
  title, body, confirmLabel = "Delete", alternative = null,
  onConfirm, onCancel,
}) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const submit = async (event) => {
    event.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError("");
    try {
      const { data } = await axios.post(
        `${BASE_URL}/api/auth/confirm-password/`,
        { password },
        { headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` } }
      );
      // Cleared before handing over: there is no reason for it to outlive
      // the exchange, and the token is what the caller needs.
      setPassword("");
      await onConfirm(data.token);
    } catch (err) {
      setError(err.response?.data?.error || "Could not confirm your password.");
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true"
         aria-labelledby="confirm-destructive-title">
      <div className="modal" style={{ maxWidth: "440px" }}>
        <form onSubmit={submit}>
          <div className="modal-head">
            <h3 className="modal-title" id="confirm-destructive-title">{title}</h3>
          </div>

          <div className="modal-body col" style={{ gap: "1rem" }}>
            <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
              {body}
            </p>

            <div className="field">
              <label className="label" htmlFor="confirm-destructive-password">
                Confirm with your password
              </label>
              <input
                id="confirm-destructive-password"
                ref={inputRef}
                className="input"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => { setPassword(e.target.value); setError(""); }}
              />
              <p className="subtle text-xs" style={{ margin: 0 }}>
                Asked because this cannot be undone from the portal.
              </p>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}
          </div>

          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onCancel}>
              Cancel
            </button>
            {alternative && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={alternative.onChoose}
              >
                {alternative.label}
              </button>
            )}
            <button
              type="submit"
              className="btn btn-danger"
              disabled={!password || busy}
            >
              {busy ? "Working…" : confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** The header a guarded endpoint expects. Kept here so the name is written
 *  once - a typo in it reads as "your password is wrong". */
export const reauthHeader = (token) => ({ "X-Reauth-Token": token });
