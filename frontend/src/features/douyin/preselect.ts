/** 抖音发布页的 URL 预选参数解析（来自剪辑工坊「用于抖音发布」）。 */
export function readDouyinPreselect(params: URLSearchParams): {
  media: string | null;
  title: string | null;
} {
  const media = params.get("media");
  if (!media) {
    return { media: null, title: null };
  }
  return { media, title: params.get("title") };
}
