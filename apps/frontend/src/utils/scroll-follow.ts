// 聊天时间线跟随迟滞：只有用户主动上滚脱离，只有真正触底恢复；
// 流式增长落在滚动事件之间时位置短暂偏离底部，不视为「用户已离开」。
export function nextFollowState(isNearBottom: boolean, scrollTop: number, lastScrollTop: number,
  distanceFromBottom: number, tolerance = 24): boolean {
  if (scrollTop < lastScrollTop - 2) return false
  if (isNearBottom) return true
  return distanceFromBottom < tolerance
}
