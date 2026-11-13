# 地图实验室架构

## 依赖方向

```mermaid
flowchart LR
  UI[main.ts 页面交互] --> Map[map.ts 地图引擎]
  UI --> Contract[geojson.ts 数据契约]
  Map --> Contract
  Map --> OL[OpenLayers]
```

数据校验不依赖 DOM 或地图实例，适合纯单元测试；地图引擎封装图层和交互，页面层只绑定事件和反馈。要素名称通过 textContent 写入 DOM，不将导入数据作为 HTML 执行。

## 图层与投影

从下到上是本地示意矢量底图、默认隐藏的在线瓦片层、用户要素层。选择交互只作用于用户要素层，不会误选背景建筑。打开在线图层时才请求外部瓦片，OpenLayers 自动显示 attribution。

GeoJSON 在边界处通过 dataProjection=EPSG:4326 / featureProjection=EPSG:3857 显式转换。测量使用 ol/sphere 而不是直接把经纬度差当米数。

## 交互生命周期

工具切换时移除旧 Draw；Select 与 Modify 根据模式启停，避免多个绘制工具同时监听事件。新增要素分配 id 和名称。清空会清除选中状态。批量导入先逐个读取、校验并试算容量与 id，全部结论确定后弹出一次确认，再按选择顺序追加成功文件；单个文件失败只记为一条结果，不中断其余文件，也不清空当前图层。

`geojson.ts` 提供 `countVertices` 与 `assignUniqueIds`：前者复用契约中的顶点口径统计要素集合，后者在追加前为与已有图层或同批次冲突的 id 重新分配唯一值（截断后加 `-2`、`-3` 后缀），避免覆盖已有要素。页面层负责 1MB 单文件限制与追加后总量（200 要素 / 10000 顶点）判定，地图层只做追加与统计。

修改产生 changefeature 事件，列表刷新合并到微任务中，避免同一操作的多次同步渲染。ResizeObserver 通知地图容器变化，CSS 负责断点布局。

## 数据边界

只接受三个明确的几何类型，检查坐标数值、经纬度范围、最少节点数和多边形闭合。id 与名称有长度约束；重复 id 拒绝；未知属性丢弃。导入不是通用 GIS 解析平台，不支持 GeometryCollection/Multi* 或复杂拓扑修复。

新增复杂功能时优先扩展数据契约和测试，再扩展地图交互，不将校验散落在按钮回调中。
