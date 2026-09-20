import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "./ConfirmDestructive";

export default function Departments() {
  const [departments, setDepartments] = useState([]);
  const [newDeptName, setNewDeptName] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  // Holds what was chosen until the password prompt comes back with a
  // token. The widest blast radius in the application: deleting a
  // department takes every manual in it.
  const [pendingDelete, setPendingDelete] = useState(null);

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
        "/api/departments/create/",
        { name: newDeptName }, authHeaders
      );
      setNewDeptName("");
      showMessage(`✅ "${newDeptName}" department created.`);
      fetchDepartments();
    } catch (err) {
      showMessage(err.response?.data?.error || "❌ Failed to create department.");
    }
  };

  const handleDelete = async (token) => {
    const { id, name } = pendingDelete;
    setPendingDelete(null);
    try {
      await axios.delete(`/api/departments/${id}/delete/`, {
        headers: { ...authHeaders.headers, ...reauthHeader(token) },
      });
      showMessage(`🗑️ "${name}" deleted.`);
      fetchDepartments();
    } catch (err) {
      showMessage(err.response?.data?.error || "❌ Failed to delete.");
    }
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
                    <td className="mono subtle">{dept.id}</td>
                    <td className="table-strong">{dept.name}</td>
                    <td>
                      <span className="table-actions on-hover">
                        <button
                          className="btn btn-danger-soft btn-sm"
                          onClick={() => setPendingDelete({
                            id: dept.id, name: dept.name,
                            manuals: dept.manual_count,
                          })}
                        >
                          Delete
                        </button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {pendingDelete && (
        <ConfirmDestructive
          title={`Delete ${pendingDelete.name}?`}
          body={`Every manual in ${pendingDelete.name} is deleted with it, along with their sections and every revision proposed against them. The master copy PDFs stay on disk, but the extracted text and all of its history do not.`}
          confirmLabel="Delete department"
          onConfirm={handleDelete}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
