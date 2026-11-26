// Public query shapes consumed by the workbench. Python remains the state and execution authority.
type Row = Record<string, unknown>;
const row = (value: unknown): Row => value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const rows = <T>(value: unknown, mapper: (source: Row) => T): T[] => list(value).map(value => mapper(row(value)));
const pick = (source: unknown, fields: string): Row => {
  const value = row(source);
  return Object.fromEntries(fields.split(' ').map(key => [key, value[key] ?? null]));
};
const scalar = (value: unknown) => ['string', 'boolean', 'number'].includes(typeof value) ? String(value) : null;
const strings = (value: unknown) => list(value).filter((item): item is string => typeof item === 'string');
const producerFields = (value: unknown) => Object.entries(row(value)).map(([producerId, fields]) => ({ producerId, fields: strings(fields) }));
const lineage = (value: unknown) => pick(value, 'parentRunId sourceRunId rerunReason supersedesRunId supersededByRunId');
const graphDisplay = (value: unknown) => {
  const source = row(value);
  const semanticKey = typeof source.semanticTaskKey === 'string' && source.semanticTaskKey.length
    ? source.semanticTaskKey : typeof source.taskPlanKey === 'string' ? source.taskPlanKey : null;
  return { ...pick(source, 'taskId logicalRole endpointRole agentName allowedSkills dependencyKeys displayOrder'), semanticTaskKey: semanticKey };
};
const graphNode = (source: Row) => ({ ...pick(source, 'nodeId nodeType name description goal agentName capability controlType'), display: graphDisplay(source.metadata) });
const graphEdge = (source: Row) => ({ ...pick(source, 'edgeId sourceId targetId edgeType activation condition'), display: graphDisplay(source.metadata) });
function graph(value: unknown): Row {
  const source = row(value);
  return { ...pick(source, 'runId graphId missionId blueprintId historical taskPlanVersion objective complexityLevel'), graphVersion: source.graphVersion ?? source.version ?? null,
    nodes: rows(source.nodes, graphNode), edges: rows(source.edges, graphEdge),
    ...(source.historical === true ? {} : {
      completedStepIds: strings(source.completedStepIds), activeStepIds: strings(source.activeStepIds), skippedStepIds: strings(source.skippedStepIds),
      workspaceReview: copilotWorkspaceReview(source.workspaceReview) }) };
}

function graphVersions(source: Row): Row {
  return { ...pick(source, 'runId graphId currentBlueprintId currentGraphVersion'),
    items: rows(source.items, item => {
      const inherited = row(item.inherited);
      return { ...pick(item, 'blueprintId graphId graphVersion taskPlanVersion current status createdAt predecessorBlueprintId reason activationId handoffId'),
        patch: item.patch == null ? null : {
          ...pick(item.patch, 'patchId addedEdgeCount removedEdgeCount'),
          addedNodeIds: strings(row(item.patch).addedNodeIds), updatedNodeIds: strings(row(item.patch).updatedNodeIds),
          removedNodeIds: strings(row(item.patch).removedNodeIds) },
        inherited: { completedStepIds: strings(inherited.completedStepIds), skippedStepIds: strings(inherited.skippedStepIds),
          attemptIds: strings(inherited.attemptIds),
          outputRefs: Object.fromEntries(Object.entries(row(inherited.outputRefs)).filter(([, value]) => typeof value === 'string')) } };
    }),
    proposals: [] };
}
const actionCapabilities = (value: unknown): unknown => value == null ? null : {
  ...pick(value, 'schemaVersion missionId runId runtimeRevision status isExecutionActive isSuperseded canInspect canDiscuss canCancel canReview canExecuteFormalAction formalActions canResolveToolApproval canAnswerPlanner canCollaborate canSetPermission canRetrySuccessor canRecoverCurrentRun retryMode retryStepId canRerunSuccessor canDecideRevision canApplyRevision canDelete'),
  lineage: lineage(row(value).lineage), unavailableReasons: rows(row(value).unavailableReasons, source => pick(source, 'action code')),
};

