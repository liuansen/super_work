#!/usr/bin/env bash
# ==============================================================================
# 从 git 历史中彻底移除凭据文件（不可逆操作，执行前请阅读全部说明）
# ==============================================================================
#
# 背景：data/spider_xhs.db-wal / -shm 曾被提交，内含真实小红书账号数据与
# xsec_token；.local/ 是 285 个重复的上游快照文件（含 2MB tar.gz）。
# 它们已从当前索引移除（git rm --cached），但**历史提交里仍然存在**。
#
# 前置条件（缺一不可）：
#   1. 工作区干净：git status 无输出。若有未提交改动，先提交或 stash
#      （git filter-branch 拒绝在有未提交改动时运行）。
#   2. 已确认该仓库若推过远端，所有人都知道需要重新 clone：
#      改写后所有提交 SHA 都会变化，必须 git push --force --all。
#   3. 已备份仓库目录（cp -r 或 git clone --mirror 到仓库外）。
#
# 用法：
#   bash scripts/purge_sensitive_history.sh
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> 检查工作区状态"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "错误：工作区有未提交改动，请先提交或 stash 后再执行。" >&2
  exit 1
fi

echo "==> 创建安全备份分支（万一需要回滚）"
git branch -f backup/pre-history-clean HEAD

echo "==> 记录改写前提交"
git log --oneline -5

echo "==> 改写历史（移除 .local/ 与 data/*.db-{wal,shm}）"
git filter-branch -f --index-filter '
  git rm -r --cached --ignore-unmatch --quiet \
    .local \
    data/spider_xhs.db-wal \
    data/spider_xhs.db-shm
' --prune-empty HEAD

echo "==> 清理旧引用与对象"
git for-each-ref --format='%(refname)' refs/original | while read -r ref; do
  git update-ref -d "$ref"
done
git reflog expire --expire=now --all
git gc --prune=now --aggressive

echo "==> 校验：历史中不应再出现敏感文件"
if git log --all --oneline -- data/spider_xhs.db-wal data/spider_xhs.db-shm .local | grep -q .; then
  echo "失败：仍能在历史中找到目标文件，请检查输出。" >&2
  exit 1
fi
echo "OK：历史中已无敏感文件"

echo "==> 下一步"
echo "1) 若仓库有远端：git push --force --all && git push --force --tags"
echo "2) 通知所有协作者重新 clone（旧克隆仍持有原始对象）"
echo "3) 到小红书作废历史中泄露过的 xsec_token / 重新登录相关账号"
echo "4) 确认无误后可删除备份分支：git branch -D backup/pre-history-clean"
