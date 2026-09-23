export const CRITICAL_ROUTES = Object.freeze([
  "/",
  "/welcome",
  "/today",
  "/coach",
  "/progress",
  "/training",
  "/settings",
  "/import/garmin-archive",
]);

export const CRITICAL_JOURNEYS = Object.freeze([
  {
    key: "new_athlete",
    entry: "/",
    checkpoints: ["/welcome", "/coach", "/today"],
  },
  {
    key: "returning_athlete",
    entry: "/auth/login?next=%2Ftoday",
    checkpoints: ["/today", "/coach"],
  },
  {
    key: "workout_analysis",
    entry: "/training",
    checkpoints: ["/activities/:id", "/coach"],
  },
  {
    key: "training_decision",
    entry: "/today",
    checkpoints: ["/coach", "/training"],
  },
  {
    key: "broken_connection",
    entry: "/settings#connections",
    checkpoints: ["/import/garmin-archive", "/training"],
  },
  {
    key: "failed_job",
    entry: "/import/garmin-archive",
    checkpoints: ["/settings#connections", "/training"],
  },
  {
    key: "mobile",
    entry: "/today",
    checkpoints: ["/coach", "/training", "/settings"],
  },
]);

export const PERFORMANCE_BUDGETS = Object.freeze({
  maxRouteJsBytes: 900 * 1024,
  maxCriticalJsBytes: 2500 * 1024,
});

export const UX_EVENT_ALLOWLIST = Object.freeze({
  events: ["surface_view", "action", "recovery_view"],
  surfaces: ["today", "coach", "progress", "training", "settings", "welcome", "archive", "public"],
  actions: ["ask_coach", "retry", "refresh", "filter", "plan_update", "connect", "import", "sign_out"],
  states: ["ready", "loading", "empty", "fresh", "stale", "partial", "failed", "disconnected", "authorization_expired", "unavailable"],
  viewports: ["mobile", "tablet", "desktop"],
});

const UX_EVENT_KEYS = new Set(["event", "surface", "action", "state", "viewport"]);

export function classifyViewport(width) {
  if (!Number.isFinite(width)) return "desktop";
  if (width <= 520) return "mobile";
  if (width <= 900) return "tablet";
  return "desktop";
}

export function validateUxEvent(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  if (Object.keys(payload).some((key) => !UX_EVENT_KEYS.has(key))) return false;
  if (!UX_EVENT_ALLOWLIST.events.includes(payload.event)) return false;
  if (!UX_EVENT_ALLOWLIST.surfaces.includes(payload.surface)) return false;
  if (!UX_EVENT_ALLOWLIST.viewports.includes(payload.viewport)) return false;
  if (payload.action !== undefined && !UX_EVENT_ALLOWLIST.actions.includes(payload.action)) return false;
  if (payload.state !== undefined && !UX_EVENT_ALLOWLIST.states.includes(payload.state)) return false;
  if (payload.event === "action" && payload.action === undefined) return false;
  return true;
}
