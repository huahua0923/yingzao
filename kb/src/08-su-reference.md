# SketchUp 建模参考（读图成图的对标标准）

> **本项目的 3D 建模方式对标 SketchUp（SU）——目前最成熟的「CAD 平面图 → 建筑三维模型」工具。**
> SU 的底层原则一句话：**从 CAD 平面图的实际线条出发建模（读图成图），不臆造构件。**
> 每个构件都按图上真实尺寸/位置画成闭合面 → 推拉成体；开口=推穿；重复构件=组件阵列；材质区分（金属窗框/半透明玻璃/木门/灰墙）。
> 识别引擎每做一个构件，先问「SU 里这一步怎么做」；SU 没有的信号（线宽/层名被 ODA 剥离）才退回几何规则。详见 [[arch-rules-over-geometry]]。

## 0. SU 总工作流（五步）

1. **描墙线**——CAD 平面图当底图，沿墙描出闭合轮廓；**墙线是基础**，墙厚取图上画好的真实厚度。
2. **推拉成墙**——选中墙平面 Push/Pull 拉出墙高。
3. **加楼板**——每层墙顶封板，推拉出楼板厚（~200mm）。
4. **挖门窗洞**——墙面画门/窗轮廓，向内推穿成洞。
5. **建屋顶**——平顶封板 / 坡顶拉脊，最后贴材质。

对照我们管道：第 3/4/5 步已有（楼板、门窗洞、屋顶），**主要偏差在第 1 步的「墙」**（见下）。

## 0.5 3D 建模铁律（法线 / 去重 / 装配式）

**法线（normal）**：凹墙（如南凹口入口的两侧墙）的「内法线」不能靠「朝质心翻」——
质心在凹口侧，会把内法线翻反，导致窗洞沿法线凸出墙外，`ExtrudeGeometry` 的 hole 不在 shape 内
→ earcut 三角化乱掉（「点击后出现很多不相关图形」根因，2026-09 修）。
正确做法：从外皮中点往法线方向探一小步（0.02m），用 `pointInPoly` 判哪侧落在墙环（wall band）
内，落内的那侧才是「往墙里」的内法线。别用质心（凹墙必错）。

**去重（dedup，= SU 的 Union/OuterShell）**：同一物理实体只建一次、只画一次。
- 墙：多段墙皮 buffer 后 `unary_union` 合并（转角/T 字轻微重叠再并集），共享墙不重复建。
- 单源真相：floor JSON 是每层几何的唯一源，前端 building.html / GLB 都从它读，不各自重算。
- 重复构件（柱/踏步/门扇）= 实例化（InstancedMesh），不逐份 copy。
- 用户铁律：「构建物不用重复画」——违反就出重影/重面（z-fighting + 面叠加）。

**装配式搭建**：识别后把构件一个个「装配」上：需要就显示、错了就删、构件错了就改、少了就加；
构件库（`component_library.py`）沉淀每个构件的签名，后期直接调用复用。

## 1. 墙 Wall —— 最大的偏差

**SU 怎么做（两种取墙厚的方法，都合法）：**

| 方法 | 适用 | 做法 |
|------|------|------|
| **双线墙直接成面**（推荐，本项目） | CAD 画了双线墙 | 描内外两条墙线，两线之间的带就是墙的闭合面 → 直接推拉，墙厚 = 两线真实间距 |
| 偏移法（Offset） | CAD 只有单线/无墙厚 | 描外围轮廓 → 偏移工具向内 offset 墙厚 → 推拉 |

- **墙交接（转角 L / T 字）**：SU 要求墙「轻微重叠」再 **并集 Union / 实体外壳 OuterShell** 合并成一体，清除内部重叠面——这正是「外墙内墙不能重复建设」的 SU 版解法。
- **墙厚**：方案深度阶段用双线墙，读真实厚度（外墙 200/300mm、内墙 100/240mm，以图为准）。

**我们现在的问题**：理化楼用了「偏移法」的变体——`outline.buffer(-0.30)` 合成一圈外环，**丢弃了图上真正画的双皮墙线**（每根 2 点墙皮线各 buffer 0.15m，没把两皮配成一条 0.24/0.30m 真实厚度的墙）。这偏离了「读图成图」。

**正确做法（对齐 SU 双线墙直接成面）**：
- 把墙 LWPOLYLINE 拆成横/竖线段，平行两两配对（间距 ∈ [wall_min, wall_max]）→ 真实厚度墙矩形。
- union 成一片真实墙（外立面可见=外墙 0.30m、其余=内墙 0.24m，互不重叠）。
- 转角/T 字靠 `unary_union` + `wall_extend`（墙段沿走向外延，等价 SU 的「轻微重叠再并集」）。
- 参考实现：`backend/modeling/build_lihua_v3.py` 的 `pair_rects`（「原来的好」），以及 `geometry.py::pair_wall_faces`（已实现配对 + 真实墙厚，line 约定在用，lwpolyline 约定没用上）。

## 2. 门 Door

**SU**：门 = 墙面**开洞** + 门框（偏移 100mm）+ 门扇组件（50mm 厚板，双门可分扇）。
**我们**：门 = gap（挖洞）+ 门扇薄板（`build_lihua_v3::add_door_leaf`，双门左右两扇留缝）。已对齐；**缺门框**（可选，当前不做）。

## 3. 窗 Window / 玻璃 Glass

