import { useState } from "react";
import axios from "axios";

// Standalone revision upload form.
//
// NOTE: this component is not currently mounted anywhere — the live staff
// submission path is StaffSections.jsx. It was pointing at /api/upload/<manualId>/,
// an endpoint that does not exist, with no auth header, so it could never have
// worked. Corrected here to the real endpoint so it is usable if mounted, rather
// than left as a broken example for someone to copy.

// Empty on purpose: every request goes out as a relative path, so the
// browser sends it to whatever host served the page and Vite's proxy
// (vite.config.js) forwards it to Django. That is what lets a second
// device on the LAN work - "127.0.0.1" would mean *that* device - and it
// keeps the browser on one origin, so CORS never enters into it.
const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

export default function UploadRevision({ sectionId, onSubmitted }) {
  const [file, setFile] = useState(null);
  const [changeReason, setChangeReason] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleUpload = async (e) => {
    e.preventDefault();
    setError("");
    if (!file) return setError("Select a file first.");
    if (!changeReason.trim()) return setError("Please give a reason for this change - a short sentence saying what changed and why.");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("change_reason", changeReason.trim());

    setLoading(true);
    try {
      const response = await axios.post(
        `${BASE_URL}/api/revisions/upload/${sectionId}/`,
        formData,
        { headers: { ...getAuth().headers, "Content-Type": "multipart/form-data" } }
      );
      setResult(response.data);
      setChangeReason("");
      onSubmitted?.(response.data);
    } catch (err) {
      // DRF returns `detail` for auth failures and `error` for view errors.
      setError(
        err.response?.data?.error ||
        err.response?.data?.detail ||
        "Upload failed."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="card card-pad" onSubmit={handleUpload}>
      <h3 className="section-title" style={{ marginBottom: "1rem" }}>Upload revision</h3>

      <div className="field">
        <label className="label">Revised file (PDF, DOCX or TXT)</label>
        <input
          className="input-file"
          type="file"
          accept=".pdf,.docx,.doc,.txt"
          onChange={(e) => setFile(e.target.files[0])}
          required
        />
      </div>

      <div className="field" style={{ marginTop: "0.75rem" }}>
        <label className="label">
          Reason for change <span style={{ color: "var(--danger)" }}>*</span>
        </label>
        <textarea
          className="textarea"
          style={{ minHeight: "70px" }}
          placeholder="Why is this change needed?"
          value={changeReason}
          onChange={(e) => setChangeReason(e.target.value)}
          required
        />
        <span className="subtle text-xs">A sentence or more: what changed and why. At least 15 characters and 3 words.</span>
      </div>

      <button className="btn btn-primary" type="submit" disabled={loading} style={{ marginTop: "0.9rem" }}>
        {loading ? <><span className="spinner spinner-light" /> Uploading…</> : "Upload"}
      </button>

      {error && <div className="toast toast-danger" style={{ marginTop: "0.9rem" }}>{error}</div>}

      {result && (
        <div className="col anim-fade-up" style={{ marginTop: "1.25rem" }}>
          <div className="row text-sm">
            <span className="subtle strong">Revision</span>
            <span className="badge badge-id">#{result.revision_id}</span>
          </div>
          <div>
            <p className="label" style={{ marginBottom: "0.4rem" }}>Diff preview</p>
            <div className="content-box content-box-scroll">{result.diff_preview}</div>
          </div>
        </div>
      )}
    </form>
  );
}
