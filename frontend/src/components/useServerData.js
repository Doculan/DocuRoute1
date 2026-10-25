import { useCallback, useEffect, useState } from "react";
import axios from "axios";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/**
 * GET `url` with `params`, again whenever either changes or `reload()` is
 * called. State is set only in the request's callbacks, never in the
 * effect itself, and a reply that arrives after the URL or params moved
 * on is dropped, so a slow page 1 cannot overwrite page 2.
 *
 * Returns `{ data, error, reload }`. `data` keeps the last good answer
 * while the next loads, so a list does not blank between pages.
 */
export default function useServerData(url, params, failure = "Could not load.") {
  const key = JSON.stringify([url, params ?? null]);
  const [state, setState] = useState({ data: null, error: "" });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let current = true;
    const [path, query] = JSON.parse(key);
    axios.get(path, { ...getAuth(), params: query ?? undefined })
      .then((res) => { if (current) setState({ data: res.data, error: "" }); })
      .catch((err) => {
        if (current) setState((s) => ({ ...s, error: err.response?.data?.error || failure }));
      });
    return () => { current = false; };
  }, [key, tick, failure]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data: state.data, error: state.error, reload };
}
