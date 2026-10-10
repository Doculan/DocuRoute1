import { Fragment, useState, useEffect, useCallback } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "./ConfirmDestructive";

export default function UserManagement() {
  const [pendingUsers, setPendingUsers] = useState([]);
  const [approvedUsers, setApprovedUsers] = useState([]);
  const [activeTab, setActiveTab] = useState("pending");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  // Rejecting deletes the account. It sits next to Approve, which is
  // exactly why it should not be a single click.
  const [pendingReject, setPendingReject] = useState(null);
  const [pendingApprove, setPendingApprove] = useState(null);
  // Which applicant's details are open.
  const [openDetails, setOpenDetails] = useState(null);

  const token = localStorage.getItem("access_token");
  const authHeaders = { headers: { Authorization: `Bearer ${token}` } };

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    
    try {
      const [pendingRes, approvedRes] = await Promise.all([
        axios.get("/api/admin/pending-users/", authHeaders),
        axios.get("/api/admin/approved-users/", authHeaders),
      ]);
      setPendingUsers(pendingRes.data);
      setApprovedUsers(approvedRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const showMessage = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3000);
  };

  const handleApprove = async (confirmationToken) => {
    const { id: userId, username } = pendingApprove;
    setPendingApprove(null);
    try {
      const { data } = await axios.patch(
        `/api/admin/approve-user/${userId}/`,
        {}, { headers: { ...authHeaders.headers, ...reauthHeader(confirmationToken) } }
      );
      // Approval places them in the office they chose; the note says when
      // it could not (no office chosen, or the office has been retired).
      showMessage(`✅ ${data.message || `${username} approved.`}${data.note ? ` ${data.note}` : ""}`);
      fetchUsers();
    } catch (err) { showMessage(err.response?.data?.error || "Failed to approve."); }
  };

  const handleReject = async (token) => {
    const { id, username } = pendingReject;
    setPendingReject(null);
    try {
      await axios.delete(`/api/admin/reject-user/${id}/`, {
        headers: { ...authHeaders.headers, ...reauthHeader(token) },
      });
      showMessage(`🗑️ ${username} rejected.`);
      fetchUsers();
    } catch (err) {
      showMessage(err.response?.data?.error || "❌ Failed to reject.");
    }
  };

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Users</h1>
          <p className="page-subtitle">Review access requests and manage approved accounts</p>
        </div>
      </header>

      <div className="stat-grid">
        <div className="stat-card is-warning">
          <span className="stat-value">{pendingUsers.length}</span>
          <span className="stat-label">Pending approval</span>
        </div>
        <div className="stat-card is-success">
          <span className="stat-value">{approvedUsers.length}</span>
          <span className="stat-label">Approved users</span>
        </div>
      </div>

      {message && <div className="toast">{message}</div>}

      <div className="tabs">
        <button
          className={`tab${activeTab === "pending" ? " is-active" : ""}`}
          onClick={() => setActiveTab("pending")}
        >
          Pending <span className="tab-count">{pendingUsers.length}</span>
        </button>
        <button
          className={`tab${activeTab === "approved" ? " is-active" : ""}`}
          onClick={() => setActiveTab("approved")}
        >
          Approved <span className="tab-count">{approvedUsers.length}</span>
        </button>
      </div>

      {loading ? (
        <div className="loading-row"><span className="spinner" /> Loading users…</div>
      ) : activeTab === "pending" ? (
        pendingUsers.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">🎉</div>
            <p className="empty-title">All caught up</p>
            <p className="empty-text">There are no pending access requests right now.</p>
          </div>
        ) : (
          <div className="table-wrap anim-fade-up">
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Full name</th>
                    <th>Email</th>
                    <th>Office</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingUsers.map((user) => (
                    <Fragment key={user.id}>
                    <tr>
                      <td className="table-strong">{user.username}</td>
                      <td>{user.full_name}</td>
                      <td>{user.email}</td>
                      <td>
                        {user.requested_office || <span className="subtle">Not sure</span>}
                        <div className="subtle text-xs">{user.requested_position_label}</div>
                        {user.approval_warning && <div className="text-xs" role="status">{user.approval_warning}</div>}
                      </td>
                      <td>
                        <div className="table-actions">
                          <button className="btn btn-ghost btn-sm"
                                  aria-expanded={openDetails === user.id}
                                  onClick={() => setOpenDetails(openDetails === user.id ? null : user.id)}>
                            {openDetails === user.id ? "Hide" : "Details"}
                          </button>
                          <button className="btn btn-success btn-sm" onClick={() => setPendingApprove(user)}>
                            Approve
                          </button>
                          <button className="btn btn-danger-soft btn-sm" onClick={() => setPendingReject({ id: user.id, username: user.username })}>
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                    {openDetails === user.id && (
                      <tr>
                        <td colSpan={5}>
                          {/* Everything they gave at sign-up, except the password. */}
                          <dl className="detail-grid" style={{ margin: "0.25rem 0" }}>
                            <dt>Full name</dt><dd>{user.full_name || "—"}</dd>
                            <dt>Username</dt><dd>{user.username}</dd>
                            <dt>Email</dt><dd>{user.email || "—"}</dd>
                            <dt>Office chosen</dt>
                            <dd>
                              {user.requested_office
                                ? <>{user.requested_office}</>
                                : <span className="subtle">Not sure — assign an office after approving</span>}
                            </dd>
                            <dt>Position chosen</dt><dd>{user.requested_position_label}</dd>
                            <dt>Signed up</dt>
                            <dd>{user.date_joined ? new Date(user.date_joined).toLocaleString() : "—"}</dd>
                          </dl>
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      ) : approvedUsers.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">👥</div>
          <p className="empty-title">No approved users yet</p>
          <p className="empty-text">Approved accounts will appear here once you action a request.</p>
        </div>
      ) : (
        <div className="table-wrap anim-fade-up">
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Full name</th>
                  <th>Email</th>
                  <th>Role</th>
                </tr>
              </thead>
              <tbody>
                {approvedUsers.map((user) => (
                  <tr key={user.id}>
                    <td className="table-strong">{user.username}</td>
                    <td>{user.full_name}</td>
                    <td>{user.email}</td>
                    <td><span className="badge">{user.role}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {pendingApprove && (
        <ConfirmDestructive
          title={`Approve ${pendingApprove.full_name || pendingApprove.username}?`}
          body={pendingApprove.approval_warning || (pendingApprove.requested_office
            ? `This grants access as ${pendingApprove.requested_position_label} at ${pendingApprove.requested_office}.`
            : "This approves system access. Assign their office and position in People afterwards.")}
          passwordHint="Confirm because accepting grants system access and may assign an office position."
          confirmLabel="Approve"
          onConfirm={handleApprove}
          onCancel={() => setPendingApprove(null)}
        />
      )}

      {pendingReject && (
        <ConfirmDestructive
          title={`Reject ${pendingReject.username}?`}
          body={`The account is deleted, not just refused. ${pendingReject.username} would have to register again, and anything they had submitted goes with it.`}
          confirmLabel="Reject and delete"
          onConfirm={handleReject}
          onCancel={() => setPendingReject(null)}
        />
      )}
    </div>
  );
}
