import { useRef } from "react";

/**
 * 列表请求竞态守卫。
 *
 * 快速切换筛选/翻页时，先发出的慢响应可能后到达并覆盖新数据。用法：
 *
 *   const request = useLatestRequest();
 *   const seq = request.begin();
 *   const data = await fetch();
 *   if (!request.isLatest(seq)) return;
 *   setData(data);
 *
 * 项目里已有若干手写 seq-ref 的页面（publish/library 详情），此 hook 是
 * 它们的通用版本，新代码统一使用，避免再出现未防护的列表。
 */
export function useLatestRequest() {
  const seqRef = useRef(0);

  return {
    begin(): number {
      seqRef.current += 1;
      return seqRef.current;
    },
    isLatest(seq: number): boolean {
      return seqRef.current === seq;
    },
  };
}