function run(source: Row): Row {
  const state = row(source.executionState);
  const refs = row(state.outputRefs);
  const summaries = row(state.outputSummaries);
  const formal = row(source.formalControl);
  return {
    ...pick(source, 'runId missionId title workflowId domain source runtimeEngine status lifecyclePhase lifecycleMessage currentStepId outputRef runtimeRevision createdAt updatedAt startedAt'),
    completedStepIds: strings(source.completedStepIds), activeStepIds: strings(source.activeStepIds), skippedStepIds: strings(source.skippedStepIds),
    steps: rows(source.steps, step => pick(step, 'stepId name agentName capability status attempt retryCount reviewRequired outputRef outputSummary startedAt completedAt')),
    ...pick(state, 'graphVersion planningDiversity planningSeed plannerAlgorithmVersion planningCandidateCount selectedPlanningVariantId'),
    review: pick(state.reviewPayload, 'subjectType subjectId controlId stepId reasonCode iteration approvals quorum accepted strategy'),
    lineage: lineage(state), outputs: Object.entries(refs).map(([stepId, outputRef]) => ({ stepId, outputRef, summary: summaries[stepId] ?? null })),
    formalControl: source.formalControl == null ? null : { ...pick(formal, 'status executionAuthorized permitIssued dispatchEligible dispatchEnabled commitId commitmentRevision materializationId activationId graphId graphVersion handoffId handoffStatus permitId permitStatus'),
      dispatch: formal.dispatch == null ? null : pick(formal.dispatch, 'dispatchId runId permitId graphVersion status') },
    failureCode: row(source.error).code ?? null,
    actionCapabilities: actionCapabilities(source.actionCapabilities),
  };
}

const missionRun = (source: Row) => pick(source, 'runId missionId status graphVersion startedAt finishedAt createdAt updatedAt');
const task = (source: Row) => ({ ...pick(source, 'taskId missionId semanticTaskKey parentTaskId title objective status'), constraintCount: list(source.constraints).length });

function executionTree(source: Row): Row {
  const blueprint = row(source.blueprint);
  const operational = row(source.operational);
  const nodes = rows(source.nodes, source => ({ task: task(row(source.task)), acgNodeId: source.acgNodeId ?? null,
    attempts: rows(source.attempts, source => {
      const binding = row(source.executionBinding);
      return { attempt: pick(source.attempt, 'attemptId runId taskId status attemptNumber startedAt finishedAt failureReason'),
        executions: rows(source.executions, source => pick(source, 'stepExecutionId runId taskId attemptId status startedAt finishedAt')),
        resourceUse: source.executionBinding == null ? null : { ...pick(binding, 'resourceId agentId modelId acgNodeId'), deploymentTier: row(binding.metadata).deploymentTier ?? null } };
    }) }));
  const attemptNumbers = new Map<string, number>();
  for (const node of list(source.nodes)) for (const attempt of list(row(node).attempts)) {
    const value = row(row(attempt).attempt);
    if (typeof value.attemptId === 'string') attemptNumbers.set(value.attemptId, Number(value.attemptNumber ?? 0));
  }
  const lifecycles = [...list(operational.nodeExecutions)].map(row).sort((left, right) => {
    const difference = (attemptNumbers.get(String(left.attemptId)) ?? 0) - (attemptNumbers.get(String(right.attemptId)) ?? 0);
    if (difference) return difference;
    const a = list(left.loopPath), b = list(right.loopPath);
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      const delta = Number(a[i] ?? -1) - Number(b[i] ?? -1);
      if (delta) return delta;
    }
    return String(left.executionInstanceId ?? '').localeCompare(String(right.executionInstanceId ?? ''));
  }).map((value, displayOrder) => ({ ...pick(value, 'stepId attemptId phase failureCode'), displayOrder }));
  return { run: missionRun(row(source.run)), graph: { ...graph(blueprint.graph), ...pick(blueprint, 'graphId missionId'), graphVersion: blueprint.version ?? null },
    nodes, lineage: lineage(operational.lineage), lifecycles };
}

