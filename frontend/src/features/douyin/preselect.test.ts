import { describe, expect, it } from "vitest";

import { readDouyinPreselect } from "./preselect";

describe("readDouyinPreselect", () => {
  it("读取 media 与 title", () => {
    const params = new URLSearchParams("media=xhs-clip-u1-a.mp4&title=%E5%BC%80%E7%AE%B1");
    expect(readDouyinPreselect(params)).toEqual({
      media: "xhs-clip-u1-a.mp4",
      title: "开箱",
    });
  });

  it("缺少 media 时返回空", () => {
    expect(readDouyinPreselect(new URLSearchParams("title=x"))).toEqual({
      media: null,
      title: null,
    });
  });
});
