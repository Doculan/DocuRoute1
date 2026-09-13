import { useState, useEffect, useCallback } from "react";
import axios from "axios";

export default function Departments() {
  const [departments, setDepartments] = useState([]);
  const [newDeptName, setNewDeptName] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  const token = localStorage.getItem("access_token");
  const authHeaders = { headers: { Authorization: `Bearer ${token}` } };

  const fetchDepartments = useCallback(async () => {
    setLoading(true);
    
    try {
      const res = await axios.get("/api/departments/", authHeaders);
      setDepartments(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { fetchDepartments(); }, [fetchDepartments]);

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
      <header className="page-head">
        <div>
          <h1 className="page-title">Departments</h1>
          <p className="page-subtitle">Organizational units that own manuals and staff accounts</p>
        </div>
      </header>

      <div className="card card-pad" style={{ marginBottom: "1.5rem" }}>
        <h3 className="section-title" style={{ marginBottom: "0.9rem" }}>Add new department</h3>
        <form onSubmit={handleCreate} className="row" style={{ gap: "0.75rem" }}>
          <input
            className="input"
            type="text"
            placeholder="e.g. Business Affairs"
            value={newDeptName}
            onChange={(e) => setNewDeptName(e.target.value)}
            required
          />
          <button className="btn btn-primary" type="submit">Create</button>
        </form>
      </div>

      {message && <div className="toast">{message}</div>}

      {loading ? (
        <div className="loading-row"><span className="spinner" /> Loading departments…</div>
      ) : departments.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">🏛️</div>
          <p className="empty-title">No departments yet</p>
          <p className="empty-text">Create your first department using the form above.</p>
        </div>
      ) : (
        <div className="table-wrap anim-fade-up">
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: "80px" }}>ID</th>
                  <th>Department name</th>
                  <th style={{ width: "120px" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {departments.map((dept) => (
                  <tr key={dept.id}>
                    <td className="muted">{dept.id}</td>
                    <td className="table-strong">{dept.name}</td>
                    <td>
                      <button
                        className="btn btn-danger-soft btn-sm"
                        onClick={() => handleDelete(dept.id, dept.name)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
