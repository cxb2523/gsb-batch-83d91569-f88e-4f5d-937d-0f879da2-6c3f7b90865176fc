export type Position = [number, number];
export type Geometry = { type: 'Point'; coordinates: Position } | { type: 'LineString'; coordinates: Position[] } | { type: 'Polygon'; coordinates: Position[][] };
export interface GeoFeature { type: 'Feature'; id: string; properties: { name: string }; geometry: Geometry }
export interface Collection { type: 'FeatureCollection'; features: GeoFeature[] }
const object = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
export function validateCollection(value: unknown): Collection {
 if (!object(value) || value.type !== 'FeatureCollection' || !Array.isArray(value.features) || value.features.length > 200) throw new Error('请输入不超过 200 个要素的 GeoJSON FeatureCollection');
 let vertices = 0;
 const position = (v: unknown): Position => {
  if (!Array.isArray(v) || v.length !== 2 || !v.every((n) => typeof n === 'number' && Number.isFinite(n)) || Math.abs(v[0]) > 180 || Math.abs(v[1]) > 85.05112878) throw new Error('坐标必须是 WGS84 [经度, 纬度]；纬度限制在 Web Mercator 可显示范围内');
  if (++vertices > 10000) throw new Error('总顶点数不能超过 10000');
  return [v[0], v[1]];
 };
 const ids = new Set<string>();
 const features = value.features.map((raw: unknown, index: number): GeoFeature => {
  if (!object(raw) || raw.type !== 'Feature' || !object(raw.geometry)) throw new Error('要素或 geometry 无效');
  const g = raw.geometry; let geometry: Geometry;
  if (g.type === 'Point') geometry = { type: 'Point', coordinates: position(g.coordinates) };
  else if (g.type === 'LineString') {
   if (!Array.isArray(g.coordinates) || g.coordinates.length < 2) throw new Error('线至少需要两个点');
   geometry = { type: 'LineString', coordinates: g.coordinates.map(position) };
  } else if (g.type === 'Polygon') {
   if (!Array.isArray(g.coordinates) || !g.coordinates.length) throw new Error('面至少需要一个闭合环');
   geometry = { type: 'Polygon', coordinates: g.coordinates.map((ring: unknown) => {
    if (!Array.isArray(ring) || ring.length < 4) throw new Error('面环至少需要四个坐标');
    const points = ring.map(position); const first = points[0]!; const last = points[points.length - 1]!;
    if (first[0] !== last[0] || first[1] !== last[1]) throw new Error('面环必须闭合');
    return points;
   }) };
  } else throw new Error('本课程只接受 Point、LineString 和 Polygon');
  const id = raw.id === undefined ? `import-${index + 1}` : String(raw.id);
  if (!['string', 'number', 'undefined'].includes(typeof raw.id) || !id || id.length > 80 || ids.has(id)) throw new Error('要素 id 不能为空、过长或重复');
  ids.add(id);
  const props = object(raw.properties) ? raw.properties : {};
  const name = typeof props.name === 'string' ? props.name.trim() : `要素 ${index + 1}`;
  if (!name || name.length > 80) throw new Error('要素名称应为 1–80 个字符');
  return { type: 'Feature', id, properties: { name }, geometry };
 });
 return { type: 'FeatureCollection', features };
}
export function countVertices(collection: Collection): number {
 return collection.features.reduce((total, feature) => total + geometryVertices(feature.geometry), 0);
}
function geometryVertices(geometry: Geometry): number {
 return geometry.type === 'Point' ? 1 : geometry.type === 'LineString' ? geometry.coordinates.length : geometry.coordinates.reduce((total, ring) => total + ring.length, 0);
}
/** 为与已有图层或同批次冲突的 id 重新分配唯一值，不改动要素内容。 */
export function assignUniqueIds(collection: Collection, usedIds: Iterable<string>): Collection {
 const used = new Set(usedIds);
 return { type: 'FeatureCollection', features: collection.features.map((feature) => {
  let id = feature.id;
  if (used.has(id)) {
   const base = id.slice(0, 77) || 'import';
   let suffix = 2;
   do {
    const tail = `-${suffix++}`;
    id = `${base.slice(0, 80 - tail.length)}${tail}`;
   } while (used.has(id));
  }
  used.add(id);
  return { ...feature, id };
 }) };
}
export function demoFeatures(): Collection {
 return { type: 'FeatureCollection', features: [
  { type: 'Feature', id: 'library', properties: { name: '学习图书馆' }, geometry: { type: 'Point', coordinates: [121.4695, 31.233] } },
  { type: 'Feature', id: 'lab', properties: { name: '创作实验室' }, geometry: { type: 'Point', coordinates: [121.478, 31.2305] } },
  { type: 'Feature', id: 'garden', properties: { name: '河畔花园' }, geometry: { type: 'Point', coordinates: [121.4735, 31.2258] } },
 ] };
}
