export function connectionState(status) {
  if (!status) return { action: "loading", label: "Checking connection…" };
  const sync = status.first_sync?.state;
  if (sync === "queued" || sync === "running") return { action: "wait", label: "Refresh in progress" };
  if (!status.garmin_connected) return { action: "connect", label: "Connect Garmin" };
  if (sync === "failed" || sync === "partial") return { action: "retry", label: "Retry refresh" };
  if (sync === "authorization_required") return { action: "connect", label: "Reconnect Garmin" };
  return { action: "refresh", label: "Refresh activity data" };
}

export function archiveState(capabilities, job) {
  const pending = ["upload_pending", "uploaded", "queued", "running"].includes(job?.status);
  return {
    canDriveImport: Boolean(capabilities?.drive?.available) && !pending,
    canUpload: Boolean(capabilities?.upload?.available) && !pending,
    driveReason: capabilities?.drive?.reason || "Checking Drive availability…",
    uploadReason: capabilities?.upload?.reason || "Checking upload availability…",
    pending,
    resultHref: job?.status === "completed" ? "/training" : null,
  };
}

function sameFilters(left, right) {
  return ["window", "sport", "goal"].every((key) => left?.[key] === right?.[key]);
}

export function dossierState(eligibility, jobs = []) {
  const currentJobs = [];
  const historicalJobs = [];
  for (const job of jobs) {
    const oldEmptySnapshot = eligibility?.eligible && job.status === "insufficient_data" && job.activity_count === 0;
    (sameFilters(job.filters, eligibility?.filters) && !oldEmptySnapshot ? currentJobs : historicalJobs).push(job);
  }
  return {
    currentJobs,
    historicalJobs,
    canGenerate: Boolean(eligibility?.eligible) && !currentJobs.some((job) => ["queued", "generating"].includes(job.status)),
  };
}

export function paginateActivities(activities = [], requestedPage = 1, pageSize = 25) {
  const totalPages = Math.max(1, Math.ceil(activities.length / pageSize));
  const page = Math.min(totalPages, Math.max(1, requestedPage));
  const start = (page - 1) * pageSize;
  const items = activities.slice(start, start + pageSize);
  return {
    items,
    page,
    totalPages,
    from: items.length ? start + 1 : 0,
    to: start + items.length,
  };
}
