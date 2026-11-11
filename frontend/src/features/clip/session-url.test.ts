import { describe, expect, it } from "vitest";

import { buildEditorUrl } from "./session-url";

describe("buildEditorUrl", () => {
  it("把令牌放进 fragment 并对参数编码", () => {
    const url = buildEditorUrl("http://127.0.0.1:3000/", "a+b/c=", 42);
    expect(url).toBe("http://127.0.0.1:3000/#handoff=a%2Bb%2Fc%3D&session=42");
    expect(url).not.toContain("?handoff=");
  });
});
