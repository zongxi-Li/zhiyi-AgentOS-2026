export interface TranscriptBlock {
  id: string;
  kind: 'text' | 'reasoning' | 'tool' | 'status';
  state: string;
  text?: string;
  callId?: string;
  toolName?: string;
  attemptId?: string;
  truncated?: boolean;
}
export interface StreamEvent {
  event: string;
  requestId?: string;
  sequence?: number;
  data: Record<string, any>;
}
export interface ResponseTimings {
  profileResolveMs?: number;
  catalogBuildMs?: number;
  providerAdapterMs?: number;
  httpClientBuildMs?: number;
  agentConstructionMs?: number;
  journalOpenMs?: number;
  journalReadMs?: number;
  agentBuildMs?: number;
  contextMeasureMs?: number;
  contextProjectionMs?: number;
  contextSummaryMs?: number;
  sdkRequestBuildMs?: number;
  firstProviderHeadersMs?: number;
  firstProviderFirstByteMs?: number;
  browserFirstReceiveMs?: number;
  browserFirstFrameMs?: number;
  gatewayPrepareMs?: number;
  contextPreparationMs?: number;
  providerHeadersMs?: number;
  providerFirstByteMs?: number;
  providerConnectMs?: number;
  providerTlsMs?: number;
  providerUploadMs?: number;
  providerHeaderWaitMs?: number;
  firstReasoningMs?: number;
  firstContentMs?: number;
}
export interface WorkingContext {
  inputTokens?: number; outputTokens?: number; actualInputTokens?: number; fixedTokens?: number;
  workingSetTriggerTokens?: number; workingSetTargetTokens?: number; hardInputLimit?: number;
  protectedTokens?: number; targetReachable?: boolean;
  summaryCalls?: number; summaryLatencyMs?: number; pruneLatencyMs?: number; prunedChars?: number;
  tokenMethod?: string; status?: string; failureCode?: string; softOverBudget?: boolean; failed?: boolean;
}
export interface ContextUsage {
  usedTokens: number | null;
  maxTokens: number;
  measurement: 'provider' | 'upper-bound' | 'unknown';
  source: 'model' | 'prepared' | 'compaction';
  confirmedTokens?: number;
  projectionVersion?: number;
}
export function contextUsage(value: unknown): ContextUsage | undefined;
export function workingContext(value: unknown): WorkingContext | undefined;
export function mergeResponseTimings(target: ResponseTimings, source: unknown): ResponseTimings;
export function applyTranscript(blocks: TranscriptBlock[], event: StreamEvent): TranscriptBlock[];
export function restoreTranscript(value: unknown): TranscriptBlock[];
export function createStreamBatcher<T extends StreamEvent>(emit: (event: T) => void,
  options?: { delayMs?: number; maxChars?: number; maxEvents?: number }): {
  accept(event: T): void; flush(): void; dispose(): void;
};
