import { Navigate } from "react-router-dom";

/**
 * 兼容旧入口：视频工坊已升级为平台无关的「剪辑工坊」。
 * 保留原路径，直接跳到新应用，避免旧书签和菜单失效。
 */
export function XhsVideoStudioPage() {
  return <Navigate to="/clip?from=xhs" replace />;
}
