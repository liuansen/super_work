export type WorkbenchApp = Readonly<{
  id: string;
  name: string;
  description: string;
  icon: string;
  entryPath: string;
  enabled: boolean;
}>;

export const workbenchApps: readonly WorkbenchApp[] = [
  {
    id: 'xhs',
    name: '小红书运营',
    description: '采集、内容管理、创作与发布的一站式运营工作台',
    icon: '/logo.jpg',
    entryPath: '/platforms/xhs/dashboard',
    enabled: true
  }
];

export function findWorkbenchApp(id: string | undefined): WorkbenchApp | undefined {
  return workbenchApps.find(app => app.id === id);
}
