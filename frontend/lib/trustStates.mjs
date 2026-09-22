const PENDING_JOB_STATES = new Set([
  "upload_pending",
  "uploaded",
  "queued",
  "processing",
  "running",
]);

const SIGNALS = [
  ["activities", "Activities"],
  ["sleep", "Sleep"],
  ["intensity", "Intensity"],
];

function hasUsableHistory(status, home) {
  return Boolean(status?.latest_activities?.length) || home?.state === "ready";
}

function pendingArchive(capabilities) {
  return PENDING_JOB_STATES.has(capabilities?.latest_job?.status);
}

function pendingSync(status) {
  return ["queued", "running"].includes(status?.first_sync?.state);
}

export function freshnessSignals(home) {
  const signals = home?.freshness?.signals || {};
  return SIGNALS.map(([key, label]) => {
    const raw = signals[key] || {};
    const state = ["fresh", "stale", "unknown", "error"].includes(raw.state)
      ? raw.state
      : "unknown";
    return {
      key,
      label,
      state,
      dataThrough: raw.data_through || null,
    };
  });
}

export function connectionTrustState(status, home, capabilities) {
  const historyAvailable = hasUsableHistory(status, home);
  const activationState = status?.activation?.state || null;
  const syncState = status?.first_sync?.state || null;
  const archiveState = capabilities?.latest_job?.status || null;
  const updating = pendingSync(status) || pendingArchive(capabilities);
  const sourceLabel = status?.garmin_connected ? "Connected source" : "Disconnected source";

  if (activationState === "authorization_expired" || syncState === "authorization_required") {
    return {
      state: "authorization_expired",
      label: "Authorization needs attention",
      detail: historyAvailable
        ? "Saved training history remains available, but future source updates need authorization."
        : "Future source updates need authorization before training history can arrive.",
      historyAvailable,
      sourceLabel,
      updating: false,
    };
  }

  if (
    activationState === "import_failed" ||
    syncState === "failed" ||
    archiveState === "failed"
  ) {
    return {
      state: "failed",
      label: "Latest update failed",
      detail: historyAvailable
        ? "Existing saved training history is unchanged. Review the failed import or retry the supported refresh."
        : "No usable history arrived from the latest attempt. Review the import and try again.",
      historyAvailable,
      sourceLabel,
      updating: false,
    };
  }

  if (activationState === "unsupported_capability") {
    return {
      state: "unavailable",
      label: "Live refresh unavailable",
      detail: historyAvailable
        ? "Saved history remains usable. Use one of the supported archive paths for additional data."
        : "This connection cannot import activities here yet. Use a supported archive path instead.",
      historyAvailable,
      sourceLabel,
      updating: false,
    };
  }

  if (updating && historyAvailable) {
    return {
      state: "partial",
      label: "History available while an update runs",
      detail: "Existing canonical history is usable while additional training data continues importing.",
      historyAvailable,
      sourceLabel,
      updating: true,
    };
  }

  if (updating) {
    return {
      state: "updating",
      label: "Training history is updating",
      detail: "No usable activity history has arrived yet. This work continues after you leave Settings.",
      historyAvailable,
      sourceLabel,
      updating: true,
    };
  }

  if (historyAvailable && !status?.garmin_connected) {
    return {
      state: "archive_only",
      label: "Saved history only",
      detail: "Canonical training history is retained, but this account is not receiving future live updates.",
      historyAvailable,
      sourceLabel,
      updating: false,
    };
  }

  if (!historyAvailable && !status?.garmin_connected) {
    return {
      state: "empty",
      label: "No training history yet",
      detail: "Add a supported training source or archive when you are ready to unlock athlete-specific guidance.",
      historyAvailable,
      sourceLabel,
      updating: false,
    };
  }

  if (home?.freshness?.state === "stale" || activationState === "stale") {
    return {
      state: "stale",
      label: "Training data needs a refresh",
      detail: "Saved history remains visible, but its newest relevant signal is older than expected.",
      historyAvailable,
      sourceLabel,
      updating: false,
    };
  }

  if (home?.freshness?.state === "partial") {
    return {
      state: "partial",
      label: "Some signals need attention",
      detail: "Usable training history is available, but one or more supporting signals are stale or unknown.",
      historyAvailable,
      sourceLabel,
      updating: false,
    };
  }

  if (status?.garmin_connected) {
    return {
      state: "connected",
      label: "Training source connected",
      detail: "Fitness Pals can use the canonical history currently available for this account.",
      historyAvailable,
      sourceLabel,
      updating: false,
    };
  }

  return {
    state: "unknown",
    label: "Connection state unavailable",
    detail: "Fitness Pals cannot determine the current connection state yet.",
    historyAvailable,
    sourceLabel,
    updating: false,
  };
}

export function trustTone(state) {
  if (state === "connected" || state === "fresh") return "success";
  if (state === "updating" || state === "partial" || state === "archive_only") return "neutral";
  return "warning";
}
