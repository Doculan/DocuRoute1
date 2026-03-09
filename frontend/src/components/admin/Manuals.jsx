import { useState, useEffect } from "react";
import axios from "axios";

export default function Manuals() {
  const [manuals, setManuals] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [form, setForm] = useState({ title: "", department_id: "", file: null });
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    const token = localStorage.getItem("access_token");
    const authHeaders = { headers: { Authorization: `Bearer ${token}` } };
    try {
      const [manualsRes, deptsRes] = await Promise.all([
        axios.get("http://127.0.0.1:8000/api/manuals/", authHeaders),
        axios.get("http://127.0.0.1:8000/api/departments/", authHeaders),
      ]);
      setManuals(manualsRes.data);
      setDepartments(deptsRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const showMessage = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 4000);
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!form.title || !form.department_id || !form.file) return;
    setUploading(true);
    const token = localStorage.getItem("access_token");

    const formData = new FormData();
    formData.append("title", form.title);
    formData.append("department_id", form.department_id);
    formData.append("file", form.file);

    try {
      const res = await axios.post(
        "http://127.0.0.1:8000/api/manuals/upload/",
        formData,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      // ✅ Show auto-section result
      showMessage(
        res.data.sections_created > 0
          ? `✅ "${res.data.title}" uploaded — ${res.data.sections_created} sections auto-detected! Go to Sections to review them.`
          : `✅ "${res.data.title}" uploaded — No sections detected. Go to Sections to add them manually.`
      );
      setForm({ title: "", department_id: "", file: null });
      fetchData();
    } catch (err) {
      showMessage(err.response?.data?.error || "❌ Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id, title) => {
    if (!confirm(`Delete "${title}"? All its sections and revisions will be deleted too.`)) return;
    const token = localStorage.getItem("access_token");
    const authHeaders = { headers: { Authorization: `Bearer ${token}` } };
    try {
      await axios.delete(`http://127.0.0.1:8000/api/manuals/${id}/delete/`, authHeaders);
      showMessage(`🗑️ "${title}" deleted.`);
      fetchData();
    } catch { showMessage("❌ Failed to delete."); }
  };

  return (
    <div>
      <h2 style={styles.pageTitle}>Manuals</h2>

      <div style={styles.card}>
        <h3 style={styles.cardTitle}>Upload Master Copy</h3>
        <form onSubmit={handleUpload} style={styles.form}>
          <input
            style={styles.input}
            type="text"
            placeholder="Manual title (e.g. Business Affairs Manual)"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            required
          />
          <select
            style={styles.input}
            value={form.department_id}
            onChange={(e) => setForm({ ...form, department_id: e.target.value })}
            required
          >
            <option value="">Select Department</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
          <input
            style={styles.input}
            type="file"
            accept=".pdf,.txt,.png,.jpg,.jpeg"
            onChange={(e) => setForm({ ...form, file: e.target.files[0] })}
            required
          />
          <button style={styles.uploadBtn} type="submit" disabled={uploading}>
            {uploading ? "⏳ Extracting & auto-sectioning..." : "Upload"}
          </button>
        </form>
      </div>

      {message && <div style={styles.toast}>{message}</div>}

      {loading ? (
        <p style={styles.loading}>Loading...</p>
      ) : manuals.length === 0 ? (
        <div style={styles.empty}>No manuals yet. Upload one above.</div>
      ) : (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Title</th>
              <th style={styles.th}>Department</th>
              <th style={styles.th}>Sections</th>
              <th style={styles.th}>Version</th>
              <th style={styles.th}>Uploaded By</th>
              <th style={styles.th}>Date</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {manuals.map((m) => (
              <tr key={m.id} style={styles.tr}>
                <td style={styles.td}>{m.title}</td>
                <td style={styles.td}>{m.department}</td>
                <td style={styles.td}>
                  <span style={styles.badge}>{m.section_count} sections</span>
                </td>
                {/* ✅ Document version column */}
                <td style={styles.td}>
                  <span style={styles.versionBadge}>v{m.version}</span>
                </td>
                <td style={styles.td}>{m.uploaded_by}</td>
                <td style={styles.td}>
                  {new Date(m.uploaded_at).toLocaleDateString()}
                </td>
                <td style={styles.td}>
                  <button
                    style={styles.deleteBtn}
                    onClick={() => handleDelete(m.id, m.title)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const styles = {
  pageTitle: { margin: "0 0 1.5rem 0", color: "#1a1a2e" },
  card: {
    backgroundColor: "#fff", borderRadius: "10px",
    padding: "1.5rem", marginBottom: "1.5rem",
    boxShadow: "0 2px 8px rgba(0,0,0,0.07)",
  },
  cardTitle: { margin: "0 0 1rem 0", color: "#333", fontSize: "1rem" },
  form: { display: "flex", flexDirection: "column", gap: "0.75rem" },
  input: {
    padding: "0.7rem 1rem", borderRadius: "8px",
    border: "1px solid #ddd", fontSize: "0.95rem", outline: "none",
  },
  uploadBtn: {
    padding: "0.75rem", backgroundColor: "#4f46e5",
    color: "#fff", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600",
  },
  toast: {
    backgroundColor: "#ebf8ff", border: "1px solid #bee3f8",
    borderRadius: "8px", padding: "0.75rem 1rem",
    marginBottom: "1rem", color: "#2b6cb0", fontWeight: "500",
  },
  table: {
    width: "100%", borderCollapse: "collapse", backgroundColor: "#fff",
    borderRadius: "10px", overflow: "hidden",
    boxShadow: "0 2px 8px rgba(0,0,0,0.07)",
  },
  th: {
    padding: "0.85rem 1rem", backgroundColor: "#f7f8fc",
    textAlign: "left", fontSize: "0.8rem",
    fontWeight: "700", color: "#444", textTransform: "uppercase",
  },
  tr: { borderBottom: "1px solid #f0f0f0" },
  td: { padding: "0.85rem 1rem", fontSize: "0.9rem", color: "#333" },
  badge: {
    padding: "0.25rem 0.6rem", backgroundColor: "#ebf4ff",
    color: "#4f46e5", borderRadius: "20px",
    fontSize: "0.78rem", fontWeight: "600",
  },
  // ✅ NEW
  versionBadge: {
    padding: "0.25rem 0.6rem", backgroundColor: "#fefcbf",
    color: "#b7791f", borderRadius: "20px",
    fontSize: "0.78rem", fontWeight: "700",
    border: "1px solid #f6e05e",
  },
  deleteBtn: {
    padding: "0.35rem 0.85rem", backgroundColor: "#e53e3e",
    color: "#fff", border: "none", borderRadius: "6px",
    cursor: "pointer", fontWeight: "600",
  },
  empty: {
    textAlign: "center", padding: "3rem", color: "#888",
    backgroundColor: "#fff", borderRadius: "10px",
  },
  loading: { textAlign: "center", color: "#888", padding: "2rem" },
};