function workspace(source: Row): Row {
  const mission = pick(source.mission, 'missionId goal description status createdAt updatedAt');
  const summary = (source: Row): Row => ({ ...pick(source, 'runId status parentRunId sourceRunId createdAt completedAt isActive'), actionCapabilities: actionCapabilities(source.actionCapabilities) });
  const activeRun = source.activeRun == null ? null : summary(row(source.activeRun));
  const attachments = rows(source.inputAttachments, source => pick(source, 'attachmentId originalFilename mimeType extension sizeBytes sha256 status extractedContentRef characterCount parser parseError createdAt updatedAt'));
  const entries = rows(source.entries, source => {
    const metadata = row(source.metadata);
    const converted = pick(metadata, 'outputRef outputSummary runtimeStatus taskPlanVersion');
    for (const key of ['artifactKind', 'artifact_kind', 'schema', 'schemaName', 'confidence', 'agentName', 'agent']) {
      converted[key] = ['agentName', 'agent'].includes(key) && typeof metadata[key] === 'boolean' ? null : scalar(metadata[key]);
    }
    for (const key of ['evidenceRefs', 'evidence_refs', 'upstreamInputs', 'sourceStepIds', 'traceLinks', 'traceRefs']) {
      converted[key] = Array.isArray(metadata[key]) ? list(metadata[key]).map(scalar).filter(value => value !== null) : null;
    }
    return { ...pick(source, 'entryId kind name group title parentEntryId displayOrder semanticTaskKey artifactKey taskId logicalRole objective dependencyKeys attemptCount latestAttemptId artifactCount artifactId contentRef artifactType mediaType checksum attemptId acgNodeId disposition sourceRunId identityQuality createdAt runId status blueprintId graphId graphVersion parentRunId completedAt isActive content'), metadata: converted } as Row;
  });
  const lines = [`# ${mission.goal}`, ...(mission.description ? ['', String(mission.description)] : []), '', '## Current Run',
    ...(activeRun ? [`- Run: \`${activeRun.runId}\``, `- Status: \`${activeRun.status}\``, ...(activeRun.completedAt ? [`- Completed: \`${activeRun.completedAt}\``] : [])] : ['No Run has been created.']),
    '', '## Input attachments', ...(attachments.length ? attachments.map(value => `- **${value.originalFilename}** (\`${value.attachmentId}\`) - ${value.status}, ${value.sizeBytes} bytes, \`${value.sha256}\``) : ['No input attachments.'])];
  const tasks = entries.filter(value => value.kind === 'task');
  if (tasks.length) lines.push('', '## Planned steps', ...tasks.map(value => `- **${value.name}** (\`${value.semanticTaskKey}\`)${value.objective ? `: ${value.objective}` : ''}`));
  for (const entry of entries) if (entry.entryId === 'overview:mission.md' && entry.kind === 'virtual_document') entry.content = lines.join('\n') + '\n';
  const diagnosticKeys: Record<string, string> = { RUN_DELIVERABLE_MISSING: 'runId', GRAPH_TASK_NOT_FOUND: 'acgNodeId taskId', TASK_PLAN_TASK_NOT_FOUND: 'runId semanticTaskKey', LEGACY_ARTIFACT_IDENTITY: 'count', PLAN_SNAPSHOT_UNRESOLVED: 'runId taskPlanVersion', PLANNING_PROJECTION_PENDING: 'runtimeStatus lifecyclePhase errorCode' };
  return { mission, activeRun, ...pick(source, 'projectionRevision projectionSchemaVersion'),
    activeGraph: source.activeGraph == null ? null : { ...graph(source.activeGraph), taskPlanVersion: row(source.activeGraph).taskPlanVersion ?? null },
    runs: rows(source.runs, summary), entries,
    graphNodes: rows(source.graphNodes, source => pick(source, 'acgNodeId nodeType name semanticTaskKey taskId identityQuality displayOrder status attemptId artifactCount artifactIds')),
    inputAttachments: attachments,
    diagnostics: rows(source.diagnostics, source => ({ ...pick(source, 'code message severity'), details: diagnosticKeys[String(source.code)] ? pick(source.details, diagnosticKeys[String(source.code)]!) : {} })),
  };
}

function content(value: unknown): Row {
  if (value === null || value === undefined) return { kind: 'null' };
  if (typeof value === 'string') return { kind: 'string', text: value };
  if (typeof value === 'boolean') return { kind: 'boolean', bool: value };
  if (typeof value === 'number') return { kind: 'number', number: value };
  if (Array.isArray(value)) return { kind: 'list', items: value.map(content) };
  return { kind: 'object', members: Object.entries(row(value)).map(([name, value]) => ({ name, value: content(value) })) };
}

