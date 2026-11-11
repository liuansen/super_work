import {
  EditOutlined,
  ExperimentOutlined,
  LinkOutlined,
  PlusCircleOutlined,
  ReloadOutlined,
  RobotOutlined,
  SendOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { arrayMove } from "@dnd-kit/sortable";
import type { DragEndEvent } from "@dnd-kit/core";
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Divider,
  Form,
  Image,
  Input,
  message as antMessage,
  Row,
  Segmented,
  Space,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";

import { PageHeader } from "../../../components/layout/app-shell";
import {
  addDraftAsset,
  deleteDraft,
  deleteDraftAsset,
  fetchDraftAssets,
  fetchDrafts,
  fetchGeneratedImageAssets,
  fetchSavedNote,
  fetchUserImages,
  generateImageWithAi,
  generateNoteWithAi,
  generateTagOptions,
  generateTitleOptions,
  reorderDraftAssets,
  rewriteDraftWithAi,
  sendDraftToPublish,
  updateDraft,
  updateDraftAsset,
  uploadAssetFile,
  extractErrorMessage
} from "../../../lib/api";
import { useLatestRequest } from "../../../hooks/use-latest-request";
import type { DraftAsset } from "../../../lib/api";
import type { Draft, GeneratedImageAsset, SavedNote, UserImageFile } from "../../../types";
import { AssetPickerModal } from "./drafts/asset-picker-modal";
import { AssetSortableGrid } from "./drafts/asset-sortable-grid";
import { DraftEditor } from "./drafts/draft-editor";
import { DraftQueue } from "./drafts/draft-queue";
import { ImageOptimizeModal } from "./drafts/image-optimize-modal";
import { UploadModal } from "./drafts/upload-modal";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

type AiContentMode = "rewrite" | "generate";

function getNoteUrl(note: SavedNote): string {
  const raw = note.raw_json ?? {};
  for (const key of ["note_url", "url", "share_url"]) {
    const v = raw[key];
    if (typeof v === "string" && v.startsWith("http")) return v;
  }
  const data = (raw.data && typeof raw.data === "object") ? raw.data as Record<string, unknown> : {};
  const items = Array.isArray(data.items) ? data.items : [];
  const item = (items[0] && typeof items[0] === "object") ? items[0] as Record<string, unknown> : {};
  const card = (item.note_card && typeof item.note_card === "object") ? item.note_card as Record<string, unknown> : {};
  for (const obj of [card, item]) {
    const xsec = obj.xsec_token;
    if (typeof xsec === "string" && xsec) {
      const src = (typeof obj.xsec_source === "string" ? obj.xsec_source : "") || "pc_feed";
      return `https://www.xiaohongshu.com/explore/${note.note_id}?xsec_token=${xsec}&xsec_source=${src}`;
    }
    for (const k of ["note_url", "url", "share_url"]) {
      const v = obj[k];
      if (typeof v === "string" && v.startsWith("http")) return v;
    }
  }
  return `https://www.xiaohongshu.com/explore/${note.note_id}`;
}

const segmentedOptions = [
  {
    value: "rewrite" as const,
    label: "改写已有草稿",
    icon: <EditOutlined />,
  },
  {
    value: "generate" as const,
    label: "生成新草稿",
    icon: <PlusCircleOutlined />,
  },
];

/* ── helpers ───────────────────────────────────────────────────────── */

function isValidUrl(s: string): boolean {
  return s.startsWith("http://") || s.startsWith("https://");
}

function getAssetTypeFromUrl(url: string): "image" | "video" {
  const lower = url.toLowerCase();
  if (/\.(mp4|mov|avi|mkv|flv|wmv)/.test(lower)) return "video";
  return "image";
}

// 本地临时素材 id：负数表示“仅本地、尚未入库”。
// 用单调递减计数器而非 -Date.now()，避免同一毫秒内多个文件拿到相同 id
// 导致 React key / dnd-kit item id 冲突。
let localAssetSeq = 0;
function nextLocalAssetId(): number {
  localAssetSeq += 1;
  return -localAssetSeq;
}

export function XhsDraftsPage() {
  const request = useLatestRequest();
  const [activeMode, setActiveMode] = useState<AiContentMode>("rewrite");
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [instruction, setInstruction] = useState("保留事实，增强小红书种草感，语气自然。");
  const [topic, setTopic] = useState("");
  const [reference, setReference] = useState("");
  const [titleOptions, setTitleOptions] = useState<string[]>([]);
  const [tagOptions, setTagOptions] = useState<string[]>([]);
  const [systemPrompt, setSystemPrompt] = useState("你是小红书内容创作助手，擅长写吸引人的标题和正文。");
  const [sourceNote, setSourceNote] = useState<SavedNote | null>(null);
  const [sourceAssets, setSourceAssets] = useState<DraftAsset[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isRewriting, setIsRewriting] = useState(false);
  const [isPolishingTitles, setIsPolishingTitles] = useState(false);
  const [isPolishingTags, setIsPolishingTags] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSendingPublish, setIsSendingPublish] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rewritePreview, setRewritePreview] = useState<string | null>(null);
  const [optimizeModalOpen, setOptimizeModalOpen] = useState(false);
  const [optimizeAssetId, setOptimizeAssetId] = useState<number | null>(null);
  const [optimizePrompt, setOptimizePrompt] = useState("");
  const [optimizeRefImages, setOptimizeRefImages] = useState<string[]>([]);
  const [optimizeResult, setOptimizeResult] = useState<string | null>(null);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [assetUrl, setAssetUrl] = useState("");
  const [draftTags, setDraftTags] = useState<{id: string; name: string}[]>([]);
  const [newTagInput, setNewTagInput] = useState("");
  const [isAddingTag, setIsAddingTag] = useState(false);
  const [userImages, setUserImages] = useState<UserImageFile[]>([]);
  const [aiAssets, setAiAssets] = useState<GeneratedImageAsset[]>([]);
  const [selectedAssetUrls, setSelectedAssetUrls] = useState<string[]>([]);
  const [isAddingAssets, setIsAddingAssets] = useState(false);
  const [refPickerOpen, setRefPickerOpen] = useState(false);
  const [refPickerUrlInput, setRefPickerUrlInput] = useState("");

  const selectedDraft = drafts.find((draft) => draft.id === selectedDraftId) ?? null;
  const imageAssets = sourceAssets.filter((a) => a.asset_type === "image");
  const videoAssets = sourceAssets.filter((a) => a.asset_type === "video");
  const hasImageAssets = imageAssets.length > 0;
  const hasVideoAssets = videoAssets.length > 0;
  const optimizeAsset = sourceAssets.find((a) => a.id === optimizeAssetId) ?? null;

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    // setState updater 必须是纯函数（StrictMode 会双调用）；
    // 先基于当前状态算出新顺序，再在 updater 外发起 API 请求
    const images = sourceAssets.filter((a) => a.asset_type === "image");
    const others = sourceAssets.filter((a) => a.asset_type !== "image");
    const oldIdx = images.findIndex((a) => a.id === Number(active.id));
    const newIdx = images.findIndex((a) => a.id === Number(over.id));
    if (oldIdx < 0 || newIdx < 0) return;
    const reorderedImages = arrayMove(images, oldIdx, newIdx);
    const result = [...reorderedImages, ...others];
    setSourceAssets(result);
    const draftId = selectedDraft?.id;
    if (draftId) {
      const ids = reorderedImages.filter((a) => a.id > 0).map((a) => a.id);
      if (ids.length) {
        void reorderDraftAssets(draftId, ids).catch((err) => {
          console.error("reorder failed", err);
          antMessage.warning("图片顺序同步失败，请刷新后重试");
        });
      }
    }
  }

  function handleRemoveAsset(assetId: number) {
    const draftId = selectedDraft?.id;
    if (!draftId || assetId <= 0) {
      // 本地未保存的素材：直接移除本地状态即可
      setSourceAssets((prev) => prev.filter((a) => a.id !== assetId));
      return;
    }
    // FE-8：乐观更新 + 失败回滚——后端删除失败时恢复原状态并提示
    const snapshot = sourceAssets;
    setSourceAssets((prev) => prev.filter((a) => a.id !== assetId));
    deleteDraftAsset(draftId, assetId).catch(() => {
      setSourceAssets(snapshot);
      antMessage.error("素材删除失败，已恢复");
    });
  }

  function handleFileUpload(file: File): false {
    const draftId = selectedDraft?.id;
    (async () => {
      try {
        const uploaded = await uploadAssetFile(file);
        if (draftId) {
          const saved = await addDraftAsset(draftId, {
            asset_type: uploaded.asset_type,
            url: uploaded.download_url,
            local_path: uploaded.file_name,
          });
          setSourceAssets((prev) => [...prev, saved]);
        } else {
          setSourceAssets((prev) => [...prev, {
            id: nextLocalAssetId(),
            draft_id: 0,
            asset_type: uploaded.asset_type,
            url: uploaded.download_url,
            local_path: uploaded.file_name,
            sort_order: prev.length,
          }]);
        }
        antMessage.success("文件上传成功");
      } catch {
        antMessage.error("文件上传失败");
      }
    })();
    return false;
  }

  function handleUrlAdd() {
    const trimmed = assetUrl.trim();
    if (!trimmed) { antMessage.warning("请输入素材链接。"); return; }
    if (!isValidUrl(trimmed)) { antMessage.error("链接格式不正确，请输入 http:// 或 https:// 开头的链接。"); return; }
    const assetType = getAssetTypeFromUrl(trimmed);
    const draftId = selectedDraft?.id;
    if (draftId) {
      (async () => {
        try {
          const saved = await addDraftAsset(draftId, { asset_type: assetType, url: trimmed });
          setSourceAssets((prev) => [...prev, saved]);
          setAssetUrl("");
          setUploadModalOpen(false);
        } catch { antMessage.error("添加素材失败"); }
      })();
    } else {
      setSourceAssets((prev) => [...prev, {
        id: nextLocalAssetId(),
        draft_id: 0,
        asset_type: assetType,
        url: trimmed,
        local_path: "",
        sort_order: prev.length,
      }]);
      setAssetUrl("");
      setUploadModalOpen(false);
    }
  }

  function toggleAssetUrl(url: string) {
    setSelectedAssetUrls(prev => prev.includes(url) ? prev.filter(u => u !== url) : [...prev, url]);
  }

  function handleAddSelectedAssets() {
    const draftId = selectedDraft?.id;
    if (isAddingAssets) return; // 防重入：双击会导致同一批图片被重复添加
    const urls = [...selectedAssetUrls];
    if (!urls.length) return;
    setIsAddingAssets(true);
    (async () => {
      let added = 0;
      let failed = 0;
      for (const url of urls) {
        if (draftId) {
          try {
            const saved = await addDraftAsset(draftId, { asset_type: "image", url });
            setSourceAssets(prev => [...prev, saved]);
            added += 1;
          } catch {
            failed += 1;
          }
        } else {
          setSourceAssets(prev => [...prev, {
            id: nextLocalAssetId(),
            draft_id: 0,
            asset_type: "image",
            url,
            local_path: "",
            sort_order: prev.length,
          }]);
          added += 1;
        }
      }
      setSelectedAssetUrls([]);
      setUploadModalOpen(false);
      if (failed) {
        antMessage.warning(`已添加 ${added} 个图片，${failed} 个失败`);
      } else {
        antMessage.success(`已添加 ${added} 个图片`);
      }
      setIsAddingAssets(false);
    })();
  }

  function closeOptimizeModal() {
    setOptimizeModalOpen(false); setOptimizeAssetId(null); setOptimizePrompt(""); setOptimizeRefImages([]); setOptimizeResult(null);
  }

  function openOptimizeModal(assetId: number) {
    setOptimizeAssetId(assetId);
    setOptimizeModalOpen(true);
  }

  async function handleOptimizeImage() {
    const asset = sourceAssets.find((a) => a.id === optimizeAssetId);
    if (!asset) return;
    if (!optimizePrompt.trim()) { antMessage.warning("请输入润色提示词"); return; }
    setIsOptimizing(true); setOptimizeResult(null);
    try {
      const refImages = [asset.url || asset.local_path, ...optimizeRefImages];
      const fullPrompt = `基于提供的第一张原图进行润色修改。要求：${optimizePrompt.trim()}`;
      const result = await generateImageWithAi({
        prompt: fullPrompt,
        reference_images: refImages,
        save_to_assets: false,
      });
      setOptimizeResult(result.url);
      antMessage.success("图片润色完成");
    } catch {
      antMessage.error("图片润色失败，请确认已配置图片生成模型");
    } finally { setIsOptimizing(false); }
  }

  function handleReplaceOptimizedAsset() {
    const resultUrl = optimizeResult;
    if (!resultUrl) return;
    const draftId = selectedDraft?.id;
    if (draftId && optimizeAssetId && optimizeAssetId > 0) {
      void updateDraftAsset(draftId, optimizeAssetId, { url: resultUrl, local_path: "" }).then((saved) => {
        setSourceAssets((prev) => prev.map((a) => a.id === optimizeAssetId ? saved : a));
      }).catch(() => {
        setSourceAssets((prev) => prev.map((a) => a.id === optimizeAssetId ? { ...a, url: resultUrl, local_path: "" } : a));
      });
    } else {
      setSourceAssets((prev) => prev.map((a) => a.id === optimizeAssetId ? { ...a, url: resultUrl, local_path: "" } : a));
    }
    closeOptimizeModal();
    antMessage.success("已替换为润色后的图片");
  }

  function handlePickRefImage(url: string) {
    setOptimizeRefImages((prev) => [...prev, url]);
    setRefPickerOpen(false);
  }

  function handleAddRefUrl() {
    const v = refPickerUrlInput.trim();
    if (v && (v.startsWith("http://") || v.startsWith("https://") || v.startsWith("/api/"))) {
      setOptimizeRefImages((prev) => [...prev, v]);
      setRefPickerUrlInput("");
      setRefPickerOpen(false);
    }
  }

  function handleRemoveDraftTag(name: string) {
    setDraftTags((prev) => prev.filter((t) => t.name !== name));
  }

  function handleCommitNewTag() {
    const name = newTagInput.trim();
    if (name && !draftTags.some((t) => t.name === name)) {
      setDraftTags((prev) => [...prev, { id: "", name }]);
    }
    setNewTagInput("");
    setIsAddingTag(false);
  }

  function clearStatus() {
    setMessage(null);
    setError(null);
  }

  function selectDraft(draft: Draft, mode: AiContentMode = "rewrite") {
    setActiveMode(mode);
    setSelectedDraftId(draft.id);
    setTitle(draft.title);
    setBody(draft.body);
    setDraftTags(
      Array.isArray(draft.tags)
        ? draft.tags.map((t) => ({ id: t.id || "", name: t.name || "" }))
        : [],
    );
    clearStatus();
  }

  async function loadDrafts() {
    const seq = request.begin();
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetchDrafts("xhs");
      // review P1：点“刷新草稿”后立即切换草稿时，旧响应不得把选择顶掉
      if (!request.isLatest(seq)) return;
      setDrafts(result.items);
      const current = selectedDraftId
        ? result.items.find((draft) => draft.id === selectedDraftId)
        : result.items[0];
      if (current) {
        setSelectedDraftId(current.id);
        setTitle(current.title);
        setBody(current.body);
        setDraftTags(
          Array.isArray(current.tags)
            ? current.tags.map((t) => ({ id: t.id || "", name: t.name || "" }))
            : [],
        );
      } else {
        setSelectedDraftId(null);
        setTitle("");
        setBody("");
        setDraftTags([]);
      }
    } catch {
      if (!request.isLatest(seq)) return;
      setError("草稿列表加载失败。");
    } finally {
      if (request.isLatest(seq)) setIsLoading(false);
    }
  }

  async function handleDeleteDraft(draftId: number) {
    try {
      await deleteDraft(draftId);
      setDrafts((prev) => prev.filter((d) => d.id !== draftId));
      if (selectedDraftId === draftId) {
        setSelectedDraftId(null);
        setTitle("");
        setBody("");
      }
      setMessage("草稿已删除。");
    } catch {
      setError("草稿删除失败。");
    }
  }

  function upsertDraft(draft: Draft, mode: AiContentMode = activeMode) {
    setDrafts((current) => {
      const exists = current.some((item) => item.id === draft.id);
      return exists ? current.map((item) => (item.id === draft.id ? draft : item)) : [draft, ...current];
    });
    // FE-9：仅在用户仍选中该草稿时更新选中态；保存旧草稿不应把用户切走
    if (selectedDraftId === draft.id || selectedDraftId === null) {
      selectDraft(draft, mode);
    }
  }

  async function handleSave() {
    if (!selectedDraft) {
      setError("请先选择或生成一个草稿。");
      return;
    }
    setIsSaving(true);
    clearStatus();
    try {
      const updated = await updateDraft(selectedDraft.id, { title, body, tags: draftTags });
      upsertDraft(updated);
      setMessage(`草稿 #${updated.id} 已保存。`);
    } catch {
      setError("草稿保存失败。");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleGenerateNote() {
    if (!topic.trim()) {
      setError("请先填写选题。");
      return;
    }
    setIsGenerating(true);
    clearStatus();
    try {
      const draft = await generateNoteWithAi({
        platform: "xhs",
        topic: topic.trim(),
        reference,
        instruction,
      });
      upsertDraft(draft, "generate");
      setMessage(`已生成草稿 #${draft.id}，可继续编辑或送入发布中心。`);
    } catch {
      setError("AI 生成笔记失败，请确认已配置默认文本模型。");
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleRewrite() {
    if (!selectedDraft) {
      setError("请先选择一个草稿。");
      return;
    }
    setIsRewriting(true);
    clearStatus();
    setRewritePreview(null);
    try {
      // FE-7：改写前先保存全部编辑内容（含 tags），避免送发布时后端复制到旧 tags
      const saved = await updateDraft(selectedDraft.id, { title, body, tags: draftTags });
      const rewritten = await rewriteDraftWithAi({ draft_id: saved.id, instruction: systemPrompt + "\n" + instruction });
      setRewritePreview(rewritten.body);
      setMessage("AI 改写完成，请在下方对比后决定是否采用。");
    } catch (err: unknown) {
      setError(extractErrorMessage(err, "AI 改写失败，请确认已配置默认文本模型。"));
    } finally {
      setIsRewriting(false);
    }
  }

  function applyRewrite() {
    if (rewritePreview !== null) {
      setBody(rewritePreview);
      setRewritePreview(null);
      setMessage("已采用 AI 改写内容。");
    }
  }

  function discardRewrite() {
    setRewritePreview(null);
    setMessage("已放弃 AI 改写内容。");
  }

  async function handleGenerateTitles() {
    if (!body.trim()) {
      setError("请先填写正文。");
      return;
    }
    setIsPolishingTitles(true);
    clearStatus();
    try {
      const result = await generateTitleOptions({ title, body, count: 5 });
      setTitleOptions(result.items);
      setMessage("标题候选已生成。");
    } catch (err: unknown) {
      setError(extractErrorMessage(err, "标题润色失败，请确认已配置默认文本模型。"));
    } finally {
      setIsPolishingTitles(false);
    }
  }

  async function handleGenerateTags() {
    if (!body.trim()) {
      setError("请先填写正文。");
      return;
    }
    setIsPolishingTags(true);
    clearStatus();
    try {
      const result = await generateTagOptions({ title, body, count: 8 });
      setTagOptions(result.items);
      setMessage("标签候选已生成。");
    } catch (err: unknown) {
      setError(extractErrorMessage(err, "标签润色失败，请确认已配置默认文本模型。"));
    } finally {
      setIsPolishingTags(false);
    }
  }

  async function handleSendToPublish() {
    if (!selectedDraft) {
      setError("请先选择一个草稿。");
      return;
    }
    setIsSendingPublish(true);
    clearStatus();
    try {
      // FE-7：送发布前提交 {title, body, tags}，后端 send-to-publish 会复制 draft.tags
      const saved = await updateDraft(selectedDraft.id, { title, body, tags: draftTags });
      const job = await sendDraftToPublish(saved.id, {
        publish_mode: "immediate",
      });
      upsertDraft(saved);
      setMessage(`已送入发布中心，发布任务 #${job.id}。请前往发布中心选择账号并发布。`);
    } catch (err: unknown) {
      setError(extractErrorMessage(err, "送发布中心失败。"));
    } finally {
      setIsSendingPublish(false);
    }
  }

  useEffect(() => {
    void loadDrafts();
  }, []);

  useEffect(() => {
    if (!selectedDraft) {
      setSourceNote(null);
      setSourceAssets([]);
      return;
    }
    let cancelled = false;
    (async () => {
      // Load assets from draft (not source note)
      try {
        const assetsResult = await fetchDraftAssets(selectedDraft.id);
        if (!cancelled) setSourceAssets(assetsResult.items);
      } catch {
        if (!cancelled) setSourceAssets([]);
      }

      // Load source note info for display only
      if (selectedDraft.source_note_id) {
        try {
          const note = await fetchSavedNote(selectedDraft.source_note_id, true);
          if (!cancelled) setSourceNote(note);
        } catch {
          if (!cancelled) setSourceNote(null);
        }
      } else {
        if (!cancelled) setSourceNote(null);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedDraft?.id, selectedDraft?.source_note_id]);

  useEffect(() => {
    if (uploadModalOpen) {
      void fetchUserImages().then(r => setUserImages(r.items)).catch(() => {});
      void fetchGeneratedImageAssets().then(r => setAiAssets(r.items)).catch(() => {});
      setSelectedAssetUrls([]);
    }
  }, [uploadModalOpen]);

  useEffect(() => {
    if (refPickerOpen) {
      void fetchUserImages().then((r) => setUserImages(r.items)).catch(() => {});
      void fetchGeneratedImageAssets().then((r) => setAiAssets(r.items)).catch(() => {});
    }
  }, [refPickerOpen]);

  // ---- Rewrite mode: 3-column layout ----
  function renderRewriteMode() {
    return (
      <Row gutter={16}>
        {/* Col 1: Draft queue */}
        <Col xs={24} lg={6}>
          <DraftQueue
            drafts={drafts}
            selectedDraftId={selectedDraftId}
            isLoading={isLoading}
            onSelectDraft={selectDraft}
            onDeleteDraft={handleDeleteDraft}
          />
        </Col>

        {/* Col 2: Main editor */}
        <Col xs={24} lg={12}>
          {/* FE-4：素材区独立于来源笔记渲染——AI 生成的空草稿也必须能上传第一张图 */}
          {selectedDraft && (
            <AssetSortableGrid
              imageAssets={imageAssets}
              videoAssets={videoAssets}
              hasVideoAssets={hasVideoAssets}
              hasImageAssets={hasImageAssets}
              videoFallbackUrl={sourceNote?.video_url}
              onDragEnd={handleDragEnd}
              onEditAsset={openOptimizeModal}
              onRemoveAsset={handleRemoveAsset}
              onViewAsset={setPreviewImage}
              onOpenUpload={() => setUploadModalOpen(true)}
            />
          )}
          {/* FE-4：来源笔记只作为可选信息展示，不再包裹素材区 */}
          {sourceNote && (
            <Card
              title="来源笔记"
              size="small"
              style={{ marginBottom: 16 }}
              extra={
                <a
                  href={getNoteUrl(sourceNote)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button type="link" size="small" icon={<LinkOutlined />}>查看原文</Button>
                </a>
              }
            >
              <Text strong style={{ display: "block", marginBottom: 4 }}>{sourceNote.title}</Text>
              <Paragraph
                ellipsis={{ rows: 3, expandable: true, symbol: "展开" }}
                type="secondary"
                style={{ marginBottom: 8, fontSize: 13 }}
              >
                {sourceNote.content}
              </Paragraph>
            </Card>
          )}
          <DraftEditor
            title={title}
            body={body}
            tags={draftTags}
            isSaving={isSaving}
            canSave={Boolean(selectedDraft)}
            isAddingTag={isAddingTag}
            newTagInput={newTagInput}
            onTitleChange={setTitle}
            onBodyChange={setBody}
            onRemoveTag={handleRemoveDraftTag}
            onStartAddTag={() => setIsAddingTag(true)}
            onNewTagInputChange={setNewTagInput}
            onCommitNewTag={handleCommitNewTag}
            onSave={handleSave}
          />
        </Col>

        {/* Col 3: AI assistant */}
        <Col xs={24} lg={6}>
          <div style={{ position: "sticky", top: 16, maxHeight: "calc(100vh - 120px)", overflowY: "auto" }}>
          <Card title="AI 助手" size="small">
            <Collapse
              size="small"
              style={{ marginBottom: 16 }}
              items={[
                {
                  key: "system-prompt",
                  label: "系统提示词 (可选)",
                  children: (
                    <TextArea
                      rows={4}
                      value={systemPrompt}
                      onChange={(e) => setSystemPrompt(e.target.value)}
                      placeholder="你是小红书内容创作助手，擅长写吸引人的标题和正文。"
                    />
                  ),
                },
              ]}
            />

            <div style={{ marginBottom: 16 }}>
              <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>AI 改写指令</Text>
              <Input
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="保留事实，增强种草感"
                style={{ marginBottom: 8 }}
              />
              <Button
                onClick={handleRewrite}
                loading={isRewriting}
                disabled={!selectedDraft}
                block
                type="primary"
                icon={<ExperimentOutlined />}
              >
                AI 改写正文
              </Button>
            </div>

            {rewritePreview !== null && (
              <Card size="small" title="改写结果" style={{ marginBottom: 16, background: "var(--app-surface-alt)", borderColor: "#1668dc40" }}>
                <Paragraph style={{ whiteSpace: "pre-wrap", color: "var(--app-text-secondary)", fontSize: 13, maxHeight: 240, overflow: "auto" }}>{rewritePreview}</Paragraph>
                <Space style={{ marginTop: 8 }}>
                  <Button type="primary" size="small" onClick={applyRewrite}>采用</Button>
                  <Button size="small" onClick={discardRewrite}>放弃</Button>
                </Space>
              </Card>
            )}

            <Divider style={{ margin: "12px 0" }} />

            <Space direction="vertical" style={{ width: "100%" }} size={8}>
              <Button onClick={handleGenerateTitles} loading={isPolishingTitles} block icon={<EditOutlined />}>润色标题</Button>
              <Button onClick={handleGenerateTags} loading={isPolishingTags} block icon={<TagsOutlined />}>润色标签</Button>
            </Space>

            <Divider />

            {titleOptions.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
                  标题建议（点击选用）
                </Text>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {titleOptions.map((option) => (
                    <div
                      key={option}
                      onClick={() => setTitle(option)}
                      style={{
                        cursor: "pointer",
                        padding: "4px 8px",
                        borderRadius: 4,
                        background: "rgba(22, 104, 220, 0.08)",
                        border: "1px solid #1668dc30",
                        fontSize: 12,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={option}
                    >
                      {option}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tagOptions.length > 0 && (
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
                  标签建议（点击添加）
                </Text>
                <Space size={[6, 6]} wrap>
                  {tagOptions.map((tag) => (
                    <Tag
                      key={tag}
                      color="geekblue"
                      onClick={() => {
                        if (!draftTags.some((t) => t.name === tag)) {
                          setDraftTags((prev) => [...prev, { id: "", name: tag }]);
                        }
                      }}
                      style={{ cursor: "pointer" }}
                    >
                      #{tag}
                    </Tag>
                  ))}
                </Space>
              </div>
            )}

            <Divider style={{ margin: "12px 0" }} />

            <div>
              <Button
                onClick={handleSendToPublish}
                loading={isSendingPublish}
                disabled={!selectedDraft}
                block
                type="primary"
                icon={<SendOutlined />}
              >
                送入发布中心
              </Button>
            </div>
          </Card>
          </div>
        </Col>

        {/* Optimize modal */}
        <ImageOptimizeModal
          open={optimizeModalOpen}
          asset={optimizeAsset}
          isOptimizing={isOptimizing}
          prompt={optimizePrompt}
          refImages={optimizeRefImages}
          result={optimizeResult}
          onCancel={closeOptimizeModal}
          onPromptChange={setOptimizePrompt}
          onRemoveRefImage={(index) => setOptimizeRefImages((prev) => prev.filter((_, i) => i !== index))}
          onOpenRefPicker={() => setRefPickerOpen(true)}
          onGenerate={() => { void handleOptimizeImage(); }}
          onReplace={handleReplaceOptimizedAsset}
        />

        {/* Reference image picker modal */}
        <AssetPickerModal
          open={refPickerOpen}
          userImages={userImages}
          aiAssets={aiAssets}
          urlInput={refPickerUrlInput}
          onCancel={() => { setRefPickerOpen(false); setRefPickerUrlInput(""); }}
          onUrlInputChange={setRefPickerUrlInput}
          onPickImage={handlePickRefImage}
          onAddUrl={handleAddRefUrl}
        />

        {/* Upload modal */}
        <UploadModal
          open={uploadModalOpen}
          assetUrl={assetUrl}
          userImages={userImages}
          aiAssets={aiAssets}
          selectedAssetUrls={selectedAssetUrls}
          isAddingAssets={isAddingAssets}
          onCancel={() => setUploadModalOpen(false)}
          onAssetUrlChange={setAssetUrl}
          onUrlAdd={handleUrlAdd}
          onToggleAssetUrl={toggleAssetUrl}
          onAddSelectedAssets={handleAddSelectedAssets}
          onFileUpload={handleFileUpload}
        />

        {/* Image preview */}
        {previewImage && (
          <Image
            src={previewImage}
            style={{ display: "none" }}
            preview={{ visible: true, onVisibleChange: (v) => { if (!v) setPreviewImage(null); } }}
          />
        )}
      </Row>
    );
  }

  // ---- Generate mode: centered card ----
  function renderGenerateMode() {
    return (
      <div style={{ maxWidth: 640, margin: "0 auto" }}>
        <Card title="AI 笔记生成">
          <Form layout="vertical">
            <Form.Item label="选题" required>
              <Input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="例如：通勤低卡早餐怎么搭配"
              />
            </Form.Item>
            <Form.Item label="参考材料">
              <TextArea
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="竞品笔记、卖点、评论洞察或人群信息"
                rows={6}
              />
            </Form.Item>
            <Form.Item label="AI 指令">
              <Input
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="保留事实，增强小红书种草感，语气自然。"
              />
            </Form.Item>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              onClick={handleGenerateNote}
              loading={isGenerating}
              block
            >
              生成草稿
            </Button>
          </Form>
        </Card>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <PageHeader
        eyebrow="XHS Drafts"
        title="草稿工坊"
        description="管理草稿、编辑内容和素材、AI 改写润色，生成结果送入发布中心。"
        action={
          <Button icon={<ReloadOutlined />} onClick={loadDrafts} loading={isLoading}>
            刷新草稿
          </Button>
        }
      />

      <Segmented
        value={activeMode}
        onChange={(val) => setActiveMode(val as AiContentMode)}
        options={segmentedOptions}
        block
        style={{ marginBottom: 8 }}
      />

      {error && (
        <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} />
      )}
      {message && (
        <Alert type="success" message={message} showIcon closable onClose={() => setMessage(null)} />
      )}

      {activeMode === "rewrite" ? renderRewriteMode() : renderGenerateMode()}
    </div>
  );
}
