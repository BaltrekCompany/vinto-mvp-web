// Pure, offline planning for PostgreSQL <=17 connection-logging restore.
// Does not execute SQL, access credentials or connect to any database.
// sourcefileKind must be verified PRIVATELY from pg_settings.sourcefile.
// Never publish the source filename or raw connection logs.
export function selectRestorePlan(input) {
  const {
    serverVersionNum, setting, context, vartype,
    source, sourcefileKind, pendingRestart,
  } = input || {};
  if (!Number.isInteger(serverVersionNum) ||
      serverVersionNum < 140000 || serverVersionNum >= 180000)
    return { eligible: false, reason: "UNSUPPORTED_PG_VERSION" };
  if (setting !== "off" || context !== "superuser-backend" ||
      vartype !== "bool" || pendingRestart !== false)
    return { eligible: false, reason: "GUC_BASELINE_NOT_SAFE" };
  if (source === "command line" || source === "override" ||
      source === "database" || source === "user" || source === "client")
    return { eligible: false, reason: "OVERRIDE_SOURCE_NOT_SAFE" };
  if (source === "default" && sourcefileKind === "none")
    return { eligible: true, restoreAction: "RESET_NEW_OVERRIDE", baseline: "off" };
  if (source === "configuration file" && sourcefileKind === "regular")
    return { eligible: true, restoreAction: "RESET_NEW_OVERRIDE", baseline: "off" };
  if (source === "configuration file" && sourcefileKind === "auto")
    return { eligible: true, restoreAction: "RESTORE_PRIOR_AUTO_VALUE", baseline: "off" };
  return { eligible: false, reason: "SOURCE_FILE_NOT_VERIFIED" };
}

export function startGatesSatisfied(evidence) {
  // This planner never grants permission to change PostgreSQL.
  // It describes which gates a future independent executor must require.
  return Boolean(evidence?.specificWriteApproval &&
    evidence?.preflightPass && evidence?.sourceFileKindVerified &&
    evidence?.logRouteVerified && evidence?.sourceFidelityPlan &&
    evidence?.retentionAndAccessPlan && evidence?.stopTimerInstalledAndTested &&
    evidence?.restoreModeRecorded && evidence?.serviceContinuityBaseline);
}
