let refreshInFlight = null;

async function refreshSession(fetchImpl) {
  if (!refreshInFlight) {
    refreshInFlight = Promise.resolve().then(() =>
      fetchImpl("/auth/refresh", {
        method: "POST",
        credentials: "same-origin",
      })
    );
  }
  const activeRefresh = refreshInFlight;
  try {
    return await activeRefresh;
  } finally {
    if (refreshInFlight === activeRefresh) refreshInFlight = null;
  }
}

function requestUrl(input) {
  return typeof input === "string" ? input : input?.url;
}

function isRefreshRequest(input) {
  try {
    return new URL(requestUrl(input), "https://fitness-pals.invalid").pathname === "/auth/refresh";
  } catch (_error) {
    return false;
  }
}

export async function authenticatedFetch(input, init = {}, fetchImpl = globalThis.fetch) {
  const requestInit = { credentials: "same-origin", ...init };
  const response = await fetchImpl(input, requestInit);
  if (response.status !== 401 || isRefreshRequest(input)) return response;

  let refreshResponse;
  try {
    refreshResponse = await refreshSession(fetchImpl);
  } catch (_error) {
    return response;
  }
  if (!refreshResponse.ok) return response;
  return fetchImpl(input, requestInit);
}

export async function authenticatedJson(input, init = {}, fetchImpl = globalThis.fetch) {
  const { json, headers, ...requestInit } = init;
  if (json !== undefined) {
    requestInit.body = JSON.stringify(json);
    requestInit.headers = { "Content-Type": "application/json", ...headers };
  } else if (headers !== undefined) {
    requestInit.headers = headers;
  }

  const response = await authenticatedFetch(input, requestInit, fetchImpl);
  if (!response.ok) {
    const error = new Error(`Authenticated request failed with status ${response.status}`);
    error.status = response.status;
    error.response = { status: response.status };
    throw error;
  }
  return response.status === 204 ? null : response.json();
}
