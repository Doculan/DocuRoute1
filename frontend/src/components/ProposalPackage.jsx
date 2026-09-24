import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { reauthHeader } from "./admin/ConfirmDestructive";

const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const GENERATED_LABEL = {
  dcr_generated: "Document Change Request",
  pages_generated: "Draft copy",
  concurrence_record: "Annex",
};

const ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

function size(bytes) {
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function when(value) {
  return new Date(value).toLocaleDateString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
  });
}

/**
 * The documents to print and sign, and the signed copies coming back.
 *
 * Files come through the authenticated download view as a blob, never as
 * a media URL: a signed DCR is not for anyone who guesses its address.
 *
 * Whether this person may upload is the server's answer, so the system
 * admin and QMS staff see the same package with nothing to press.
 */
export default function ProposalPackage({ proposalId, onChanged }) {
  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(null);          // the kind being uploaded
  const [replacing, setReplacing] = useState(null); // the scan being replaced

  const load = useCallback(async () => {
    try {
      const { data } = await axios.get(
        `${BASE_URL}/api/proposals/${proposalId}/package/`, getAuth()
      );
      setPkg(data);
    } catch (err) {
      setError(err.response?.data?.error || "Could not load the documents.");
    }
  }, [proposalId]);

  useEffect(() => { load(); }, [load]);

  const download = async (file) => {
    try {
      const response = await axios.get(
        `${BASE_URL}/api/proposals/${proposalId}/attachments/${file.id}/download/`,
        { ...getAuth(), responseType: "blob" }
      );
      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename || "document";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setError("Could not download that file.");
    }
  };

  const upload = async (kind, file) => {
    if (!file) return;
    if (file.size > pkg.max_bytes) {
      setError(`That file is ${size(file.size)}. The limit is ${size(pkg.max_bytes)}.`);
      return;
    }
    setBusy(kind);
    setError("");
    const form = new FormData();
    form.append("kind", kind);
    form.append("file", file);
    try {
      const { data } = await axios.post(
        `${BASE_URL}/api/proposals/${proposalId}/scans/`, form, getAuth()
      );
      setPkg(data);
      onChanged?.(data.status);
    } catch (err) {
      setError(err.response?.data?.error || "Could not upload that file.");
    } finally {
      setBusy(null);
    }
  };

  if (!pkg) {
    return error ? <div className="alert alert-danger">{error}</div> : null;
  }

  return (
    <section style={{ marginTop: "1.5rem" }}>
      <Status pkg={pkg} />

      {error && <div className="alert alert-danger">{error}</div>}

      <h2 className="section-title">
        {pkg.status === "awaiting_signature" ? "Documents to sign" : "Documents"}
      </h2>
      <div>
        {pkg.generated.map((file) => (
          <div key={file.id} className="package-row">
            <span className="package-name text-sm">
              {GENERATED_LABEL[file.kind]}
              <span className="package-meta">{file.filename}</span>
            </span>
            <span className="package-actions">
              <button className="btn btn-ghost btn-sm" onClick={() => download(file)}>
                Download
              </button>
            </span>
          </div>
        ))}
      </div>

      <h2 className="section-title" style={{ marginTop: "1.5rem" }}>Signed copies</h2>
      <p className="package-note">
        Stored as uploaded. DocuRoute does not check signatures or contents —
        the QMS office checks them against the paper originals.
      </p>
      <div>
        {Object.entries(pkg.scans).map(([kind, scan]) => (
          <ScanRow
            key={kind}
            kind={kind}
            scan={scan}
            canUpload={scan.can_upload ?? pkg.can_upload}
            canReplace={scan.can_replace ?? pkg.can_replace}
            busy={busy === kind}
            onUpload={(file) => upload(kind, file)}
            onReplace={() => setReplacing(scan.current)}
            onDownload={download}
          />
        ))}
      </div>

      {replacing && (
        <ReplaceForm
          proposalId={proposalId}
          scan={replacing}
          maxBytes={pkg.max_bytes}
          onCancel={() => setReplacing(null)}
          onDone={(data) => {
            setReplacing(null);
            setPkg(data);
            onChanged?.(data.status);
          }}
        />
      )}
    </section>
  );
}

function Status({ pkg }) {
  if (pkg.status === "ready_for_imr") {
    return (
      <div className="alert alert-success">
        The signed copies are in. The IMR decides next.
      </div>
    );
  }
  if (pkg.status === "awaiting_approval") {
    const office = pkg.scans.approved_dcr?.can_upload;
    return (
      <div className="alert alert-success">
        {office
          ? "Accepted by the IMR. Once the approving authority has signed the DCR, upload it."
          : "Accepted by the IMR. Waiting for the approving authority's signature."}
      </div>
    );
  }
  if (pkg.status === "with_custodian") {
    return <div className="alert alert-success">With the Document Custodian.</div>;
  }
  if (pkg.status === "package_returned") {
    return (
      <div className="alert alert-warning">
        {pkg.can_replace
          ? "Returned by the Document Custodian. Replace the copies marked below."
          : "Returned to the requesting office for defects in the signed copies."}
      </div>
    );
  }
  if (pkg.status === "awaiting_signature") {
    return (
      <div className="alert alert-success">
        {pkg.can_upload
          ? "Agreed and frozen. Print the documents, sign them, and upload the signed copies."
          : "Agreed and frozen. Waiting for the signed copies."}
      </div>
    );
  }
  return null;
}

