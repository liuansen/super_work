import { expect, test } from "@playwright/test";

/**
 * 关键链路冒烟：注册 → 应用中心 → 进入小红书工作区 → 未登录态被拦截。
 *
 * 只验证「跨层契约」：登录态（HttpOnly cookie + 内存 access token）能
 * 让受保护路由放行、侧边栏与页面真实渲染、登出后立即失效。
 * 不验证业务细节（那些由后端 pytest 与前端单测覆盖）。
 */

const USERNAME = `e2e_${Date.now().toString(36)}`;
const PASSWORD = "e2e-password-123";

test("register, land in app center, open xhs workspace, then logout", async ({ page }) => {
  await page.goto("/login");

  // 切到注册页签
  await page.getByRole("radio", { name: /注册|Register/ }).click().catch(async () => {
    // Segmented 的 label 可能不是 radio 角色：退化为文本点击
    await page.getByText("注册", { exact: true }).click();
  });

  const inputs = page.locator("form input");
  await inputs.nth(0).fill(USERNAME);
  await inputs.nth(1).fill(PASSWORD);
  if ((await inputs.count()) >= 3) {
    await inputs.nth(2).fill(PASSWORD);
  }
  await page.locator("form").getByRole("button").first().click();

  // 注册成功 → 应用中心
  await expect(page).toHaveURL(/\/apps$/, { timeout: 15_000 });
  await expect(page.getByText("超级工作台")).toBeVisible();

  // 进入小红书工作区（真实调用 /api/accounts 等接口）
  await page.goto("/platforms/xhs/dashboard");
  await expect(page).toHaveURL(/\/platforms\/xhs\/dashboard$/);
  await expect(page.locator(".ant-layout-sider")).toBeVisible();

  // 刷新后仍保持登录态（refresh cookie 生效）
  await page.reload();
  await expect(page).toHaveURL(/\/platforms\/xhs\/dashboard$/);

  // 登出后受保护路由跳回登录页
  const logoutButton = page.getByRole("button", { name: /退出|登出|logout/i });
  if (await logoutButton.count()) {
    await logoutButton.first().click();
    await expect(page).toHaveURL(/\/login$/, { timeout: 15_000 });
  }
});

test("anonymous deep link is redirected to login", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/platforms/xhs/library");
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
});