function resourceCatalog(source: Row): Row {
  return { total: source.total, items: rows(source.items, item => {
    const profile = row(item.profile);
    return { snapshotVersion: item.snapshotVersion,
      profile: { ...pick(profile, 'resourceId resourceType deploymentTier capabilities domains version enabled capacity privacyLevel dataZone location ownerScope modelIds runtimeKind displayName nodeId trust hostRuntimeId provider sourceType adapter model contextWindowTokens maxOutputTokens'),
        labels: Object.entries(row(profile.labels)).filter(([, value]) => typeof value === 'string').map(([key, value]) => ({ key, value })),
        costMetadata: Object.entries(row(profile.costMetadata)).filter(([, value]) => typeof value === 'number').map(([key, value]) => ({ key, value })),
        computeCapacity: profile.computeCapacity == null ? null : pick(profile.computeCapacity, 'cpuCores memoryMb gpuType gpuMemoryMb bandwidthMbps') },
      snapshot: pick(item.snapshot, 'healthStatus utilization latencyMs availableSlots reliability observedAt') };
  }) };
}

const stringOrNull = (value: unknown): string | null => typeof value === 'string' ? value : null;
const numberOrNull = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;

function copilotInitialPlan(value: unknown): Row | null {
  if (value == null) return null;
  const source = row(value);
  return {
    planVersion: numberOrNull(source.planVersion), commitId: stringOrNull(source.commitId),
    commitmentRevision: numberOrNull(source.commitmentRevision), objective: stringOrNull(source.objective),
    constraints: strings(source.constraints), expectedArtifacts: strings(source.expectedArtifacts),
    relations: list(source.relations).map(row)
      .filter(relation => typeof relation.sourceKey === 'string' && typeof relation.targetKey === 'string'
        && (relation.relationType === 'depends_on' || relation.relationType === 'parent'))
      .map(relation => pick(relation, 'sourceKey targetKey relationType')),
    tasks: rows(source.tasks, task => ({
      key: stringOrNull(task.key), title: stringOrNull(task.title), objective: stringOrNull(task.objective),
      rationale: stringOrNull(task.rationale), acceptanceCriteria: strings(task.acceptanceCriteria),
      sourceRefs: strings(task.sourceRefs), capabilities: strings(task.capabilities),
    })),
  };
}

function copilotToolActivity(source: Row): Row {
  const decision = row(source.approvalDecision);
  return { ...Object.fromEntries('executionId tool status stepId attemptId receiptRef createdAt'.split(' ')
    .map(key => [key, stringOrNull(source[key])])),
    ...(['policy', 'user'].includes(String(decision.source)) ? { approvalDecision: {
      ...pick(decision, 'source decidedAt policyRevision'),
      actor: decision.actor == null ? null : pick(decision.actor, 'userId tenantId'),
    } } : {}) };
}

function taskOperatorPolicy(value: unknown): Row | null {
  if (value == null) return null;
  const source = row(value);
  return { ...pick(source, 'missionId permission approvalMode policyRevision updatedAt operationId effectiveApprovalMode effectiveScopeMatch'),
    workspaceScope: source.workspaceScope == null ? null : pick(source.workspaceScope, 'workspaceId grantId resourceId'),
    updatedBy: source.updatedBy == null ? null : pick(source.updatedBy, 'userId tenantId') };
}

function copilotReview(value: unknown): Row | null {
  if (value == null) return null;
  const source = row(value);
  // Keep the diagnostic display contract explicit. Runtime snapshots and
  // continuation patches never cross this gateway whitelist.
  return pick(source, 'subjectId subjectType reason reasonCode kind displayReason errorCode errorType canApprove decisionRejected expectedRunUpdatedAt');
}

function copilotPlanningProgress(value: unknown): Row | null {
  if (value == null) return null;
  const source = row(value);
  return { ...pick(source, 'kind status message observationId errorCode'),
    ...(typeof source.reason === 'string' ? { reason: source.reason } : {}),
    ...(typeof source.errorType === 'string' ? { errorType: source.errorType } : {}),
    ...(typeof source.canApprove === 'boolean' ? { canApprove: source.canApprove } : {}) };
}

