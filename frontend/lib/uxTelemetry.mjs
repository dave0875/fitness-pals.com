import { authenticatedFetch } from "./authFetch.mjs";
import { classifyViewport, validateUxEvent } from "./productV2ReleaseContract.mjs";

export function currentViewport() {
  return classifyViewport(typeof window === "undefined" ? Number.NaN : window.innerWidth);
}

export async function trackUxEvent(event, fetchImpl = globalThis.fetch) {
  const payload = {
    ...event,
    viewport: event.viewport || currentViewport(),
  };
  if (!validateUxEvent(payload)) return false;

  try {
    const response = await authenticatedFetch(
      "/api/ux-events",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        keepalive: true,
      },
      fetchImpl
    );
    return response.ok;
  } catch (_error) {
    return false;
  }
}
