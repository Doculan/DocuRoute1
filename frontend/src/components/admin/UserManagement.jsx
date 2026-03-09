import { useState, useEffect } from "react";
import axios from "axios";

export default function UserManagement() {
  const [pendingUsers, setPendingUsers] = useState([]);
  const [approvedUsers, setApprovedUsers] = useState([]);
  const [activeTab, setActiveTab] = useState("pending");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  const token = localStorage.getItem("access_token");
  const authHeaders = { headers: { Authorization: `Bearer ${token}` } };

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const [pendingRes, approvedRes] = await Promise.all([
        axios.get("http://127.0.0.1:8000/api/admin/pending-users/", authHeaders),
        axios.get("http://127.0.0.1:8000/api/admin/approved-users/", authHeaders),
      ]);
      setPendingUsers(pendingRes.data);
      setApprovedUsers(approvedRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchUsers(); }, []);

  const showMessage = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3000);
  };

  const handleApprove = async (userId, username) => {
    try {
      await axios.patch(
        `http://127.0.0.1:8000/api/admin/approve-user/${userId}/`,
        {}, authHeaders
      );
      showMessage(`✅ ${username} approved.`);
      fetchUsers();
    } catch { showMessage("❌ Failed to approve."); }
  };

  const handleReject = async (userId, username) => {
    if (!confirm(`Reject and delete ${username}?`)) return;
    try {
      await axios.delete(
        `http://127.0.0.1:8000/api/admin/reject-user/${userId}/`,
        authHeaders
      );
      showMessage(`🗑️ ${username} rejected.`);
      fetchUsers();
    } catch { showMessage("❌ Failed to reject."); }
  };

  return (
    <div>
      <h2 style={styles.pageTitle}>User Management</h2>

      <div style={styles.statsRow}>
        <div style={styles.statCard}>
          <span style={styles.statNum}>{pendingUsers.length}</span>
          <span style={styles.statLabel}>Pending Approval</span>
        </div>
        <div style={styles.statCard}>
          <span style={styles.statNum}>{approvedUsers.length}</span>
          <span style={styles.statLabel}>Approved Users</span>
        </div>
      </div>

      {message && <div style={styles.toast}>{message}</div>}

      <div style={styles.tabs}>
        <button
          style={activeTab === "pending" ? styles.tabActive : styles.tab}
          onClick={() => setActiveTab("pending")}
        >
          Pending ({pendingUsers.length})
        </button>
        <button
          style={activeTab === "approved" ? styles.tabActive : styles.tab}
          onClick={() => setActiveTab("approved")}
        >
          Approved ({approvedUsers.length})
        </button>
      </div>

      {loading ? (
        <p style={styles.loading}>Loading...</p>
      ) : activeTab === "pending" ? (
        pendingUsers.length === 0 ? (
          <div style={styles.empty}>🎉 No pending users.</div>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Username</th>
                <th style={styles.th}>Email</th>
                <th style={styles.th}>Department</th>
                <th style={styles.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pendingUsers.map((user) => (
                <tr key={user.id} style={styles.tr}>
                  <td style={styles.td}>{user.username}</td>
                  <td style={styles.td}>{user.email}</td>
                  <td style={styles.td}>{user.department}</td>
                  <td style={styles.td}>
                    <button style={styles.approveBtn} onClick={() => handleApprove(user.id, user.username)}>
                      Approve
                    </button>
                    <button style={styles.rejectBtn} onClick={() => handleReject(user.id, user.username)}>
                      Reject
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : approvedUsers.length === 0 ? (
        <div style={styles.empty}>No approved users yet.</div>
      ) : (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Username</th>
              <th style={styles.th}>Email</th>
              <th style={styles.th}>Department</th>
              <th style={styles.th}>Role</th>
            </tr>
          </thead>
          <tbody>
            {approvedUsers.map((user) => (
              <tr key={user.id} style={styles.tr}>
                <td style={styles.td}>{user.username}</td>
                <td style={styles.td}>{user.email}</td>
                <td style={styles.td}>{user.department}</td>
                <td style={styles.td}>
                  <span style={styles.badge}>{user.role}</span>
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
  statsRow: { display: "flex", gap: "1rem", marginBottom: "1.5rem" },
  statCard: {
    flex: 1, backgroundColor: "#fff", borderRadius: "10px",
    padding: "1.2rem", textAlign: "center",
    boxShadow: "0 2px 8px rgba(0,0,0,0.07)",
    display: "flex", flexDirection: "column", gap: "0.3rem",
  },
  statNum: { fontSize: "2rem", fontWeight: "700", color: "#4f46e5" },
  statLabel: { fontSize: "0.85rem", color: "#666" },
  toast: {
    backgroundColor: "#ebf8ff", border: "1px solid #bee3f8",
    borderRadius: "8px", padding: "0.75rem 1rem",
    marginBottom: "1rem", color: "#2b6cb0", fontWeight: "500",
  },
  tabs: { display: "flex", gap: "0.5rem", marginBottom: "1rem" },
  tab: {
    padding: "0.5rem 1.2rem", border: "2px solid #ddd",
    borderRadius: "8px", backgroundColor: "#fff",
    cursor: "pointer", fontWeight: "600", color: "#666",
  },
  tabActive: {
    padding: "0.5rem 1.2rem", border: "2px solid #4f46e5",
    borderRadius: "8px", backgroundColor: "#4f46e5",
    cursor: "pointer", fontWeight: "600", color: "#fff",
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
  approveBtn: {
    padding: "0.35rem 0.85rem", backgroundColor: "#38a169",
    color: "#fff", border: "none", borderRadius: "6px",
    cursor: "pointer", fontWeight: "600", marginRight: "0.5rem",
  },
  rejectBtn: {
    padding: "0.35rem 0.85rem", backgroundColor: "#e53e3e",
    color: "#fff", border: "none", borderRadius: "6px",
    cursor: "pointer", fontWeight: "600",
  },
  badge: {
    padding: "0.25rem 0.6rem", backgroundColor: "#ebf4ff",
    color: "#4f46e5", borderRadius: "20px",
    fontSize: "0.78rem", fontWeight: "600",
  },
  empty: {
    textAlign: "center", padding: "3rem", color: "#888",
    backgroundColor: "#fff", borderRadius: "10px",
  },
  loading: { textAlign: "center", color: "#888", padding: "2rem" },
};
