import { useState, useEffect } from "react";
import axios from "axios";

export default function Departments() {
  const [departments, setDepartments] = useState([]);
  const [newDeptName, setNewDeptName] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  const token = localStorage.getItem("access_token");
  const authHeaders = { headers: { Authorization: `Bearer ${token}` } };

  const fetchDepartments = async () => {
    setLoading(true);
    try {
      const res = await axios.get("http://127.0.0.1:8000/api/departments/", authHeaders);
      setDepartments(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDepartments(); }, []);

  const showMessage = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3000);
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!newDeptName.trim()) return;
    try {
      await axios.post(
        "http://127.0.0.1:8000/api/departments/create/",
        { name: newDeptName }, authHeaders
      );
      setNewDeptName("");
      showMessage(`✅ "${newDeptName}" department created.`);
      fetchDepartments();
    } catch (err) {
      showMessage(err.response?.data?.error || "❌ Failed to create department.");
    }
  };

  const handleDelete = async (id, name) => {
    if (!confirm(`Delete "${name}"? This will also delete all its manuals.`)) return;
    try {
      await axios.delete(
        `http://127.0.0.1:8000/api/departments/${id}/delete/`,
        authHeaders
      );
      showMessage(`🗑️ "${name}" deleted.`);
      fetchDepartments();
    } catch { showMessage("❌ Failed to delete."); }
  };

  return (
    <div>
      <h2 style={styles.pageTitle}>Departments</h2>

      {/* Create Form */}
      <div style={styles.card}>
        <h3 style={styles.cardTitle}>Add New Department</h3>
        <form onSubmit={handleCreate} style={styles.form}>
          <input
            style={styles.input}
            type="text"
            placeholder="e.g. Business Affairs"
            value={newDeptName}
            onChange={(e) => setNewDeptName(e.target.value)}
            required
          />
          <button style={styles.createBtn} type="submit">
            + Create
          </button>
        </form>
      </div>

      {message && <div style={styles.toast}>{message}</div>}

      {/* Departments List */}
      {loading ? (
        <p style={styles.loading}>Loading...</p>
      ) : departments.length === 0 ? (
        <div style={styles.empty}>No departments yet. Create one above.</div>
      ) : (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>ID</th>
              <th style={styles.th}>Department Name</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {departments.map((dept) => (
              <tr key={dept.id} style={styles.tr}>
                <td style={styles.td}>{dept.id}</td>
                <td style={styles.td}>{dept.name}</td>
                <td style={styles.td}>
                  <button
                    style={styles.deleteBtn}
                    onClick={() => handleDelete(dept.id, dept.name)}
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
  form: { display: "flex", gap: "1rem" },
  input: {
    flex: 1, padding: "0.7rem 1rem", borderRadius: "8px",
    border: "1px solid #ddd", fontSize: "0.95rem", outline: "none",
  },
  createBtn: {
    padding: "0.7rem 1.5rem", backgroundColor: "#4f46e5",
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
