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
  gatewayPrepareMs?: number;
  contextPreparationMs?: number;
  providerHeadersMs?: number;
  providerFirstByteMs?: number;
  firstReasoningMs?: number;
  firstContentMs?: number;
}
export function mergeResponseTimings(target: ResponseTimings, source: unknown): ResponseTimings;
export function applyTranscript(blocks: TranscriptBlock[], event: StreamEvent): TranscriptBlock[];
export function restoreTranscript(value: unknown): TranscriptBlock[];
export function createStreamBatcher<T extends StreamEvent>(emit: (event: T) => void,
  options?: { delayMs?: number; maxChars?: number; maxEvents?: number }): {
  accept(event: T): void; flush(): void; dispose(): void;
};