**SU**：窗 = 墙面**开洞**（推穿）+ **窗框**（金属材质）+ **玻璃**（半透明材质薄板，略内嵌于墙厚中线）。
**我们**：`facade_windows` 沿外墙直段等距生成**合成窗**（DXF 无窗；`synthetic` 标记默认不渲染），GLB/前端按同算法布窗；玻璃=半透明薄板。
**差距**：~~只有玻璃、无窗框~~ 前端 `building.html` 与 GLB `build_standard_glb.py` 均已对齐「铝合金窗框 + 玻璃」（`addWindowFrame`/`add_frame`：四根框料围住窗洞、跨满墙厚、外皮齐平；玻璃内缩进框、居中墙厚）。GLB 侧合成窗 `INCLUDE_SYNTHETIC_WINDOWS` 已置 True（313 窗开洞 + 框 + 玻璃，raycast 验证命中玻璃非实墙）。
**坑（法线）**：窗洞 = 在外墙直段上开洞，洞要横跨墙厚、整段落在墙皮内。合成窗中心落在外皮上，
「往墙里」的方向对凹墙（南凹口侧墙）不能用质心翻——见上「3D 建模铁律」；前端 `facadeWindows` 已改为
`pointInPoly` 探墙环内法线（`building.html`）。

**坑（墙皮 / 挖洞，2026-09 定论）**：窗洞横跨整个墙厚（外皮到内皮），**没法用「单个带洞 ExtrudeGeometry」挖穿**——
洞恰好贴在 band 的里外两条边界上，THREE 的 `ShapeUtils.triangulateShape → earcut` 会把贴边界的洞当退化**丢掉**（= 墙皮实心、玻璃被埋在墙里，raycast 打到外皮/内皮），或内缩 eps 又留下不透明墙皮盖住整扇窗（从外看仍是实墙）。
「0 NaN」是假信号：三角化不报错 ≠ 洞真的挖出来了。
**正确做法（= SU 推穿成洞）**：把窗带拆成一块块「墙段盒子」（`renderWindowBandSegments`），窗所在外皮直段按窗位切开留真缺口；内法线用 `pointInPoly` 探（凹墙不能用质心翻）。窗框跨满墙厚、外皮齐平；框/盒子的厚度轴要对齐内法线（`rotation.y = atan2(nx, -ny)`，凹墙内法线被翻转，固定 `atan2(dy,dx)` 会把厚度朝外）。

## 4. 楼梯 Stair

**SU**：参数化（层高/倾角 → 踏步高 150、踏步宽 300）+ 踏步**组件阵列** + 梯段 + 休息平台 + **扶手**（路径跟随 Follow-Me / 组件复制）。
**我们**：`detect_stairwells` 从踏步聚类出井（跑数 → 直跑/双跑/双分式），踏步按 nosing 堆叠成台阶。
**差距**：只建模踏步，**无扶手/栏杆**。

## 5. 电梯 Elevator

**SU**：先定**核心筒**（矩形平面）→ 井道墙 + 每层**电梯门** + **轿厢**（box 组件）。
**我们**：`detect_elevator_shafts`（墙 union 里的小矩形洞=竖井）+ 电梯门。
**差距**：有井道 + 门，**无轿厢**。

## 6. 柱 Column

**SU**：柱 = 足迹（矩形/圆）推拉成体，**组件阵列**复制。
**我们**：columns 从图读（INSERT 块 / LWPOLYLINE），`localize_columns` 已按图定位。已对齐。

## 7. 楼板 Slab / 地面 Floor

**SU**：每层墙顶封板，推拉 ~200mm 厚。
**我们**：slab 已有（`result["outline"]` = slab_poly，`add_slab` 挤出）。已对齐。

## 8. 屋顶 Roof

**SU**：平顶封板 / 坡顶拉脊（画中线 → 移动抬脊 → 屋檐厚度）。
**我们**：`result["roof"]`（roofT/parapetH/parapetT）+ 女儿墙；style 支持 flat/gable。已对齐。

---

## 差距清单（按优先级）

| 优先级 | 构件 | 差距 | 代码位置 |
|--------|------|------|----------|
| P0 | **墙** | 合成外环 → 改「双皮配对成真实厚墙」 | `geometry.py::derive_walls_and_outline` lwpolyline 分支 |
| ~~P1~~ ✅ | **窗** | ~~缺金属窗框~~ 前端 + GLB 均已补窗框 | `building.html::addWindowFrame` / `glb_common.py::add_frame` |
| P2 | **楼梯** | 缺扶手/栏杆 | `build_standard_glb.py` |
| P3 | **电梯** | 缺轿厢 | `build_standard_glb.py` |
| P4 | 门 | 缺门框（可选） | — |

## 关键外部参考

- [SketchUp 如何借助平面图搭建立体模型](https://www.gc5.com/3dmx/sujq/10426049.html)
- [SketchUp 导入 CAD 创建墙体](https://www.justeasy.cn/baike/3659.html)
- [SketchUp 实体工具（Union/OuterShell 去内部重叠面）](https://help.sketchup.com/zh-cn/sketchup/modeling-complex-3d-shapes-solid-tools)
- [SU 楼梯建模（踏步组件阵列 + 扶手路径跟随）](https://www.sketchupbar.com/portal.php?mod=view&aid=1129&page=1&mobile=no)
- [SU 玻璃门/半透明材质（玻璃和镜子分类）](https://soft.3dmgame.com/gl/3678.html)
