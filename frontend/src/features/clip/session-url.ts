/**
 * 编辑器地址构造：令牌只放进 URL fragment（#…）。
 *
 * fragment 不会出现在服务器日志、Referer 头或网络抓包的请求行里，
 * 这是「令牌不得出现在查询参数/日志」契约的关键实现。
 */
export function buildEditorUrl(base: string, handoffToken: string, sessionId: number): string {
  const url = new URL(base);
  url.hash = new URLSearchParams({
    handoff: handoffToken,
    session: String(sessionId),
  }).toString();
  return url.toString();
}
