export function connectionState(status) {
  if (!status) return { action: "loading", label: "Checking connection…", enabled: false, href: null };
  const activationAction = status.activation?.action;
  if (activationAction) {
    return {
      action: activationAction.kind,
      label: activationAction.label,
      href: activationAction.href || null,
      enabled: activationAction.enabled !== false,
      state: status.activation.state,
    };
  }

  // Compatibility for responses during rolling deployment.
  const sync = status.first_sync?.state;
  if (sync === "queued" || sync === "running") return { action: "wait", label: "Refresh in progress", enabled: false, href: "/training" };
  if (!status.garmin_connected) return { action: "archive", label: "Review training data options", enabled: true, href: "/import/garmin-archive" };
  if (status.garmin_sync_available === false) return { action: "archive", label: "Use a supported training import", enabled: true, href: "/import/garmin-archive" };
  if (sync === "failed" || sync === "partial") return { action: "retry", label: "Retry refresh", enabled: true, href: null };
  if (sync === "authorization_required") return { action: "archive", label: "Review training data options", enabled: true, href: "/import/garmin-archive" };
  return { action: "refresh", label: "Refresh activity data", enabled: true, href: null };
}

export function archiveState(capabilities, job) {
  const pending = ["upload_pending", "uploaded", "queued", "processing", "running"].includes(job?.status);
  return {
    canDriveImport: Boolean(capabilities?.drive?.available) && !pending,
    canUpload: Boolean(capabilities?.upload?.available) && !pending,
    driveReason: capabilities?.drive?.reason || "Checking Drive availability…",
    uploadReason: capabilities?.upload?.reason || "Checking upload availability…",
    pending,
    resultHref: job?.status === "completed" ? "/training" : null,
  };
}

export function archiveProgress(job) {
  const total = Math.max(0, Number(job?.objects_total) || 0);
  const imported = Math.max(0, Number(job?.objects_imported) || 0);
  const skipped = Math.max(0, Number(job?.objects_skipped) || 0);
  const failed = Math.max(0, Number(job?.objects_failed) || 0);
  const reportedProcessed = Math.max(0, Number(job?.objects_processed) || 0);
  const processed = Math.min(
    total || Number.MAX_SAFE_INTEGER,
    Math.max(reportedProcessed, imported + skipped + failed),
  );
  const activities = Math.max(0, Number(job?.activities) || 0);
  const percent = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : null;

  if (job?.status === "completed") {
    return {
      processed: total || processed,
      total,
      percent: 100,
      activities,
      label: "Import complete",
      detail: total
        ? `${total} file${total === 1 ? "" : "s"} checked · ${activities} activit${activities === 1 ? "y" : "ies"} processed.`
        : `${activities} activit${activities === 1 ? "y" : "ies"} processed.`,
    };
  }

  if (job?.status === "failed") {
    return {
      processed,
      total,
      percent,
      activities,
      label: "Import stopped",
      detail: total
        ? `${processed} of ${total} files checked before the import stopped.`
        : "The import stopped before progress could be completed.",
    };
  }

  if (total > 0) {
    return {
      processed,
      total,
      percent,
      activities,
      label: `Importing: ${processed} of ${total} files checked`,
      detail: activities
        ? `${activities} activit${activities === 1 ? "y" : "ies"} processed so far.`
        : "No activities have been added from the checked files yet.",
    };
  }

  return {
    processed,
    total,
    percent,
    activities,
    label: job?.status === "processing" ? "Preparing import progress…" : "Import queued",
    detail: "Waiting for the worker to report the first checkpoint.",
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
