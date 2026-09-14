import axios from "axios";

// Access tokens expire after an hour. Without this the refresh token sat in
// localStorage unused, so any write made after that hour failed with a 401 and
// a generic error toast that gave no hint the session had simply lapsed.
//
// Imported once in main.jsx; it patches the shared axios default instance that
// every component already uses.

const REFRESH_URL = "/api/auth/refresh/";

let refreshRequest = null;

function clearSession() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("role");
  localStorage.removeItem("username");
  localStorage.removeItem("department");
}

// One in-flight refresh shared by every request that 401s at the same time,
// so a burst of parallel calls doesn't fire a burst of refreshes.
function refreshAccessToken() {
  if (refreshRequest) return refreshRequest;

  const refresh = localStorage.getItem("refresh_token");
  if (!refresh) return Promise.reject(new Error("no refresh token"));

  refreshRequest = axios
    .post(REFRESH_URL, { refresh }, { skipAuthRefresh: true })
    .then((res) => {
      const token = res.data.access;
      localStorage.setItem("access_token", token);
      return token;
    })
    .finally(() => {
      refreshRequest = null;
    });

  return refreshRequest;
}

axios.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { response, config } = error;

    // Only a 401 is recoverable here, and only once per request — otherwise a
    // still-rejected retry would loop. The refresh call itself is exempt.
    if (
      response?.status !== 401 ||
      !config ||
      config._retried ||
      config.skipAuthRefresh
    ) {
      return Promise.reject(error);
    }

    config._retried = true;

    try {
      const token = await refreshAccessToken();
      config.headers = { ...config.headers, Authorization: `Bearer ${token}` };
      return axios(config);
    } catch {
      // The refresh token is gone or itself expired — the session is genuinely
      // over, so drop it and send the user back to the login screen.
      clearSession();
      window.location.reload();
      return Promise.reject(error);
    }
  }
);