function ScanRow({ kind, scan, canUpload, canReplace, busy, onUpload, onReplace, onDownload }) {
  const input = useRef(null);
  const current = scan.current;
  // Newest first: each earlier file was replaced for the reason its
  // successor carries.
  const chain = current ? [current, ...scan.earlier] : scan.earlier;

  return (
    <div className="package-row">
      <span className="package-name text-sm">
        {scan.label}
        {scan.returned && <span className="status-mark is-returned" style={{ marginLeft: "0.5rem" }}>Returned</span>}
        <span className="package-meta">
          {current
            ? `${current.filename} · ${size(current.size)} · ${current.by} · ${when(current.at)}`
            : "Not uploaded yet"}
        </span>
        {scan.earlier.length > 0 && (
          <details className="package-earlier">
            <summary>
              Replaced {scan.earlier.length} time{scan.earlier.length === 1 ? "" : "s"}
            </summary>
            <ul>
              {scan.earlier.map((file, i) => (
                <li key={file.id}>
                  <button className="link-btn text-xs" onClick={() => onDownload(file)}>
                    {file.filename}
                  </button>
                  {` · ${file.by} · ${when(file.at)}`}
                  {chain[i]?.replacement_reason && (
                    <div>Replaced: {chain[i].replacement_reason}</div>
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
      </span>
      <span className="package-actions">
        {current && (
          <button className="btn btn-ghost btn-sm" onClick={() => onDownload(current)}>
            Download
          </button>
        )}
        {current && canReplace && (
          <button className="btn btn-ghost btn-sm" onClick={onReplace}>Replace</button>
        )}
        {!current && canUpload && (
          <>
            <input
              ref={input}
              id={`scan-${kind}`}
              type="file"
              accept={ACCEPT}
              style={{ display: "none" }}
              onChange={(e) => { onUpload(e.target.files[0]); e.target.value = ""; }}
            />
            <button
              className="btn btn-primary btn-sm"
              disabled={busy}
              onClick={() => input.current?.click()}
            >
              {busy ? "Uploading…" : "Upload"}
            </button>
          </>
        )}
      </span>
    </div>
  );
}

function ReplaceForm({ proposalId, scan, maxBytes, onCancel, onDone }) {
  const [file, setFile] = useState(null);
  const [reason, setReason] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const ready = file && reason.trim() && password && !busy;

  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    if (file.size > maxBytes) {
      setError(`That file is ${size(file.size)}. The limit is ${size(maxBytes)}.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const { data: confirmation } = await axios.post(
        `${BASE_URL}/api/auth/confirm-password/`, { password }, getAuth()
      );
      setPassword("");
      const form = new FormData();
      form.append("file", file);
      form.append("reason", reason);
      const { data } = await axios.post(
        `${BASE_URL}/api/proposals/${proposalId}/scans/${scan.id}/replace/`, form,
        { headers: { ...getAuth().headers, ...reauthHeader(confirmation.token) } }
      );
      onDone(data);
    } catch (err) {
      setError(err.response?.data?.error || "Could not replace that file.");
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal" style={{ maxWidth: "460px" }}>
        <form onSubmit={submit}>
          <div className="modal-head">
            <h3 className="modal-title">Replace this signed copy?</h3>
          </div>
          <div className="modal-body col" style={{ gap: "1rem" }}>
            <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
              {scan.label}: {scan.filename} stays on record as the earlier copy.
            </p>
            <div className="field">
              <label className="label" htmlFor="replace-file">New file</label>
              <input id="replace-file" className="input" type="file" accept={ACCEPT}
                     onChange={(e) => { setFile(e.target.files[0] || null); setError(""); }} />
            </div>
            <div className="field">
              <label className="label" htmlFor="replace-reason">Why</label>
              <input id="replace-reason" className="input" value={reason}
                     placeholder="e.g. the first scan was unreadable"
                     onChange={(e) => setReason(e.target.value)} />
            </div>
            <div className="field">
              <label className="label" htmlFor="replace-password">
                Confirm with your password
              </label>
              <input id="replace-password" className="input" type="password"
                     autoComplete="current-password" value={password}
                     onChange={(e) => { setPassword(e.target.value); setError(""); }} />
            </div>
            {error && <div className="alert alert-danger">{error}</div>}
          </div>
          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={!ready}>
              {busy ? "Working…" : "Replace"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
