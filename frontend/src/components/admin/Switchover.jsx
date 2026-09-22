import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "./ConfirmDestructive";

const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/**
 * Switching access from departments to positions.
 *
 * The screen's job is to make the change inspectable before it happens.
 * Blockers say what would break; the preview says what each person would
 * see afterwards — which is the part the blockers cannot cover, because
 * somebody holding the *wrong* position is not stranded, just misplaced.
 *
 * There is no way to force it past a blocker, and that is deliberate:
 * every blocker is a person losing access to the documents that govern
 * their work.
 */
export default function Switchover() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(null);   // true = on, false = off

  const load = useCallback(async () => {
    try {
      const res = await axios.get(`${BASE_URL}/api/org/switchover/`, getAuth());
      setData(res.data);
      setError("");
    } catch (err) {
      setError(err.response?.data?.error || "Could not read the switchover state.");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const flip = async (token) => {
    const wanted = pending;
    setPending(null);
    try {
      await axios.post(
        `${BASE_URL}/api/org/switchover/set/`,
        { by_position: wanted },
        { headers: { ...getAuth().headers, ...reauthHeader(token) } }
      );
      setMessage(wanted
        ? "Access is now scoped by position."
        : "Access is back to departments.");
      setTimeout(() => setMessage(""), 6000);
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not switch.");
    }
  };

  if (!data) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  const { by_position: on, ready, blockers, warnings, preview, inactive, unapproved } = data;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Switchover</h1>
          <p className="page-subtitle">
            Access is scoped by{" "}
            <strong>{on ? "position" : "department"}</strong>
            {on && data.switched_at
              ? ` — switched by ${data.switched_by}`
              : ""}
            .
          </p>
        </div>
        {on ? (
          <button className="btn btn-ghost btn-sm" onClick={() => setPending(false)}>
            Switch back to departments
          </button>
        ) : (
          <button
            className="btn btn-primary btn-sm"
            disabled={!ready}
            onClick={() => setPending(true)}
          >
            Switch to positions
          </button>
        )}
      </header>

      {error && <div className="alert alert-danger">{error}</div>}
      {message && <div className="toast">{message}</div>}

      {!on && (
        <>
          {blockers.length === 0 ? (
            <div className="alert alert-success">
              Nothing is blocking the switch. Check the preview below before
              making it — the blockers catch people who would see nothing,
              not people who would see the wrong thing.
            </div>
          ) : (
            <section style={{ marginBottom: "1.5rem" }}>
              <h2 className="section-title">Blocking the switch</h2>
              <div className="col" style={{ gap: "0.75rem" }}>
                {blockers.map((b) => (
                  <div key={b.code} className="alert alert-danger">
                    <div>{b.message}</div>
                    {b.detail.length > 0 && (
                      <div className="subtle text-xs" style={{ marginTop: "0.4rem" }}>
                        {b.detail
                          .map((d) => d.username || d.title || d.document || d.name)
                          .join(", ")}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <p className="subtle text-xs" style={{ marginTop: "0.6rem" }}>
                There is no way to switch past these. Each one is somebody
                losing access to documents they work with.
              </p>
            </section>
          )}

          {warnings.length > 0 && (
            <section style={{ marginBottom: "1.5rem" }}>
              <h2 className="section-title">Worth knowing first</h2>
              <div className="col" style={{ gap: "0.5rem" }}>
                {warnings.map((w) => (
                  <div key={w.code} className="alert alert-warning">
                    <div>{w.message}</div>
                    {w.detail.length > 0 && (
                      <div className="subtle text-xs" style={{ marginTop: "0.4rem" }}>
                        {w.detail
                          .map((d) => d.title || d.name || d.username)
                          .join(", ")}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      <section>
        <h2 className="section-title">
          {on ? "What each account sees" : "What each account would see"}
        </h2>
        <PreviewTable rows={preview} on={on} />
      </section>

      {unapproved.length > 0 && (
        <section style={{ marginTop: "1.5rem" }}>
          <h2 className="section-title">Awaiting approval</h2>
          <p className="subtle text-sm" style={{ margin: 0 }}>
            {unapproved.map((r) => r.username).join(", ")} — cannot sign in,
            so the switch does not affect them.
          </p>
        </section>
      )}

      {inactive.length > 0 && (
        <section style={{ marginTop: "1.5rem" }}>
          <h2 className="section-title">Deactivated</h2>
          <p className="subtle text-sm" style={{ margin: 0 }}>
            {inactive.map((r) => r.username).join(", ")} — kept on the record,
            no longer signing in.
          </p>
        </section>
      )}

      {pending !== null && (
        <ConfirmDestructive
          title={pending
            ? "Switch access to positions?"
            : "Switch access back to departments?"}
          body={pending
            ? "From now on people see the documents of offices where they "
              + "currently hold a position, and may propose changes only "
              + "where their office concurs. Announcements follow the same "
              + "rule. This can be switched back."
            : "Everyone returns to seeing their department's manuals, and "
              + "proposing anywhere in that department. Announcements go "
              + "back to department targeting."}
          confirmLabel={pending ? "Switch to positions" : "Switch back"}
          onConfirm={flip}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}

function PreviewTable({ rows, on }) {
  if (rows.length === 0) {
    return <p className="subtle text-sm" style={{ margin: 0 }}>No active accounts.</p>;
  }

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Account</th>
            <th>Department</th>
            <th>Offices held</th>
            <th style={{ textAlign: "right" }}>By department</th>
            <th style={{ textAlign: "right" }}>By position</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const changes = r.manuals_now !== r.manuals_after;
            return (
              <tr key={r.id}>
                <td className="table-strong">
                  {r.full_name || r.username}
                  {r.system_role === "system_admin" && (
                    <span className="badge badge-neutral" style={{ marginLeft: "0.4rem" }}>
                      admin
                    </span>
                  )}
                </td>
                <td className="subtle">{r.department || "—"}</td>
                <td>
                  {r.offices.length === 0
                    ? <span className="subtle">none</span>
                    : r.offices.join(", ")}
                </td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}
                    className={on ? "subtle" : ""}>
                  {r.scoped === false ? <span className="subtle">all</span> : r.manuals_now}
                </td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {r.scoped === false ? (
                    <span className="subtle" title="Admin access is not scoped by office">
                      all
                    </span>
                  ) : (
                  <>
                  <span className={r.loses_everything ? "strong" : ""}
                        style={r.loses_everything ? { color: "var(--danger)" } : undefined}>
                    {r.manuals_after}
                  </span>
                  {r.loses_everything && (
                    <span className="badge badge-danger" style={{ marginLeft: "0.4rem" }}>
                      sees nothing
                    </span>
                  )}
                  {!r.loses_everything && changes && (
                    <span className="subtle text-xs" style={{ marginLeft: "0.4rem" }}>
                      {r.manuals_after > r.manuals_now ? "more" : "fewer"}
                    </span>
                  )}
                  </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