function copilotWorkspaceReview(value: unknown): Row | null {
  if (value == null) return null;
  const source = row(value);
  const gaps = row(source.gaps);
  return {
    ...pick(source, 'schemaVersion round graphVersion status'),
    gaps: { ...pick(gaps, 'missingReadCount missingListingCount unsupportedEntryCount'),
      missingReads: strings(gaps.missingReads), missingListings: strings(gaps.missingListings),
      unsupportedEntries: strings(gaps.unsupportedEntries) },
    rounds: rows(source.rounds, round => ({ ...pick(round, 'round graphVersion action reason observationRef decisionRef patchRef'),
      stepIds: strings(round.stepIds), addedStepIds: strings(round.addedStepIds), traceRefs: strings(round.traceRefs) })),
  };
}

function copilot(source: Row): Row {
  return { ...pick(source, 'runId missionId latestRunId taskPermission approvalMode policyRevision status revision modelAvailable defaultModelId permissions'),
    approvalPolicy: taskOperatorPolicy(source.approvalPolicy),
    initialPlan: copilotInitialPlan(source.initialPlan), toolActivity: rows(source.toolActivity, copilotToolActivity),
    workspaceReview: copilotWorkspaceReview(source.workspaceReview),
    planningProgress: copilotPlanningProgress(source.planningProgress),
    question: source.question == null ? null : pick(source.question, 'questionId prompt choices'),
    humanAnswers: rows(source.humanAnswers, source => pick(source, 'questionId sourceRunId prompt answer operationId answeredAt')),
    review: copilotReview(source.review),
    exchanges: rows(source.exchanges, source => ({ ...pick(source, 'operationId user assistant createdAt observedRevision permission modelId requestedModelId reasoningEffort sourceRunId'),
      action: source.action == null ? null : pick(source.action, 'kind stepId expectedRevision retryMode capabilityCatalogRevision executionEnvironmentChanged executeStepIds reusedStepIds content'),
      receipt: source.receipt == null ? null : pick(source.receipt, 'proposalId runId kind status executeStepIds reusedStepIds') })),
    decision: source.decision == null ? null : pick(source.decision, 'observationId action reason'),
    steps: rows(source.steps, source => pick(source, 'stepId name status')),
    models: rows(source.models, source => pick(source, 'id provider model reasoningEfforts defaultReasoningEffort')) };
}

const traceFamilies: Record<string, string> = {
  step_scheduled: 'stepIds', step_succeeded: 'outputSummary modelInvocations runtimeEvents toolCalls provenanceEvents communicationReads memoryAccess memoryEvent',
  model_called: 'provider model latencyMs promptVersion promptTemplateHash promptInstanceHash stablePrefixHash schemaHash kernelVersion preset presetVersion capabilityId capabilityPolicyVersion requestProtocolVersion outputProtocolVersion promptRendererVersion requestType providerFamily modelVersion streaming trustSummary usage finishReason capability outputPolicy requestedOutputTokens effectiveOutputTokens effectiveReason outputExhausted partIndex callChainId',
  tool_called: 'tool name status latencyMs errorCode',
  data_consumed: 'policyId read readCount retrievalMode hitRefs write written readTypes writeType limit tokenBudget tokensUsed requireAudit runId consumerStepId producerStepId outputRef fields tokens channel eventId producerStepIds producerEventIds fieldsByProducer consumedFields tokensDelivered tokensAvailable savingRatio checksum contractStatus eventHash interactionId evidenceRefs',
  data_produced: 'eventId producerStepId fieldNames checksum tokenSize evidenceRefs eventHash runId stepId summary metrics decision relations kind phaseId capsuleRef sourceMemoryRefs tokenCount',
  runtime_event_classified: 'runtimeEvent attemptId sequence timestamp payload',
  run_recovered: 'failedResources retryStepIds sourceRunId failedStepId reusedStepIds resumeStepIds reason mode',
  run_failed: 'errorCode code message', review_required: 'auditOutcome',
  review_decided: 'subjectType decision operationId reviewer comment deferredMemoryDiscarded runId stepId expectedRunUpdatedAt expectedStepStatus',
  runtime_patch_applied: 'patchType previousAgentId agentId reason', graph_patch_applied: 'baseGraphVersion graphVersion newRunId',
};
const plannerTraceKeys = 'planningProgress category stage kind attempt retryCount taskCount dependencyCount nodeCount edgeCount constraintCount requiredCapabilityCount expectedArtifactCount profileId runId mode timeoutSeconds errorCode code message selectedVariant selectionSeed algorithmVersion presetVersion fallbackReason candidateCount selectedVariantId selectedCapabilities selectionReasons stochasticFallback taskPlanVersion taskNodeCount notes scanned protected deleted';
traceFamilies.task_status_changed = plannerTraceKeys;
traceFamilies.stochastic_planning_fallback = plannerTraceKeys;

