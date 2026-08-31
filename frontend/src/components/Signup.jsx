import { useState, useEffect } from "react";
import axios from "axios";
import logo from '../assets/QMS.png';

export default function Signup({ onBackToLogin }) {
  const [formData, setFormData] = useState({
    username: "",
    email: "",
    password: "",
    confirmPassword: "",
    department_id: "",
  });
  const [departments, setDepartments] = useState([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    console.log('Fetching departments...');
    setDepartmentsLoading(true);
    axios.get("/api/departments/")
      .then((res) => {
        console.log('Departments received:', res.data);
        console.log('Departments type:', typeof res.data);
        console.log('Departments length:', res.data.length);
        if (Array.isArray(res.data)) {
          setDepartments(res.data);
        } else {
          console.error('Departments response is not an array:', res.data);
          setDepartments([]);
        }
        setDepartmentsLoading(false);
      })
      .catch((error) => {
        console.error('Error fetching departments:', error);
        setDepartments([]);
        setDepartmentsLoading(false);
      });
  }, []);

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSignup = async (e) => {
    e.preventDefault();
    setError("");

    if (formData.password !== formData.confirmPassword) {
      return setError("Passwords do not match.");
    }
    if (formData.password.length < 8) {
      return setError("Password must be at least 8 characters.");
    }

    setLoading(true);
    try {
      await axios.post("/api/auth/register/", {
        username: formData.username,
        email: formData.email,
        password: formData.password,
        department_id: formData.department_id || null,
      });
      setSuccess(true);
    } catch (err) {
      const msg = err.response?.data?.error || "Registration failed.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div style={styles.page}>
        <div style={styles.left}>
          <div style={styles.brand}>
           <img src={logo} alt="DocuRoute logo" style={{ height: '250px', width: 'auto' }} />
                     <p style={styles.brandSub}>QUALITY MANAGEMENT SYSTEM ON ADMINISTRATIVE SERVICES <br></br>Controlled Document Management System</p>
                   </div>
        </div>
        <div style={styles.right}>
          <div style={styles.card}>
            <div style={styles.successIcon}>✅</div>
            <h2 style={styles.title}>Registration Sent!</h2>
            <p style={styles.successText}>
              Your account is pending admin approval. You'll be able to log in
              once an admin approves your account.
            </p>
            <button style={styles.button} onClick={onBackToLogin}>
              Back to Login
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.page}>
      <div style={styles.left}>
        <div style={styles.brand}>
         <img src={logo} alt="DocuRoute logo" style={{ height: '250px', width: 'auto' }} />
                   <p style={styles.brandSub}>QUALITY MANAGEMENT SYSTEM ON ADMINISTRATIVE SERVICES <br></br>Controlled Document Management System</p>
                 </div>
      </div>

      <div style={styles.right}>
        <div style={styles.card}>
          <h2 style={styles.title}>Create account</h2>
          <p style={styles.subtitle}>Fill in your details to register</p>

          <form onSubmit={handleSignup} style={styles.form}>
            <div style={styles.inputGroup}>
              <label style={styles.label}>Username</label>
              <input
                style={styles.input}
                type="text"
                name="username"
                value={formData.username}
                onChange={handleChange}
                placeholder="Enter username"
                required
              />
            </div>

            <div style={styles.inputGroup}>
              <label style={styles.label}>Email</label>
              <input
                style={styles.input}
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                placeholder="Enter email"
                required
              />
            </div>

            <div style={styles.inputGroup}>
              <label style={styles.label}>Department</label>
              <select
                key={departments.length}
                style={{
                  ...styles.input,
                  backgroundColor: 'white',
                  cursor: departmentsLoading ? 'not-allowed' : 'pointer',
                  minHeight: '40px'
                }}
                name="department_id"
                value={formData.department_id}
                onChange={handleChange}
                disabled={departmentsLoading}
              >
                <option value="">
                  {departmentsLoading ? "Loading departments..." : "Select your department"}
                </option>
                {console.log('Rendering departments:', departments)}
                {departments && departments.length > 0 ? (
                  departments.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))
                ) : (
                  !departmentsLoading && <option disabled>No departments available</option>
                )}
              </select>
            </div>

            <div style={styles.inputGroup}>
              <label style={styles.label}>Password</label>
              <input
                style={styles.input}
                type="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                placeholder="At least 8 characters"
                required
              />
            </div>

            <div style={styles.inputGroup}>
              <label style={styles.label}>Confirm Password</label>
              <input
                style={styles.input}
                type="password"
                name="confirmPassword"
                value={formData.confirmPassword}
                onChange={handleChange}
                placeholder="Repeat your password"
                required
              />
            </div>

            {error && <p style={styles.error}>{error}</p>}

            <button style={styles.button} type="submit" disabled={loading}>
              {loading ? "Registering..." : "Sign Up"}
            </button>
          </form>

          <p style={styles.loginText}>
            Already have an account?{" "}
            <span style={styles.link} onClick={onBackToLogin}>
              Log in
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}

const styles = {
  page: {
    display: "flex",
    height: "100vh",
    width: "100vw",
    overflow: "hidden",
  },
  left: {
    flex: 1,
    backgroundColor: "#090749",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "3rem",
  },
  brand: {
    textAlign: "center",
  },
  brandTitle: {
    color: "#fff",
    fontSize: "3rem",
    fontWeight: "800",
    margin: "0 0 1rem 0",
    letterSpacing: "-1px",
  },
  brandSub: {
    color: "#8888aa",
    fontSize: "1rem",
    lineHeight: "1.6",
    maxWidth: "300px",
    margin: "0 auto",
  },
  right: {
    width: "480px",
    minWidth: "480px",
    backgroundColor: "#f0f2f5",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "2rem",
    overflowY: "auto",
  },
  card: {
    backgroundColor: "#fff",
    padding: "2.5rem",
    borderRadius: "16px",
    boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
    width: "100%",
  },
  title: {
    margin: "0 0 0.25rem 0",
    fontSize: "1.6rem",
    fontWeight: "700",
    color: "#1a1a2e",
  },
  subtitle: {
    color: "#888",
    marginBottom: "1.8rem",
    marginTop: 0,
    fontSize: "0.9rem",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "1rem",
  },
  inputGroup: {
    display: "flex",
    flexDirection: "column",
    gap: "0.3rem",
  },
  label: {
    fontSize: "0.85rem",
    fontWeight: "600",
    color: "#333",
  },
  input: {
    padding: "0.75rem 1rem",
    borderRadius: "8px",
    border: "1px solid #ddd",
    fontSize: "0.95rem",
    outline: "none",
  },
  button: {
    marginTop: "0.5rem",
    padding: "0.85rem",
    backgroundColor: "#4f46e5",
    color: "#fff",
    border: "none",
    borderRadius: "8px",
    fontSize: "1rem",
    fontWeight: "600",
    cursor: "pointer",
  },
  error: {
    color: "#e53e3e",
    fontSize: "0.85rem",
    textAlign: "center",
    margin: 0,
    padding: "0.5rem",
    backgroundColor: "#fff5f5",
    borderRadius: "8px",
    border: "1px solid #fed7d7",
  },
  successIcon: {
    fontSize: "3rem",
    textAlign: "center",
    marginBottom: "1rem",
  },
  successText: {
    textAlign: "center",
    color: "#555",
    marginBottom: "1.5rem",
    lineHeight: "1.6",
  },
  loginText: {
    textAlign: "center",
    marginTop: "1.2rem",
    fontSize: "0.875rem",
    color: "#666",
  },
  link: {
    color: "#4f46e5",
    cursor: "pointer",
    fontWeight: "600",
  },
};
