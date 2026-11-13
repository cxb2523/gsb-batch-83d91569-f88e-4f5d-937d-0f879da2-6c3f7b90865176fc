import { test, expect, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { validateCollection } from '../../src/geojson';

const feature = (id: string, name: string, coordinates: [number, number]) => ({ type: 'Feature', id, properties: { name }, geometry: { type: 'Point', coordinates } });
const file = (name: string, value: unknown) => ({ name, mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(value)) });

/** 等待一次批量导入的处理与确认对话框出现。 */
async function batch(page: Page, files: { name: string; mimeType: string; buffer: Buffer }[]) {
 await page.locator('#file').setInputFiles(files);
 await expect(page.locator('#confirm')).toBeVisible();
}

test('批量导入逐文件交代结局，成功文件追加而不破坏当前图层', async ({ page }, info) => {
 await page.goto('/'); await expect(page.locator('#feature-count')).toHaveText('3 个要素');
 await batch(page, [
  file('points.geojson', { type: 'FeatureCollection', features: [
   feature('library', '批量点 A', [121.472, 31.231]),
   feature('batch-point-b', '批量点 B', [121.4765, 31.2295]),
  ] }),
  file('route.json', { type: 'FeatureCollection', features: [
   { type: 'Feature', id: 'route-x', properties: { name: '批量路线' }, geometry: { type: 'LineString', coordinates: [[121.47, 31.228], [121.474, 31.2305], [121.478, 31.227]] } },
  ] }),
  file('bad.geojson', { type: 'FeatureCollection', features: [feature('bad', '坏点', [0, 90])] }),
 ]);
 // 确认框说明本次新增数与失败文件数。
 await expect(page.locator('#confirm-text')).toContainText('新增 3 个要素');
 await expect(page.locator('#confirm-text')).toContainText('1 个文件失败');
 await page.getByRole('button', { name: '确认', exact: true }).click();
 await expect(page.locator('#feature-count')).toHaveText('6 个要素');
 // 逐文件结局：成功给要素数，失败给原因。
 await expect(page.locator('#import-list li')).toHaveCount(3);
 await expect(page.locator('#import-list li[data-file="points.geojson"]')).toContainText('成功：2 个要素');
 await expect(page.locator('#import-list li[data-file="route.json"]')).toContainText('成功：1 个要素');
 await expect(page.locator('#import-list li[data-file="bad.geojson"]')).toContainText('失败：坐标必须是 WGS84');
 await expect(page.locator('#import-report')).toBeVisible();
 await expect(page.locator('#import-summary')).toContainText('成功 2');
 await expect(page.locator('#import-summary')).toContainText('失败 1');
 await expect(page.locator('#import-summary')).toContainText('新增 3 个要素');
 // 原有要素仍在，当前图层没有被替换。
 await expect(page.locator('#features')).toContainText('学习图书馆');
 await expect(page.locator('#features')).toContainText('批量点 A');
 await expect(page.locator('#features')).toContainText('批量点 B');
 await expect(page.locator('#features')).toContainText('批量路线');
 // 追加后仍可选择并编辑。
 await page.getByRole('button', { name: /批量点 A/ }).click();
 await expect(page.locator('#inspector')).toBeVisible();
 await page.getByLabel('要素名称').fill('批量点 A 已编辑'); await page.getByRole('button', { name: '保存名称' }).click();
 await expect(page.locator('#features')).toContainText('批量点 A 已编辑');
 // 导出结果仍需通过数据契约校验，且 id 不与已有要素冲突。
 const downloadEvent = page.waitForEvent('download'); await page.getByRole('button', { name: /导出 GeoJSON/ }).click();
 const target = info.outputPath('batch-export.geojson'); await (await downloadEvent).saveAs(target);
 const data = JSON.parse(await readFile(target, 'utf8'));
 expect(() => validateCollection(data)).not.toThrow();
 expect(data.features).toHaveLength(6);
 const ids = data.features.map((item: { id: string }) => item.id);
 expect(new Set(ids).size).toBe(ids.length);
 expect(ids).toContain('library-2');
 expect(ids.filter((id: string) => id === 'library')).toHaveLength(1);
});

test('超过要素数、顶点数与 1MB 的文件被拒绝，其余文件仍成功', async ({ page }, info) => {
 await page.goto('/'); await expect(page.locator('#feature-count')).toHaveText('3 个要素');
 const tooMany = { type: 'FeatureCollection', features: Array.from({ length: 198 }, (_, index) => feature(`many-${index}`, `超量点 ${index}`, [121.47 + index * 0.00001, 31.23])) };
 const tooManyVertices = { type: 'FeatureCollection', features: [{ type: 'Feature', id: 'long-line', properties: { name: '超长线' }, geometry: { type: 'LineString', coordinates: Array.from({ length: 9999 }, (_, index) => [121.47 + index * 0.000001, 31.23]) } }] };
 const oversized = { type: 'FeatureCollection', features: [feature('large', '超大文件点', [121.472, 31.231])], padding: 'x'.repeat(1024 * 1024) };
 await batch(page, [
  file('too-many.geojson', tooMany),
  file('too-many-vertices.geojson', tooManyVertices),
  file('oversized.json', oversized),
  file('good.geojson', { type: 'FeatureCollection', features: [feature('good-a', '正常点 A', [121.4735, 31.232]), feature('good-b', '正常点 B', [121.4745, 31.226])] }),
 ]);
 await expect(page.locator('#confirm-text')).toContainText('新增 2 个要素');
 await expect(page.locator('#confirm-text')).toContainText('3 个文件失败');
 await page.getByRole('button', { name: '确认', exact: true }).click();
 await expect(page.locator('#feature-count')).toHaveText('5 个要素');
 await expect(page.locator('#import-list li[data-file="too-many.geojson"]')).toContainText('失败：');
 await expect(page.locator('#import-list li[data-file="too-many.geojson"]')).toContainText('要素上限');
 await expect(page.locator('#import-list li[data-file="too-many-vertices.geojson"]')).toContainText('顶点上限');
 await expect(page.locator('#import-list li[data-file="oversized.json"]')).toContainText('1MB');
 await expect(page.locator('#import-list li[data-file="good.geojson"]')).toContainText('成功：2 个要素');
 await expect(page.locator('#import-summary')).toContainText('成功 1');
 await expect(page.locator('#import-summary')).toContainText('失败 3');
 // 拒绝的文件没有留下部分数据，已有要素和成功文件都完好。
 await expect(page.locator('#features')).toContainText('学习图书馆');
 await expect(page.locator('#features')).toContainText('正常点 A');
 await expect(page.locator('#features')).not.toContainText('超量点 0');
 await expect(page.locator('#features')).not.toContainText('超长线');
 const downloadEvent = page.waitForEvent('download'); await page.getByRole('button', { name: /导出 GeoJSON/ }).click();
 const target = info.outputPath('rejected-export.geojson'); await (await downloadEvent).saveAs(target);
 const data = JSON.parse(await readFile(target, 'utf8'));
 expect(() => validateCollection(data)).not.toThrow();
 expect(data.features).toHaveLength(5);
 expect(data.features.map((item: { id: string }) => item.id)).not.toContain('many-0');
});
