import { SaveOutlined } from "@ant-design/icons";
import { Button, Card, Form, Input, Space, Tag } from "antd";

const { TextArea } = Input;

export type DraftTag = { id: string; name: string };

export type DraftEditorProps = {
  title: string;
  body: string;
  tags: DraftTag[];
  isSaving: boolean;
  canSave: boolean;
  isAddingTag: boolean;
  newTagInput: string;
  onTitleChange: (value: string) => void;
  onBodyChange: (value: string) => void;
  onRemoveTag: (name: string) => void;
  onStartAddTag: () => void;
  onNewTagInputChange: (value: string) => void;
  onCommitNewTag: () => void;
  onSave: () => void;
};

export function DraftEditor({
  title,
  body,
  tags,
  isSaving,
  canSave,
  isAddingTag,
  newTagInput,
  onTitleChange,
  onBodyChange,
  onRemoveTag,
  onStartAddTag,
  onNewTagInputChange,
  onCommitNewTag,
  onSave,
}: DraftEditorProps) {
  return (
    <Card title="编辑器">
      <Form layout="vertical">
        <Form.Item label="标题" style={{ marginBottom: 16 }}>
          <Input
            value={title}
            onChange={(e) => onTitleChange(e.target.value)}
            placeholder="生成或选择一个标题"
            size="large"
          />
        </Form.Item>
        <Form.Item label="正文" style={{ marginBottom: 16 }}>
          <TextArea
            value={body}
            onChange={(e) => onBodyChange(e.target.value)}
            placeholder="正文生成后可在这里继续编辑。"
            rows={16}
            style={{ fontFamily: "monospace" }}
          />
        </Form.Item>
        <Form.Item label="标签" style={{ marginBottom: 16 }}>
          <Space size={[4, 8]} wrap>
            {tags.map((tag) => (
              <Tag
                key={tag.id || tag.name}
                closable
                onClose={() => onRemoveTag(tag.name)}
                color="blue"
              >
                #{tag.name}
              </Tag>
            ))}
            {isAddingTag ? (
              <Input
                size="small"
                style={{ width: 120 }}
                value={newTagInput}
                onChange={(e) => onNewTagInputChange(e.target.value)}
                onPressEnter={onCommitNewTag}
                onBlur={onCommitNewTag}
                autoFocus
                placeholder="输入标签"
              />
            ) : (
              <Tag
                style={{ cursor: "pointer", borderStyle: "dashed" }}
                onClick={onStartAddTag}
              >
                + 添加标签
              </Tag>
            )}
          </Space>
        </Form.Item>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          onClick={() => onSave()}
          loading={isSaving}
          disabled={!canSave}
        >
          保存
        </Button>
      </Form>
    </Card>
  );
}
