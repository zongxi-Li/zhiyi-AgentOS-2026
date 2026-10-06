import type { Role } from '@/services/api/role'

// 内置角色（律师/教师/程序员/作家）已下线；知识图谱与 RAG 一律按角色 id（自定义角色）定位。
export function resolveKnowledgeRoleId(role?: Role | null): string | undefined {
  return role?.id
}
