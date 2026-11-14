import type { FastifyRequest } from 'fastify';
import { GatewayError, type PythonGateway } from './gateway.js';

export async function clearChatSession(gateway: PythonGateway, request: FastifyRequest, contextId: string) {
  const response = await gateway.request(`/ai/chat/sessions/${encodeURIComponent(contextId)}`, {
    identity: request.localIdentity!, method: 'DELETE',
  });
  if (!response.ok) throw new GatewayError(response.status, 'CHAT_SESSION_DELETE_FAILED');
  await response.arrayBuffer();
}