function trace(source: Row): Row {
  const publicFields = new Set('status tool name model provider finishReason latencyMs producerStepId producerStepIds consumerStepId interactionId outputRef channel fields consumedFields tokens tokensDelivered contractStatus errorCode code message summary reason graphVersion attemptId planningProgress category stage kind attempt retryCount taskCount dependencyCount nodeCount edgeCount constraintCount requiredCapabilityCount expectedArtifactCount timeoutSeconds failedResources retryStepIds'.split(' '));
  return { ...pick(source, 'runId missionId workflowId domain status eventCount'), events: rows(source.events, source => {
    const raw = row(source.payload), payload: Row = {}, details: unknown[] = [];
    for (const key of (traceFamilies[String(source.eventType)] ?? '').split(' ')) {
      const value = raw[key];
      if (value == null) continue;
      if (key === 'fieldsByProducer') { payload.producerFields = producerFields(value); continue; }
      if (publicFields.has(key)) payload[key] = value;
      const kind = value === '[redacted]' ? 'redacted' : value === '[truncated]' ? 'truncated' : Array.isArray(value) ? 'list' : typeof value;
      details.push({ key, value: typeof value === 'string' ? value : JSON.stringify(value), kind });
    }
    payload.details = details;
    return { ...pick(source, 'eventId runId stepId agentName eventType observation durationMs createdAt'), payload };
  }) };
}

const artifact = (source: Row) => pick(source, 'manifestId kind mediaType checksum byteLength fragmentCount estimatedTokens sealed createdAt artifactId missionId originRunId taskId semanticTaskKey artifactKey acgNodeId producerAttemptId name artifactType contentRef runId disposition sourceRunId');
const provenancePayload = (source: Row) => ({ ...pick(source, 'eventId runId missionId attempt producerStepId agentName fieldNames tokenSize evidenceRefs checksum previousHash eventHash createdAt consumerStepId consumerAgentName producerStepIds producerEventIds consumedFields tokensDelivered tokensAvailable savingRatio contractStatus interactionId edgeIds producerAgentNames'), producerFields: producerFields(source.fieldsByProducer) });

/** Route projection keeps the established UI wire contract while dropping runtime snapshots. */
export function projectAgentOsResponse(path: string, value: unknown): unknown {
  const source = row(value), suffix = path.replace(/^\/ai\/agentos\/v2/u, '');
  if (suffix === '/runs') return { ...pick(source, 'total page pageSize'), items: rows(source.items, run) };
  if (/^\/runs\/[^/]+$/u.test(suffix)) return { ...run(source), initialPlan: copilotInitialPlan(source.initialPlan) };
  if (/^\/runs\/[^/]+\/plan$/u.test(suffix)) return { runId: stringOrNull(source.runId), plan: copilotInitialPlan(source.plan) };
  if (/^\/runs\/[^/]+\/storage$/u.test(suffix)) return {
    ...pick(source, 'runId records measuredRecords unmeasuredRecords logicalBytes largestBytes encodedBinaryBytes encodedBinaryRatio uniquePayloadBytes duplicatePayloadBytes growthBytes externalStoredBytes externalFiles duplicateBodyBytes'),
    states: pick(source.states, 'online archived deletable'),
    largestRecord: source.largestRecord == null ? null : pick(source.largestRecord, 'reference bytes contentType'),
  };
  if (/\/execution-tree$/u.test(suffix)) return executionTree(source);
  if (/\/workspace$/u.test(suffix)) return workspace(source);
  if (/^\/runs\/[^/]+\/graph\/versions$/u.test(suffix)) return graphVersions(source);
  if (/\/graph$/u.test(suffix)) return graph(source);
  if (suffix === '/missions') return { ...pick(source, 'total page pageSize source'), items: rows(source.items, source => pick(source, 'missionId title description status latestRunId latestRunStatus createdAt updatedAt runCount')) };
  if (/^\/missions\/[^/]+$/u.test(suffix)) return { mission: pick(source.mission, 'missionId goal description status createdAt updatedAt'), tasks: rows(source.tasks, task),
    graphs: rows(source.blueprints, source => pick(source, 'graphId version createdAt')), runs: rows(source.runs, missionRun) };
  if (/^\/missions\/[^/]+\/runs$/u.test(suffix)) return { missionId: source.missionId, runs: rows(source.runs, missionRun) };
  if (/\/workspace\/files$/u.test(suffix)) return { ...pick(source, 'workspaceRoot path'), entries: rows(source.entries, source => pick(source, 'name path type')) };
  if (/\/workspace\/file$/u.test(suffix)) return pick(source, 'workspaceRoot path content version');
  if (/\/history-config$/u.test(suffix)) {
    const input = row(source.input);
    return { ...pick(source, 'runId title reviewMode enabledPluginIds'), input: { ...pick(input, 'taskGoal userIntent materialText contractText materialIds constraints expectedArtifacts planningMode planningDiversity capabilityProfile thinkingMode reasoningEffort planningSeed webSearchEnabled'),
      pluginData: Object.entries(row(input.pluginData)).map(([pluginId, fields]) => ({ pluginId, entries: Object.entries(row(fields)).filter(([, value]) => ['string', 'boolean', 'number'].includes(typeof value)).map(([name, value]) => ({ name, [typeof value === 'string' ? 'text' : typeof value === 'boolean' ? 'bool' : 'number']: value })) })) } };
  }
  if (suffix === '/resources') return resourceCatalog(source);
  if (suffix === '/nodes') return { total: source.total, items: rows(source.items, source => ({ snapshotVersion: source.snapshotVersion, healthStatus: row(source.health).status,
    profile: { ...pick(source.profile, 'nodeId displayName placement trust ownerScope enabled provider sourceType adapter'), computeCapacity: row(source.profile).computeCapacity == null ? null : pick(row(source.profile).computeCapacity, 'cpuCores memoryMb gpuType gpuMemoryMb bandwidthMbps') } })) };
  if (/\/resources\/[^/]+\/credential$/u.test(suffix)) return pick(source, 'resourceId credentialId createdAt');
  if (/\/artifacts$/u.test(suffix)) return { ...pick(source, 'runId total'), items: rows(source.items, artifact) };
  if (/\/artifacts\/[^/]+$/u.test(suffix)) return artifact(source);
  if (/\/fragments$/u.test(suffix)) return { manifest: artifact(row(source.manifest)), nextCursor: source.nextCursor ?? null,
    items: rows(source.items, source => pick(source, 'fragmentId manifestId sequence checksum byteLength estimatedTokens sourceRefs constraintRefs verificationStatus complete content')) };
  if (/\/outputs\/[^/]+$/u.test(suffix)) return { ...pick(source, 'runId outputRef'), content: content(source.content) };
  if (/\/legacy-outputs$/u.test(suffix)) return { runId: source.runId, items: rows(source.items, source => ({ ...pick(source, 'stepId name status'), content: content(source.content) })) };
  if (/\/copilot$/u.test(suffix)) return copilot(source);
  if (/\/trace$/u.test(suffix)) return trace(source);
  if (/\/checkpoints$/u.test(suffix)) return { ...pick(source, 'runId total'), items: rows(source.items, source => pick(source, 'checkpointId version canResume')) };
  if (/\/provenance$/u.test(suffix)) return { ...pick(source, 'runId integrityStatus schemaVersion legacy'),
    ...(source.events ? { events: rows(source.events, source => ({ eventType: source.eventType, payload: provenancePayload(row(source.payload)) })) }
      : { productions: rows(source.productions, provenancePayload), consumptions: rows(source.consumptions, provenancePayload), interactions: rows(source.interactions, provenancePayload) }) };
  if (/\/memory-events$/u.test(suffix)) return { ...pick(source, 'runId total'), items: rows(source.items, source => ({
    ...pick(source, 'kind stepId createdAt'), ...pick(source, source.kind === 'memory_access' ? 'retrievalMode hitRefs fallbackReason' : source.kind === 'memory_event' ? 'summary' : source.kind === 'phase_capsule' ? 'phaseId sourceMemoryRefs tokenCount' : 'kind'),
    ...(source.kind === 'memory_event' ? { metrics: pick(source.metrics, 'fieldCount evidenceCount modelInvocationCount toolCallCount') } : {}) })) };
  return value;
}
