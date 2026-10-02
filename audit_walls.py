# -*- coding: utf-8 -*-
"""建好后对账（墙级）：图纸墙线 ↔ 交付墙 **双向** 逐段账 + 排除账 + 叠加图。

## 这件东西补的是哪个洞

`_dxf_audit.py`（2026-09-14 立）已经能量「漏墙率」，而且**跑得动**（2026-09-24 实测
c057 F1-F5 = 0.0%、c113 F0 = 4.7%）。它是本仓唯一那把**墙级**尺子，但那把尺子有五个洞：

  ① **单向**：只量「图纸有墙、模型没有」（漏），不量「模型有墙、图纸没有」（多建/歪建）。
     而人眼在 compare 页上看的正是两个方向（旧 overlay 的图例写着「红跑出去=多建」）。
  ② **只有率、没有段**：报「本层漏 4.7%」，不报「是哪一段、多长、在哪」。
     4.7% 落在 3406m 上 ≈160m —— 这句话对修图的人没有可操作性。
  ③ **不在红绿灯墙上**：`_dxf_audit.py` 全仓只在 `_audit_html` 里出现过，**不在**
     `backend/checks/` 的 A/B/C 任何一层 ⇒ 全库体检表上看不见它。
  ④ **排除是静默的**：`_source_wall_points(..., stats=None)` 的 `stats` 在唯一调用点
     （`audit_building`）**从来没人传** ⇒ 踏步带的排除账一直是空的；门带 `_door_zone_mask`
     连计数器都没有。⇒ 「排除了什么」屏幕上看不见（「量到 0」与「没量」同形）。
  ⑤ **曲要素整类隐形**：`_source_wall_points:216-219` 明确跳过 ARC/CIRCLE/SPLINE，
     注释写着「识别器从不建模（直墙= LWPOLYLINE/LINE）」—— **那行注释已经过期**：
     `backend/recognizer/curve_walls.py` 存在、`classify_line.py:20` import 它并在 `:194` 调用、
     `data/buildings` 的 **95 栋**里 **27 栋** profile 写着 `pair_curved: True`
     （2026-09-24 实测；判据 = `run_step.load_profile(n).pair_curved`，重跑即得。
      ★ 这里原先写的是「49 栋里 27 栋」—— 分子至今没变，**分母是当时的库容**，现在库容 95。）
     ⇒ 这 27 栋的曲墙在**唯一**那把墙级尺子的两侧都是隐形的。
     跳过本身**是对的**（不跳会被 c041/c026/c079 的 ~千% 虚漏刷屏），错的是**连账都不记**。

## 分工（一个判断只许有一份实现）

  · 「漏墙」这个**判断**仍然只有一份：本引擎直接调 `_dxf_audit` 的
    `_source_wall_points` / `_walls_geom` / `_door_zone_mask` / `_in_any_door_zone`，
    并用**同一套机制**（`prepared.prep(cov.buffer(WALL_DIST))` + `prep.covers(Point)`）
    和同一批常量（`SAMP` / `WALL_DIST` / `MIN_ENTITY`）算同一个数。
    `--cross-check` 会调 `_dxf_audit.audit_building(name)` 逐层比对**必须相等** ——
    两把尺子量同一个东西给不出同一个数，那就是多了一套实现（本仓栽过多次）。
  · 「错位 / 真缺墙」的**判别**也仍然只有一份：`_dxf_audit_report.classify`。
    本引擎只在漏墙率 ≥ 它自己的阈值（15%）时去**调**它，不重写。
  · 本引擎**自己拥有**的是三件新东西：双向的**段级归属**、**排除账**、**曲要素单列**。

## ① 的口径分解（v3，2026-09-24 引擎实测 —— 这一节是 ① 判定改口径的依据）

**病根在参考集自己身上，而且它只读不改。** `_dxf_audit._source_wall_points`（★只读、不许改）
取顶点用 `rv = list(e.get_points("xy"))` —— **不展开 bulge**；并且把 `ARC/CIRCLE/SPLINE`
整类跳过（`CURVED`，注释写「识别器从不建模」，那是为躲 c041/c026/c079 的 ~千% 假阳性）。
后果：**同一段弧，画成 ARC 会被忽略，画成带 bulge 的 LWPOLYLINE 就变成一根直墙** ——
c113 F0 实测该层 421 条 bulge 段，最大弦长 48.2m、最大矢高 24.2m（c113 F1）。
于是 ① 把「弧被弦替掉、交付墙按弧建在别处」读成「这一带没建墙」。

判定法：一个被判漏的样本，**同时**满足下面两条才扣（`ON_CHORD` / `MISS_CHORD_SAG`）：
  (a) 它落在某条 bulge 段的**弦**上（≤ 0.02m）；且那条弦的**矢高 ≥ 0.40m**（= `WALL_DIST`，
      弦≈弧的不必参与判定）；
  (b) 那条弦对应的**真弧**，在离该样本最近处**已被交付墙盖住**（≤ `WALL_DIST`）。
★ 两条**都不许省**，且方向不对称：**误扣会藏住一个真缺陷，不扣只是多报**（本仓铁律 36）
  ⇒ 宁可多报。T15 把两条各配一个对照（弦在、弧没建 ⇒ 5 点一个也不许扣；离弦 1.00m ⇒ 不许扣；
  离弦 0.01m ⇒ 必须扣），T16 从 DXF 进料侧验同一件事（墙图层 + 矢高 0.4 才收、0.04 不收、
  非墙图层不收、门槛可调），并**钉住弧顶在圆心对面** —— 矢高对「弧被镜像到弦另一侧」完全瞎
  （|s| 一样），只有逐点位置能认出来。

| 层 | ② 总账 `miss_pct` | 弦化扣掉 `miss_chord_m`（点数 / 矢高） | **真实档** `miss_real_pct` |
|---|---|---|---|
| c113 F0 | 4.7%（159.6m） | 107.4m（307 点；p50 7.0 / mx 7.13） | **1.5%**（52.1m） |
| c113 F1 | 1.0%（27.6m） | 5.6m（16 点；p50 23.8 / **mx 24.2**） | **0.8%**（22.0m） |
| c113 F2 | 2.6%（68.2m） | 24.1m（69 点） | **1.7%**（44.1m） |
| c113 F3 | 3.5%（98.3m） | 24.8m（71 点） | **2.6%**（73.5m） |
| c113 F4 | 0.8%（7.0m） | 0（本层无过线弦） | 0.8%（7.0m） |
| c057 F0-F5 | 0.6% / 0.0%×5 | 0（**阴性对照**：该栋弦化无从谈起） | 0.6% / 0.0%×5 |

⇒ 口径：**`miss_pct` 是总账、也是 `--cross-check` 与 `_dxf_audit` 逐层比的那个数**
  （两把尺子量同一个东西必须给同一个数）；**判定只看 `miss_real_pct`**。
  c113 F0 总账里 67.3% 是尺子造的 —— 拿总账判就是把假阳性当缺陷。
⇒ 弧的构造**只有一份实现**：`bulge_to_arc` 只当「圆心 + 半径」用，**扫掠方向按 DXF 自己的
  定义**（`b>0` = 逆时针），起止角自己 `atan2`；★**不许用库返回的 `a1/a2` 排序** ——
  实测真图上按 `(a1+a2)/2` 取角中点会落到**对径点**（197/421 条），而手算小样本上它恰好全对
  （「小样本全对、真数据错一半」的口径不许用）。认证见 `_scratch/_stray_bulge_arcapi.py`。

## ② 的口径分解（v2，2026-09-24 引擎实测 —— 这一节是 ② 判定改口径的依据）

洞① 一直没补，因为 ② 这个方向**没有第二把尺子**：① 的漏墙率可以拿 `_dxf_audit` 的独立
实现做 `--cross-check`，② 报出 18~26% 却无处对账。补法是**换参考集**：
把「参考点」换成**图纸的线几何**（`layer_geoms`，展弧、七类线状图元全收、**故意不过滤**），
离它 > 0.40m 的才算「图纸上真的没有」。两份参考各自是一份距离数组（判近/判远与报距离同源）。

| 口径 | 含义 | c113 F0 | c057 F1 |
|---|---|---|---|
| 总账 `stray_pct` | 对**掩蔽后**的参考点集 > 0.40m | 24.0%（4199 点 / 1469.6m） | 18.5%（1803 点 / 631.0m） |
| A 门带掩蔽 `stray_door_n` | 把门区里被调用方删掉的图纸墙线放回来就解释得了 | 6.0%（1058 点） | 16.7%（1628 点） |
| B 墙图层几何 `stray_wall_pct` | 对**墙图层全部线状图元（展弧）** > 0.40m | 0.9%（153 点 / 53.5m） | 0.0%（0 点） |
| **C 任何图层几何 `stray_any_pct`** | ★**判定档**：对**任何图层**的线几何 > 0.40m | **0.7%（122 点 / 42.7m）** | **0.0%（0 点）** |

★ **A 与 B/C 是两条轴，不互斥**：A 量的是**参考点集**（门带掩蔽），B/C 量的是**几何**。
  拿 A 去减 B 是一个**没量过**的数。等级顺序 A ⊃ B ⊃ C 只在同一轴内有意义。
★ **解释账**：`stray_*_n` 是**不解释**的点数，**解释**掉的在 `stray_wall_layers` 里 ——
  c113 F0 是 `{'4.2墙体': 17337}`，17337 + 153 = 17490 = 本层边线采样数 ✓（c057 F1 是
  9763 + 0 = 9763 ✓）。**这两个数不是矛盾**，是两个方向（我第一次读时判成了矛盾，记在这里）。
★ **E 类的距离分布**（`stray_any_dist`）：p10 0.42 / p25 0.46 / **p50 0.53** / p75 0.65 /
  p90 0.78 / **max 1.04m，5m 以外 0 点**。⇒ 不是「有一片墙凭空多出来」，而是 **0.40m 这条线
  切在一个连续分布的中段**（成因是口径：交付墙边线是两圈壳，参考集是单根线）。
  「阈值太紧」和「模型多建」在计数上同形，**只有距离分布能把它们分开**。
★ **c057 F0-F5 的阴性对照**：总账 18.4~18.5%，其中 90% 是门带掩蔽；墙图层档与任何图层档
  **六层全 0.0%** ⇒ ② 那一栏对这个栋**一个字都不说**（v1 拿总账判，会报 18 个百分点的假红）。

### 旧表为什么错（v1 的 B/C/D/E 四行 —— 已作废，作废理由要留着）

v1 那一版的口径分解用的是 `_scratch/_stray_explain_probe.py` / `_stray_resid_layer_probe.py`，
它的「墙图层几何」取法是：`LWPOLYLINE` 取 `get_points("xy")`（**弦化**）＋
`ARC/CIRCLE/SPLINE` 只取圆心一点、随后因 `len(lv) >= 2` 不成立而**整类丢掉**。
⇒ 那是一份**退化**的参考集：**弧没了、曲墙成了弦**；参考集小 ⇒ 解释得少 ⇒ 残余虚高。
同一批 4199 个离群点，只换参考集取法（探针 `_scratch/_stray_wallref_probe.py`）：

| 取法 | 条数 / 总长 | 解释不了的残余 |
|---|---|---|
| (i) 引擎法：七类线状图元 + 展弧 | 796 条 / 5222.4m | **143 点 = 0.8%** |
| (ii) 半保真：去掉 ARC/CIRCLE/SPLINE，仍展弧 | 4116 条 / 22346.8m | 375 点 = 2.1% |
| (iii) 旧探针法：只直墙类 + 弦化 | 2755 条 / 19503.7m | **1539 点 = 8.8%**（≈探针报的 9.5%） |

★ 反直觉但已被量实：**(i) 的参考集最小（条数 1/5、总长 1/4），解释得却最多** ——
  它多出来的那些条，要么是同一栋**别的楼层**画在同一图层上的几何（与本案无关），
  要么根本不保真。⇒ 「参考集更全」**不许用条数或总长判断**，要看它是不是**保真**。
★ 于是旧表的 C 3.9% / D 4.4% / **E 3.1%（540 点）** 全是这把尺子量的，方向是**虚高**；
  引擎的数：B 0.9%（153 点）、**C（判定档）0.7%（122 点 = 42.7m）**。
★ 两个分母（**153 与 143 不是矛盾，是分母不同**）：153 的分母是**全部** 17490 个边线采样，
  143 的分母是 **4199 个离群点**。差的 10 点已逐点量过（`_stray_walltier_reconcile.py` /
  `_stray_chord_src_probe.py`）：它们的最近图元都是**带一段 bulge 的 LWPOLYLINE**，
  顶点折线离它们 0.02~0.50m、**展弧**离它们 0.42~0.68m，且它们**正好落在交付墙上**
  （离交付墙 0.00m）⇒ 是「参考点集按弦、② 的几何按弧」这一件事在 0.06% 尺度上的投影，
  **不是缺陷**（10 点全部落在此档，也因此被算进 122 里）。
★ 反方向也量过：把 ② 的参考集**也**改成弦化取法，任何图层残余从 122 **涨到 533 点**
  ⇒ 弦化对 ② 是**更坏**的尺子（② 问的是「图纸上有没有东西」，图纸上的弧就是弧）。
  **① 的参考集是弦、② 的参考集必须保真 —— 两边各自保真，不许把一处的口径搬到另一处。**

⇒ 因此 ② **不再用一个数当结论**：判定只看 **C（任何图层都无对应物）**，A/B 如实列在 notes 里，
   「口径损失」与「模型多建」在屏幕上**必须不是同一行字**。

## ③ 的量纲与作用域（v4，2026-09-24 —— 这一节是 ③ 判定改口径的依据）

③ 是 v1 起就**单列**的那一档（曲要素从不混进 ① 的分母）。v4 之前它有两处错，
**两处都是「屏幕上很好看」的错**（本仓铁律 23：判据的三种坏法），而且方向都朝**假红**。

### (a) 量纲错：`curve_m = 点数 × SAMP`

`curve_points` 取点走 `ezpath.make_path(e).flattening(A.SAMP)` —— `flattening(distance)`
的 `distance` 是**矢高（曲线与折线的最大偏离）**，不是**步长**；实现里还有**最小分段数**。
⇒ 点距与曲线长度**无关**（实测 ARC 恒 65 点、CIRCLE 恒 129 点；
c043 F0 点距中位 0.0248m、c113 F0 0.0373m，而 `SAMP = 0.35`）⇒ 米数虚高一个数量级：

| 层 | 真长（各实体展开长度之和） | `点数 × SAMP`（③ 旧口径） | 倍 |
|---|---|---|---|
| c043 F0 | 25.2m | 359.1m | **14.2×** |
| c113 F0 | 153.8m | 1197.7m | **7.8×** |
| c057 F1 | 2.2m | 45.1m | **20.5×** |

★ 最刺眼的一点：**`curve_points` 内部本来就算了真实长度** ——
  `L = sum(dist(lv[i], lv[i+1]))`，用它做 `L < A.MIN_ENTITY` 的短实体过滤，
  **然后丢掉**，回报时改写成 `点数 × SAMP`（旧 `:524` / `:707`）。
  ⇒ v4 把那个 `L` 留下来（`curve_segments` 返回 `(pts, w)`，`w[i]` = 点 i→i+1 的段长）。
★ 为什么「比值」那两栏骗过了人：**分子分母一起错** ⇒ `curve_miss_pct` 看着还挺合理
  （c043 F0 报 14.9%，按真长算是 14.4%）—— **一个自洽的数不是证据**（本仓铁律 18/22）。

### (b) 作用域错：分母里混着「识别器根本不收的东西」

识别器自己的规则（`classify_line.py:172-181`、`classify.py:187-216`，**只读、一个字不改**）：

- `ARC` 且 **r ≥ `CURVE_MIN_R`(2.0m)** → 曲墙（两条识别路径**都**收 ⇒ 任何栋都在册）；
- `ARC` 且 r < 2m → **门扇开启弧/装饰弧**，`classify_line.py:174` 原注
  「半径 < CURVE_MIN_R(2m) 的是门扇开启弧/装饰弧, 必须排除, 否则每扇门长一堵墙」；
- `CIRCLE` → **两条路径都不收**（`classify_line` 尾注「TEXT/MTEXT/CIRCLE 标注忽略」）；
- `ELLIPSE`（长半轴 < 1m）/ 走 `classify_line` 的栋的所有 `ELLIPSE`/`SPLINE` → 也不收。

而 ③ 旧版把墙图层上**所有** ARC/CIRCLE/SPLINE/ELLIPSE 都算进分母。实测（`_scratch/_curve_len_gauge.py`）：

| 层 | 旧报 | 分母其实是 | 在册（真曲墙） | 新判定 |
|---|---|---|---|---|
| c043 F0 | GAP **14.9%** | 18 段门开启弧（r≈1.00~1.28m），**一段曲墙都没有** | 0 段 / 0.0m | **不判**（PASS） |
| c113 F0 | GAP **36.1%** | 4 段真弧 70.4m；另 46 个柱/圆符号（39.0m）+ 27 段门弧（32.5m）+ 8 个符号椭圆，占分母 **54%** | 4 段 / 70.4m | 漏 **5.4%**（WATCH） |
| c057 F1 | **17.8%** | **一个 r≈0.35m 的圆**（45.1m 的「曲要素」全是它） | 0 段 / 0.0m | **不判**（PASS） |

⇒ ③ 的两处修法都是**同一个方向**：**分子分母都改成「识别器真的会当墙的那批曲线的真实长度」**。
   出局的每一类**计数 + 记米数**进 `led["curve_excl"]`，并在报告里印出来 ——
   「本层无曲要素」与「有，但都出局了」在屏幕上**必须不是同一行字**（铁律 23(b)）。
⇒ 判漏的规则与 ① 同构、但落在**段**上：一段算漏**当且仅当两个端点都没被盖住**
   （保守：只有一端在外的那段不计，它至多半段，且绝不虚增分子）。

## 用法（手解析 argv，**不认 `--help`**；不认识的开关/楼名一律硬错，绝不回落成全量）

    python -u audit_walls.py c113 c057            # 只这两栋（写 JSON + 叠加图 + 楼内 index）
    python -u audit_walls.py                      # 全库（**只有此时**才写全仓总目录）
    python -u audit_walls.py c057 --no-overlay    # 只出数、不出叠加图（体检用，快）；
                                                  # ★ 楼内 index.html **照样写**，逐层印「未出图」——
                                                  #   页与 JSON 必须同一轮次（见下面「产物」那条）
    python -u audit_walls.py c113 --diagnose      # 漏墙率≥15% 的层顺带问 _dxf_audit_report
    python -u audit_walls.py c113 c057 --cross-check   # 与 _dxf_audit 逐层比对漏墙率
    python -u audit_walls.py --selftest           # 尺子自己的十二组（含三个阴性对照）
    GYM3D_WALL_AUDIT_PROBE_OUT=<目录> python -u audit_walls.py c113 --probe
                                                  # ★ **门禁轮**：真跑一遍，产物只写 <目录>，
                                                  #   不碰 META/<楼>.json、不写楼内页面、不画 PNG

  退出码：0 = 全部落在 PASS/NOT_APPLICABLE；1 = 有 GAP（那是**数据**的红，不是尺子坏了）；
          2 = 有 UNAVAILABLE（**没量成**，与「量到 0」必须分开）或参数错。

产物（四条路径互不覆盖 —— 本仓铁律：一件产物一个路径）：
  · data/_meta/wall_audit/<name>.json         机器读（带 criterion_version + 尺子指纹）
  · data/buildings/<name>/audit/index.html    人眼看（**每一趟都写**，与 JSON 同轮次）
  · data/buildings/<name>/audit/*.png         叠加图（`--no-overlay` 那趟不写）
  · data/buildings/_wall_audit.html           全仓总目录（**不带楼名**时才写）
  · <PROBE_OUT_ENV>/<name>.json               `--probe` 那趟的唯一产物；上面四条一条都不动

★ **`--probe` 与 `--no-overlay` 的区别**（两者的名字都像"少做点事"，很容易混）：
  `--no-overlay` 少做的是**图**，数**照样写进被测栋的目录**；
  `--probe` 少做的是**写** —— 一个字节都不落在 `data/buildings/` 与被测栋的
  `META/<楼>.json` 里。门禁**必须**用后者：它每栋都要跑一次，
  用前者就等于「量一次、把被测栋的视觉页抹一次」（实测损坏见 PROBE_OUT_ENV 那段）。

★ 为什么 index.html 不跟 `--no-overlay` 绑在一起：绑过一版，实测留下的是
  **页与表来自两个轮次**（c057：页面 19:34 那次带图写的，JSON 被 19:40 那次重写）
  —— 同一目录里躺着一对互相矛盾的产物，而屏幕上没有任何东西说这件事
  （本仓铁律 24：「这份数是旧尺子量的」与「这份数是对的」长得一样）。
  页面一律重写，`--no-overlay` 时逐层印红字「未出图」，这就把差异**印出来**了。
  ★ 三份指纹必须同源：`when` 由循环里**一次** `strftime` 算好，JSON 与页面共用同一个变量，
  不许各自再调一次时间（差一秒就说不清谁新）；`self_sha12()` 进程内只读一次盘，
  否则全库跑到后半程被人改了文件，后写的产物会盖上一把它**没用过**的尺子的指纹。

★ 纪律：本文件**只读** data/ 下既有交付件，只**写**上面三个路径；不改任何生产代码，
  不改 `_dxf_audit.py` / `_audit_report.py`（按用户令：调试好的代码禁止再修改）。
"""
import glob
import io
import json
import math
import os
import sys
import time
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend", r"D:\gym3d"]

import matplotlib
matplotlib.use("Agg")                     # 必须在任何人 import pyplot 之前定下来
import matplotlib.pyplot as plt
import numpy as np
import ezdxf
import shapely
import shapely.geometry as sg
from ezdxf import path as ezpath
from ezdxf.math import bulge_to_arc       # 弧的圆心/半径只此一处（见 bulge_chords）
from shapely import STRtree
from shapely import points as shpoints
from shapely.ops import nearest_points    # 「弦上那点到它的弧最近处」用

import _dxf_audit as A                    # ★ 复用它的判断与常量，一个字不改
import _dxf_audit_report as DR            # ★ 复用「错位/真缺墙」判别（import 安全：main 有守卫）
import _dxf_cad_render as R               # ★ 复用它的 _entity_floor（定位规则只许有一份）
import run_step
from backend.state.roster import sha12    # 指纹规则全仓只有这一份
from recognizer.profile import to_local, floor_of
# ★ ③ 的**作用域与半径阈值**只此一处来源：识别器自己的常量与判据（见 curve_in_scope）。
#   抄一份数进本文件 = 同一事实两份写法，上游一改就漂（本仓铁律 18）。
import recognizer.classify as CL

# 中文不设字体会渲染成方框（约定抄 _dxf_cad_render.py:21-22）
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DengXian"]
plt.rcParams["axes.unicode_minus"] = False

BASE = r"D:\gym3d\data\buildings"
META = r"D:\gym3d\data\_meta\wall_audit"
SELF = os.path.abspath(__file__).replace("\\", "/")

#: `--probe`（**门禁轮**）把产物写到这里，而不是 META，且**不碰**楼内页面与 PNG。
#: 为什么非有这条出路不可（2026-09-24 实测的自造缺陷，已造成实物损坏）：
#:   门禁 B5 每查一栋都要调本脚本一次，而 `--no-overlay` **照样重写**
#:   `META/<楼>.json` 与 `data/buildings/<楼>/audit/index.html`。于是
#:   「门禁量一次」= 把被测栋的视觉页抹成逐层红字「未出图」——
#:   实测 c001/c103/c113 三栋的 `<img>` 从 6/6/5 变成 **0/0/0**，而 PNG 就躺在旁边。
#:   ⇒ 通则：**量具不许改变被测对象**。门禁要的是「真跑一遍、不读旧产物」，
#:     这两件事与「把数写进被测栋的交付目录」本来就没有关系 —— 分开即可。
#: ★ 路径由**调用方**用环境变量给，不给就硬错。猜一个临时目录，等于把产物静默写到某处
#:   （本仓铁律 16：产物落在哪都行 = 出问题时无从判断它落在哪）。
PROBE_OUT_ENV = "GYM3D_WALL_AUDIT_PROBE_OUT"

#: 判据语义改了（分组方式/量纲/阈值/排除规则）就 +1；指纹另由 self_sha12() 机械给出。
#: 两个都要：手写的会忘，机械的说不清语义（铁律 24）。
#: v2（2026-09-24）：② 由「一个数」改成**口径分解**，判定改看 E 类（任何图层都无对应物）。
#:   依据写在文件头「② 的口径分解」一节 —— 旧口径下 c057 F1 的 18.5% 里 0.0% 是真的。
#: v3（2026-09-24）：① 同样改成**口径分解**，判定改看**真实档**（扣掉参考集把弧弦化造
#:   出来的那批）。依据写在文件头「① 的口径分解」一节 —— 旧口径下 c113 F0 的 4.7% 里
#:   92.3% 的点落在弦上。⇒ 两个方向现在都自带「总账 / 判定档」两栏。
#: v4（2026-09-24）：③ 改**量纲**（曲长按真实段长，不再 `点数 × SAMP`）＋ 改**作用域**
#:   （只收识别器真会当墙的曲线，门弧/整圆/符号椭圆出局并计数）。依据写在文件头
#:   「③ 的量纲与作用域」一节 —— 旧口径下 c043 F0 的 14.9% 与 c057 F1 的 17.8% 都是
#:   假红（那两层**一段曲墙都没有**），c113 F0 的 36.1% 真值是 5.4%。
CRITERION_VERSION = 4

#: 漏墙率的两条线。**15 不是新发明的数**：`_dxf_audit._audit_html` 的内联告警线
#: 与 `_dxf_audit_report.THRESH` 都是 15.0，这里跟着它们，不另立一套。
MISS_WATCH = 5.0
MISS_GAP = 15.0

#: 「多建/歪建」的两条线是 **试行**（本仓从没有过这个方向的数 ⇒ 没有历史可跟）。
#: ⇒ 不假装它有依据：全库分布出来之后按分位数定，定下来之前它只到 WATCH 为止。
STRAY_WATCH = 5.0
STRAY_GAP = 15.0
STRAY_MIN_M = 20.0        # 交付墙边线短于此的层不按比值判（小分母的比值会发疯）

#: 扫「所有图层的几何」时的**剪枝余量**：只对「离 E 类候选点 ≤ 此值」的图元做采样。
#: 必须 **> WALL_DIST** —— 它是**保守**的：宁可不剪，也不许把 0.40m 内的东西筛掉
#: （量程卡在待检对象之上，就会放行它本该拒绝的东西；本仓栽过）。
STRAY_ANY_PAD = 0.45

#: ① 的**弦化档**判据（v3 新增，依据写在文件头「① 的口径分解」一节）。
#: 参考集 `_dxf_audit._source_wall_points` 取顶点用 `list(e.get_points("xy"))` ——
#: **不展开 bulge**，于是图纸上一条弧在参考集里成了一根**直弦**
#: （实测 c113 F0：弦长 max 48.2m、矢高 max 24.2m；c057 F1 一条都没有，max 0.298m）。
ON_CHORD = 0.02           # 「这个样本落在某根弦上」的容差：弦上的样本距弦恰为 0
#: 弦离弧 ≥ 此值才算「这根弦不可能是图纸上的线」。
#: **不是新发明的数**：它就是判定「盖没盖住」那条同名的容差 `A.WALL_DIST` ——
#: 弦与真弧的偏离一旦超过**尺子自己的分辨力**，这把尺子就无法再把它当成「图纸上的线」。
MISS_CHORD_SAG = A.WALL_DIST

#: `layer_geoms` 收哪些图元类型 —— **只收线状图元**。
#: 文字(TEXT/MTEXT)/标注(DIMENSION)/填充(HATCH/SOLID)/块参照(INSERT 已摊开) 一律不算
#: 「对应物」：一条墙在图上的对应物是**墙线**，不是压在它上面那一行房间号。
#: ★ 这条界是**语义**上的，不是省事 —— 若 `TEXT` 也算，就会冒出
#:   「墙下正好标了个号 ⇒ 判它图上有东西」这种**把真缺陷藏起来**的绿。
_GEOM_TYPES = ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "SPLINE", "ELLIPSE")

CLUSTER_CELL = 0.5        # 段级归属的网格；必须 > A.SAMP(0.35)，否则一条直线被切碎
CURVE_MIN_M = 3.0         # 曲要素短于此不值得判（圆角/小的弧线）

#: 分布池下限。**不是新发明的数**：`_dxf_audit.py:449` 就是
#: `pool = [r for r in allres if r["src_m"] >= 50]`（那条既有的全库分布用的正是它）。
#: 跟着它，我的分布才能与 `_dxf_audit.html` 的 296 层**逐层可比**。
#: ★ 它只筛**分布**，不筛**判定**：30m 墙全漏也是 100%，照样判。池内池外都要打进输出。
POOL_MIN_SRC_M = 50.0

FLAGS = ("--no-overlay", "--probe", "--diagnose", "--cross-check", "--selftest", "--quiet")


_SELF_SHA12 = None


def self_sha12():
    """本文件的 sha256 前 12 位 —— 产物自带「这是哪把尺子量的」。

    ★ **只读一次盘**（进程内缓存），不是每次调用重读：全库跑十几分钟，期间只要有人
      动了本文件，重读会让**后半程的产物盖上新 sha**，而它们跑的仍是**旧代码**
      ⇒ 产物会宣称一把它没用过的尺子。本仓铁律 24 的成因正是「时间」，
      防法就是让「进程用哪份代码」与「产物写哪个指纹」**恒出自同一次读盘**。
    """
    global _SELF_SHA12
    if _SELF_SHA12 is None:
        with open(SELF, "rb") as fh:
            _SELF_SHA12 = sha12(fh.read())
    return _SELF_SHA12


# ── 纯核心：不碰 DXF，--selftest 就靠这一层能逐格验 ──────────────────────

def cluster_points(pts, cell=CLUSTER_CELL, seg_w=None):
    """把一串采样点并成「连续段」。返回 [{idx, n, len_m, cx, cy, x0, y0, x1, y1}]，长的在前。

    为什么按**空间连通**分而不是按实体/直段（run）分：人要看的是
    「图纸上哪一段没有红墙压着」—— 那是空间的连续，不是画图时恰好被拆成几个实体的拓扑。

    判据：`cell` 网格的 8 邻域连通。取 cell=0.5 > SAMP=0.35 ⇒ 同一条线上相邻两次采样
    必落在同格或邻格（步长小于格宽），所以一条连续墙线不会被判成两段。

    `seg_w`（可选）＝与 `pts` **等长**的段重表：`seg_w[i]` = 「点 i → 点 i+1」的**真实**
    长度（米），末点/跨实体写 `None`；给了就按它求和，`len_m` 于是是真实长度。
    ★ 为什么要留一个开关：本函数有三处调用，其中两处（①②）的点是**等步**采样的
      （`_source_wall_points` 每 0.35m 取一个）⇒ 那里 `n × SAMP` 本来就是对的；
      只有**曲要素**那批点距与 SAMP 无关（`flattening(A.SAMP)` 的入参是**矢高容差**，
      实测点距 0.019~0.037m）⇒ 它是唯一需要真长度的地方。
      **不能全局改**：改了会把 ①② 的米数一起改错（本仓铁律 26：只动要动的那一个变量）。
    """
    cells = {}
    for i, (x, y) in enumerate(pts):
        cells.setdefault((int(math.floor(x / cell)), int(math.floor(y / cell))), []).append(i)
    seen, out = set(), []
    for key in cells:
        if key in seen:
            continue
        stack, comp = [key], []
        seen.add(key)
        while stack:
            k = stack.pop()
            comp.extend(cells[k])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nk = (k[0] + dx, k[1] + dy)
                    if nk in cells and nk not in seen:
                        seen.add(nk)
                        stack.append(nk)
        comp.sort()
        gp = [pts[i] for i in comp]
        gx = [q[0] for q in gp]
        gy = [q[1] for q in gp]
        if seg_w is None:
            len_m = round(len(gp) * A.SAMP, 1)
        else:
            len_m = round(sum(seg_w[i] for i in comp
                              if i < len(seg_w) and seg_w[i] is not None), 1)
        out.append(dict(idx=comp, n=len(gp), len_m=len_m,
                        cx=round(sum(gx) / len(gx), 2), cy=round(sum(gy) / len(gy), 2),
                        x0=round(min(gx), 1), y0=round(min(gy), 1),
                        x1=round(max(gx), 1), y1=round(max(gy), 1)))
    out.sort(key=lambda c: -c["n"])
    return out


def boundary_samples(cov, step=A.SAMP):
    """交付墙覆盖区的**边线**采样点（局部米）。

    为什么采边线而不是轴心线：轴心线要中轴提取（本仓没有，也不该为此新写一个）；
    边线是这份几何**本来就有**的东西。代价是同一面墙有两个面 ⇒ 边线长约是轴长的 2 倍，
    所以「交付侧」的数**不与「图纸侧」相减**，各自只跟自己的历史基线比（口径写在 measure 里）。
    """
    try:
        seg = cov.boundary.segmentize(step)
        xy = shapely.get_coordinates(seg)
    except Exception:
        return []
    return [(float(a), float(b)) for a, b in xy]


def stray_samples(xs, src, tol=A.WALL_DIST):
    """在边线采样点里挑出「附近没有图纸墙线」的那些 + 各自到最近图纸点的距离。

    返回 (pts, dists, near_n)。`dists` 与 `pts` 等长（无图纸点时全为 None）。

    ★ 这里踩过两个坑，都是**同一处**的两种写法，且**都不报错、只是数错**：

    ① `query_nearest(..., return_distance=True)` 返回的是 **(下标, 距离)**，顺序与本能的相反。
       写反了就把一个**下标**当中位距离报出去。
    ② **更隐蔽的一条：默认 `all_matches=True`，并列会多出行。** 本层源码点里有**完全重复**
       的点（同一条墙线被两个实体各画一次），于是并列是家常便饭 —— c113 F0 实测
       `idx.shape=(2, 18445)` 而查询点是 **17490** 个。多出来的 955 行让 `dists[i]`
       **不再对应** `xs[i]`，我却按 `dists[i]` 取值 ⇒ 「近/远」与「距离」变成两份数据。
       后果不是异常，是**自相矛盾**：报「离群 24%、其中位最近距离 0.15m」——
       而「离群」的定义就是 >0.40m，中位数根本不可能落在 0.15。
       （铁律 18：自洽的数也可能是错的；这次是**不自洽**才露的馅。）

    ⇒ 出路是**让两个判断出自同一个数组**：`near = dists <= tol`。
      dwithin 谓词整个不要了 —— 只要还有两处算「近不近」，它们就有机会不一致。
      `all_matches=False` 保证一行输入一行距离，另有**对齐自检**兜底（对不上就抛，
      不许悄悄按错行取值）。T12 用「带重复点的合成源集」把这件事钉住。
    """
    if not xs:
        return [], [], 0
    if not src:
        return list(xs), [None] * len(xs), 0
    tree = STRtree(shpoints(np.asarray(src, dtype=float)))
    q = shpoints(np.asarray(xs, dtype=float))
    idx, dists = tree.query_nearest(q, return_distance=True, all_matches=False)
    idx = np.asarray(idx)
    dists = np.asarray(dists, dtype=float).ravel()
    if len(dists) != len(xs):
        raise RuntimeError("query_nearest 返回 %d 个距离、采样点 %d 个 —— 对不上行，"
                           "按行取值会得到错的距离（先查 all_matches 是否又变回默认）"
                           % (len(dists), len(xs)))
    if idx.ndim == 2 and idx.shape[0] == 2 and not np.array_equal(
            idx[0], np.arange(len(xs))):
        raise RuntimeError("query_nearest 的输入下标不是 0..N-1 顺序 —— 距离数组与采样点错位")
    near = dists <= tol
    pts = [xs[i] for i in range(len(xs)) if not near[i]]
    dd = [float(dists[i]) for i in range(len(xs)) if not near[i]]
    return pts, dd, int(near.sum())


def stray_samples_geom(xs, geoms, layers=None, tol=A.WALL_DIST):
    """同 `stray_samples`，但参考是**线几何**（精确点→线距离）。返回 (pts, dists, near_n, 层账)。

    两条纪律与 `stray_samples` **完全一样**（那是 T12 钉下来的）：
      · `all_matches=False` + **对齐自检**（对不上就抛，不许按错行取值）；
      · 「判近/判远」与「报出去的距离」出自**同一份数组** `dists`。
    `layers` 给图层名（与 geoms 并行）时，顺带数出**近的那些点是被哪个图层解释的** ——
    口径损失长什么样必须能看见，否则「3.1% 之外的那 20.9%」就成了一笔无名的账。
    """
    if not xs:
        return [], [], 0, {}
    if not geoms:
        return list(xs), [None] * len(xs), 0, {}
    tree = STRtree(geoms)
    q = shpoints(np.asarray(xs, dtype=float))
    idx, dists = tree.query_nearest(q, return_distance=True, all_matches=False)
    idx = np.asarray(idx)
    dists = np.asarray(dists, dtype=float).ravel()
    if len(dists) != len(xs):
        raise RuntimeError("线几何参考：返回 %d 个距离、采样点 %d 个 —— 对不上行"
                           "（先查 all_matches 是否又变回默认）" % (len(dists), len(xs)))
    if idx.ndim != 2 or idx.shape[0] != 2 or not np.array_equal(idx[0], np.arange(len(xs))):
        raise RuntimeError("线几何参考：配对下标形状 %r 不是 (2, N) 的输入序 —— 距离与点错位"
                           % (idx.shape,))
    near = dists <= tol
    cnt = {}
    if layers:
        for j in idx[1][near]:
            k = layers[int(j)]
            cnt[k] = cnt.get(k, 0) + 1
    pts = [xs[i] for i in range(len(xs)) if not near[i]]
    dd = [float(dists[i]) for i in range(len(xs)) if not near[i]]
    return pts, dd, int(near.sum()), cnt





def classify_floor(rec):
    """→ (status, why, notes)。

    status 用 `findings.Status` 的同一套词（PASS/WATCH/GAP/UNAVAILABLE/NOT_APPLICABLE），
    这样 B5 那条 check 不用翻译。

    ★ 曲要素未开识别时**不报红**，只报 WATCH 并写明盲区 —— 报了红就是
      c041/c026/c079 那次 ~千% 虚漏的老毛病（假阳性会被学会忽略）。
      但**必须露出来**：「这类不在判定范围内」和「这类没问题」不许同形。
    """
    lv = []          # (rank, status, why)；rank 大者胜

    # ① 图纸 → 交付（漏）★ v3：判定看 **真实档**（扣掉「参考集把弧弦化」造出来的那批）
    #   总账（`miss_pct`）**照样报**，而且照样是 `--cross-check` 与 `_dxf_audit` 比的那个数
    #   —— 两把尺子量同一个东西必须给同一个数。只是**判定不看它**：实测 c113 F0 总账里
    #   92.3% 是尺子造的（参考集把弧弦化），拿它判就是把假阳性当成缺陷。
    mr = rec.get("miss_real_pct")
    if rec["miss_pct"] is None:
        # src_n==0 有两种截然不同的原因，**不许同形**（本仓铁律：空输出不是「没有数据」）
        if rec.get("curve_n", 0) > 0:
            lv.append((0, "NOT_APPLICABLE", "本层墙图层上只有曲要素（直墙账不适用）"))
        else:
            lv.append((1, "WATCH", "本层图纸墙图层上没有任何可用墙线（**没量到**，不是通过）"))
    elif mr is None:
        # ★ 弦化档没跑起来 ⇒ **不许**退回总账去判（那正是要修的病，同 ② 的处置）
        lv.append((1, "WATCH", "漏墙总账 %.1f%%（%.1f/%.1fm），**但弦化档没跑**"
                   "（真实档未知）⇒ 本层不判「漏墙」"
                   % (rec["miss_pct"], rec["miss_m"], rec["src_m"])))
    elif mr >= MISS_GAP:
        lv.append((2, "GAP", "漏墙 **%.1f%%**（真实档 %.1f/%.1fm）≥ %.0f%%"
                   "（总账 %.1f%%，其中 %.1f%% 是参考集把弧弦化造的，已扣）"
                   % (mr, rec["miss_real_m"], rec["src_m"], MISS_GAP,
                      rec["miss_pct"], round(rec["miss_chord_m"] / max(rec["src_m"], 1e-9) * 100, 1))))
    elif mr >= MISS_WATCH:
        lv.append((1, "WATCH", "漏墙 **%.1f%%**（真实档 %.1f/%.1fm）"
                   "（总账 %.1f%%；已扣掉参考集弦化造的 %.1f%%）"
                   % (mr, rec["miss_real_m"], rec["src_m"], rec["miss_pct"],
                      round(rec["miss_chord_m"] / max(rec["src_m"], 1e-9) * 100, 1))))
    else:
        # ★ 显式写出「这个方向查过且干净」，并把**扣了多少**一起印出来 ——
        #   「扣掉一大半之后才合格」与「本来就干净」不许同形（本仓铁律）。
        lv.append((0, "PASS", "漏墙 %.1f%%（真实档 %.1f/%.1fm；总账 %.1f%%，"
                   "其中参考集弦化造的 %.1fm 已扣）"
                   % (mr, rec["miss_real_m"], rec["src_m"], rec["miss_pct"],
                      rec["miss_chord_m"])))

    # ② 交付 → 图纸（多建/歪建）★ v2：判定只看 **E 类**（对**任何图层**都无对应物）
    #   v1 拿「离掩蔽后的图纸点 >0.40m」一个数直接判 —— 实测那个数里大半是**参考集口径**
    #   （c057 F1 的 18.5% 有 100% 是口径产物）。A~D 四类如实列在 notes，**不作判定**。
    if rec.get("stray_pct") is None:
        # 只有一种到达这里的方式：**没有图纸墙线可比**（src 空，见 measure_floor）。
        # ★ 这里给 NOT_APPLICABLE，**不是 PASS**：不判 ≠ 通过。但也**不在这里升 WATCH** ——
        #   「为什么一条可比线都没有」只有 ① 知道（图层上只有曲要素 ⇒ 直墙账不适用；
        #   图层空 ⇒ 没量到），② 再喊一遍就是**同一个问题两处判**，而且会把
        #   T6 那种「曲墙已建、直墙账本就不适用」的干净层升成 WATCH（假红）。
        #   ⇒ 各方向管各方向：① 管「有没有得比」，② 只管「比出来的结果」。
        lv.append((0, "NOT_APPLICABLE", rec.get("stray_note") or "交付侧无可比对象 ⇒ 不判"))
    elif rec["stray_edge_m"] < STRAY_MIN_M:
        lv.append((0, "PASS", "交付墙边线只有 %.1fm（<%.0fm）⇒ 比值不判"
                   % (rec["stray_edge_m"], STRAY_MIN_M)))
    elif rec.get("stray_any_pct") is None:
        # ★ v2 的分解没跑起来 ⇒ **不许**退回 v1 的「一个数」去判（那正是要修的病）
        lv.append((1, "WATCH",
                   "交付墙 %.1f%%（%.1fm）的边线附近没有图纸墙线，**但口径分解没跑**"
                   "（E 类未知）⇒ 本层不判「多建/歪建」"
                   % (rec["stray_pct"], rec["stray_edge_m"])))
    elif rec["stray_any_pct"] >= STRAY_GAP:
        lv.append((2, "GAP", "交付墙有 %.1f%%（%.1fm）的边线**在任何图层上都找不到对应物**"
                   "（多建/歪建；已扣掉 %.1f%% 的参考集口径损失，阈值试行中）"
                   % (rec["stray_any_pct"], rec["stray_any_m"],
                      rec["stray_pct"] - rec["stray_any_pct"])))
    elif rec["stray_any_pct"] >= STRAY_WATCH:
        lv.append((1, "WATCH", "交付墙 %.1f%%（%.1fm）的边线在任何图层上都找不到对应物"
                   "（已扣掉 %.1f%% 的口径损失，阈值试行中）"
                   % (rec["stray_any_pct"], rec["stray_any_m"],
                      rec["stray_pct"] - rec["stray_any_pct"])))
    else:
        # 显式写出「这个方向查过且干净」—— 不然屏幕上「查了没事」与「压根没查」同形
        lv.append((0, "PASS", "交付墙边线 E 类 %.1f%%（任何图层上都有对应物）"
                   % rec["stray_any_pct"]))

    # ③ 曲要素（**单列**，永不混进 ① 的分母）
    if rec["curve_m"] < CURVE_MIN_M:
        lv.append((0, "PASS", "本层图纸墙图层上无曲要素（<%.0fm）" % CURVE_MIN_M))
    elif rec["pair_curved"]:
        if rec["curve_miss_pct"] >= MISS_GAP:
            lv.append((2, "GAP", "曲墙 %.0f%%（%.1f/%.1fm）没建（该栋 pair_curved=True，曲墙在识别范围内）"
                       % (rec["curve_miss_pct"], rec["curve_miss_m"], rec["curve_m"])))
        elif rec["curve_miss_pct"] >= MISS_WATCH:
            lv.append((1, "WATCH", "曲墙 %.0f%%（%.1f/%.1fm）没建"
                       % (rec["curve_miss_pct"], rec["curve_miss_m"], rec["curve_m"])))
        else:
            lv.append((0, "PASS", "曲墙已建（漏 %.0f%%）" % rec["curve_miss_pct"]))
    else:
        lv.append((1, "WATCH",
                   "本层有 %.1fm 曲要素，但该栋 pair_curved=False ⇒ 曲墙**不在识别范围内**；"
                   "本类不计作漏（否则是 c041/c026/c079 那种 ~千%% 假阳性），但请知悉这是盲区"
                   % rec["curve_m"]))

    rank = max(t[0] for t in lv)
    top = [t for t in lv if t[0] == rank]
    if rank == 0:
        # 三条都在 0 档：只要有一条真 PASS，整层就算 PASS（**某个方向不适用**不等于整层没查）；
        # 一条 PASS 都没有（三个方向都 N/A）才写 NOT_APPLICABLE。
        st = "PASS" if any(t[1] == "PASS" for t in lv) else "NOT_APPLICABLE"
        return st, "；".join(t[2] for t in lv if t[2]), [t[2] for t in lv]
    return top[0][1], "；".join(t[2] for t in top), [("●" if t[0] == rank else "·") + t[2] for t in lv]


def measure_floor(src, cov, curve=None, door_mask=None, ledger=None, pair_curved=False,
                  src_raw=None, wall_geom=None, any_geom=None, wall_layers=None,
                  bulge_arcs=None, curve_w=None):
    """一个楼层的三个账（图纸→交付 / 交付→图纸 / 曲要素）+ 排除账。**纯函数，可自检。**

    `cov` = 交付墙覆盖区（shapely，局部米）或 None；`src`/`curve` = 采样点列。
    ★ 「不判」一律用 `None`，**绝不用 0**：0 是「量到 0」，None 是「没量到」，
      两者在屏幕上必须不是同一个东西（本仓铁律）。

    v2 新增的三个**可选**参考（见文件头「② 的口径分解」）—— 给了才量，没给一律 `None`：
      · `src_raw`   = **未掩门带**的图纸采样点（`_source_wall_points` 的原样输出）
      · `wall_geom` = 墙图层上**不过滤**的全部线几何（`layer_geoms(..., layer=wall_layer)`）
      · `any_geom`  = **所有图层**的线几何并集（`layer_geoms(..., layer=None)`）
    ② 于是从「一个数」变成**三档嵌套**：masked ⊆ wall ⊆ any ⇒ 恒有
    `n_any ≤ n_wall ≤ n_nomask ≤ len(xs)`，运行期断言钉住（T13 的刑具就改这个）。

    v3 新增第四个可选参考（见文件头「① 的口径分解」）—— 同样给了才量：
      · `bulge_arcs` = `bulge_chords(...)`：墙图层上**矢高 ≥ WALL_DIST** 的那些
        「弦／弧」对。① 因此从「一个数」变成**两档**：`miss_pct` = 总账（不变，
        `--cross-check` 与 `_dxf_audit` 比的就是它）＋ `miss_real_pct` = 判定档
        （扣掉「参考集把弧弦化」造出来的那批）。恒有 `miss_real_n ≤ len(missed)`。

    v4 新增 `curve_w`（见文件头「③ 的量纲与作用域」）：与 `curve` **等长**的段重表，
      `curve_w[i]` = 「点 i → 点 i+1」的真实长度，末点/跨实体写 `None`。
      ⇒ `curve_m` 不再由 `点数 × SAMP` 得出（那是**错的口径**：`flattening(A.SAMP)` 的
      入参是矢高容差、不是步长，实测点距 0.019~0.037m ⇒ 米数虚高 7.8~20.5 倍）。
      ★ **给了 `curve` 就必须给 `curve_w`**，缺了当场抛 —— 不许悄悄回落到旧口径：
        旧口径错得安静（比值那两栏甚至会因为「分子分母一起错」而看着正常，
        实测 c043 F0 报 14.9% 而真值 14.4%、c113 F0 报 36.1% 而真值 5.4%）。
    """
    src = list(src or [])
    curve = list(curve or [])
    curve_w = list(curve_w) if curve_w is not None else None
    if curve and curve_w is None:
        raise ValueError(
            "measure_floor: 给了 curve（%d 点）却没给 curve_w —— 拒绝回落到"
            "「点数 × SAMP」这个错口径（见本函数 docstring 与文件头 ③ 一节）" % len(curve))
    if curve_w is not None and len(curve_w) != len(curve):
        raise ValueError("measure_floor: curve_w 与 curve 不等长（%d ≠ %d）⇒ 段与点已经错位"
                         % (len(curve_w), len(curve)))
    n = len(src)
    rec = dict(src_n=n, src_m=round(n * A.SAMP, 1),
               curve_n=len(curve),
               # 实体数 = 段重表里 None 的个数（每个实体末点恰好一个 None）
               curve_ent_n=(sum(1 for x in curve_w if x is None) if curve_w else 0),
               curve_m=round(sum(x for x in (curve_w or []) if x), 1),
               pair_curved=bool(pair_curved), ledger=dict(ledger or {}))
    has_cov = cov is not None and not cov.is_empty

    # ① 图纸 → 交付（**与 _dxf_audit 同一套机制、同一批常量**）
    if not has_cov:
        missed, prep = list(src), None
    else:
        prep = shapely.prepared.prep(cov.buffer(A.WALL_DIST))
        missed = [q for q in src if not prep.covers(sg.Point(q[0], q[1]))]
    rec["miss_m"] = round(len(missed) * A.SAMP, 1)
    rec["miss_pct"] = round(len(missed) / n * 100, 1) if n else None
    dists = (shapely.distance(shpoints(np.asarray(missed, dtype=float)), cov)
             if (missed and has_cov) else None)
    rec["miss_med_dist_m"] = (round(float(np.median(dists)), 2) if dists is not None else None)
    cl = cluster_points(missed)
    for c in cl:
        c["near_m"] = (round(float(np.median(dists[c["idx"]])), 2) if dists is not None else None)
        c.pop("idx")
    rec["miss_clusters"] = cl

    # ── ① 的**口径分解**（v3 的判定依据，见文件头「① 的口径分解」）──────────────
    # 报出来的这个 `miss_pct` 里，多少是**参考集自己把弧弦化**造出来的，多少是
    # **图纸上有墙而交付里真没有**？这两件事在屏幕上**必须不是同一行字**：
    # 实测 c113 F0 那 159.6m 的「漏」里 **92.3% 的点落在弦上**，只剩 12.2m 不在任何弦上。
    #
    # 扣除要**两个条件同时成立**（缺一不扣）：
    #   (a) 这个漏点**落在某根弦上**（≤ ON_CHORD），而那根弦离它自己的弧 ≥ WALL_DIST
    #       —— 参考集在这个位置放了一根**图纸上没有**的直墙；
    #   (b) 那根弦的**弧**在离该点最近处**已被交付墙盖住**（≤ WALL_DIST）
    #       —— 图纸上真实的那道曲墙**是建了的**，只是不在弦的位置上。
    # ★ (b) 是这档的保险：只满足 (a) **不许扣** —— 弧没建时，这条漏是真的。
    #   后果不对称：扣错会**藏起一个真缺陷**，不扣只是多报一条（本仓铁律 36）。
    rec["miss_chord_n"] = None
    rec["miss_chord_m"] = None
    rec["miss_chord_sag"] = None
    rec["miss_real_n"] = None
    rec["miss_real_m"] = None
    rec["miss_real_pct"] = None
    if bulge_arcs is not None:
        rec["miss_real_n"] = len(missed)
        rec["miss_real_m"] = rec["miss_m"]
        rec["miss_real_pct"] = rec["miss_pct"]
        rec["miss_chord_n"] = 0
        rec["miss_chord_m"] = 0.0
        rec["miss_chord_sag"] = dict(n=0, p50=None, mx=None)
        if missed and bulge_arcs and prep is not None:
            cq = shpoints(np.asarray(missed, dtype=float))
            ci, cd = STRtree([g[0] for g in bulge_arcs]).query_nearest(
                cq, return_distance=True, all_matches=False)
            ci = np.asarray(ci)
            cd = np.asarray(cd, dtype=float).ravel()
            if len(cd) != len(missed):
                raise RuntimeError("① 弦化档：返回 %d 个距离、漏点 %d 个 —— 对不上行"
                                   "（先查 all_matches 是否又变回默认）" % (len(cd), len(missed)))
            if ci.ndim != 2 or ci.shape[0] != 2 or not np.array_equal(ci[0], np.arange(len(missed))):
                raise RuntimeError("① 弦化档：配对下标形状 %r 不是 (2, N) 的输入序 —— 距离与点错位"
                                   % (ci.shape,))
            keep = np.zeros(len(missed), dtype=bool)
            for t in np.where(cd <= ON_CHORD)[0]:
                arc = bulge_arcs[int(ci[1][t])][1]
                near_pt = nearest_points(arc, sg.Point(float(missed[t][0]),
                                                       float(missed[t][1])))[0]
                if prep.covers(near_pt):
                    keep[t] = True
            rec["miss_chord_n"] = int(keep.sum())
            rec["miss_chord_m"] = round(int(keep.sum()) * A.SAMP, 1)
            rec["miss_real_n"] = len(missed) - int(keep.sum())
            rec["miss_real_m"] = round(rec["miss_real_n"] * A.SAMP, 1)
            rec["miss_real_pct"] = (round(rec["miss_real_n"] / n * 100, 1) if n else None)
            if keep.any():
                sags = [bulge_arcs[int(ci[1][t])][2] for t in np.where(keep)[0]]
                rec["miss_chord_sag"] = dict(n=len(sags),
                                             p50=round(float(np.median(sags)), 2),
                                             mx=round(float(max(sags)), 2))
        if not (0 <= rec["miss_real_n"] <= len(missed)):
            raise RuntimeError("① 弦化档：真实档 %d 点不在 [0, 漏点 %d] 内 —— 扣得比漏的还多，"
                               "这档的集合不是漏点的子集" % (rec["miss_real_n"], len(missed)))

    # ② 交付 → 图纸（多建/歪建）
    xs = boundary_samples(cov, A.SAMP) if has_cov else []
    rec["cov_edge_m"] = round(cov.boundary.length, 1) if has_cov else 0.0
    rec["cov_edge_sampled_m"] = round(len(xs) * A.SAMP, 1)
    if not src:
        # ★ 没有图纸墙线 ⇒ 「离群」这个词无从谈起：**不许**把交付墙整片报成 100% 多建/歪建。
        #   这个方向此刻是「没量到」而不是「量到 0」，所以三个数全给 None，不给 0
        #   （给 0 就是宣称「查过、没有多建」，那是假话；铁律：两者必须不同形）。
        rec["stray_edge_m"] = None
        rec["stray_pct"] = None
        rec["stray_med_dist_m"] = None
        rec["stray_near_src_n"] = 0
        rec["stray_clusters"] = []
        rec["stray_note"] = "本层没有图纸墙线可比 ⇒ 交付侧**不判**（不是「没有多建」）"
        rec["stray_nomask_n"] = None
        for k in ("door", "wall", "any"):
            rec["stray_%s_pct" % k] = None
            rec["stray_%s_m" % k] = None
            rec["stray_%s_n" % k] = None
            rec["stray_%s_clusters" % k] = []
        rec["stray_any_dist"] = None
        rec["stray_wall_layers"] = None
    else:
        stray, sd, near_n = stray_samples(xs, src, A.WALL_DIST)
        rec["stray_edge_m"] = round(len(stray) * A.SAMP, 1)
        # 分母也用**采样估计**（同一个估计量），不用精确周长 —— 混用两者会在
        # 「每条边线至多多算一个采样」上系统性地高估（本仓铁律 23(c)：量纲要恒等）
        rec["stray_pct"] = round(len(stray) / len(xs) * 100, 1) if xs else None
        rec["stray_med_dist_m"] = (round(float(np.median([d for d in sd if d is not None])), 2)
                                   if any(d is not None for d in sd) else None)
        rec["stray_near_src_n"] = near_n
        scl = cluster_points(stray)
        for c in scl:
            c.pop("idx")
        rec["stray_clusters"] = scl
        rec["stray_note"] = None

        # ── ② 的**口径分解**（v2 的判定依据，见文件头那一节）────────────────────
        # 报出来的这个 `stray_pct` 里，多少是**参考集自己少收了线**，多少是
        # **交付墙上真有东西而图纸上没有**？这两件事在屏幕上**必须不是同一行字** ——
        # v1 把它们加在一起报（c057 F1 的 18.5% 实测 100% 是前者）。
        # 三档**嵌套**：masked ⊆ wall ⊆ any（墙图层 ⊆ 所有图层），恒有
        # n_any ≤ n_wall ≤ n_nomask，运行期断言钉住。分母一律是 len(xs)（同一估计量）。
        n_nomask = len(stray)
        rec["stray_nomask_n"] = n_nomask
        rec["stray_door_pct"] = None
        rec["stray_door_n"] = None
        if src_raw is not None:
            # A 类 = **只有没被门带掩蔽的源点才解释得了**的那些边线。
            # src_raw ⊇ src ⇒ near_raw ⊇ near_nomask，差集正是「参考被门带吃掉」的那批
            # （直接相减，不另写一遍判据：两处判「近」就有机会不一致 —— T12 的教训）。
            _, _, near_raw = stray_samples(xs, src_raw, A.WALL_DIST)
            rec["stray_door_n"] = int(near_raw - near_n)
            rec["stray_door_pct"] = (round((near_raw - near_n) / len(xs) * 100, 1)
                                     if xs else None)
        for key, geoms in (("wall", wall_geom), ("any", any_geom)):
            if geoms is None:
                # ★ 没量到 ≠ 量到 0：整档留 None（不许拿一个 0 去当中性值）
                rec["stray_%s_pct" % key] = None
                rec["stray_%s_m" % key] = None
                rec["stray_%s_n" % key] = None
                rec["stray_%s_clusters" % key] = []
                continue
            gp, gd, _, lcnt = stray_samples_geom(
                xs, geoms, (wall_layers if key == "wall" else None), A.WALL_DIST)
            rec["stray_%s_n" % key] = len(gp)
            rec["stray_%s_pct" % key] = round(len(gp) / len(xs) * 100, 1) if xs else None
            rec["stray_%s_m" % key] = round(len(gp) * A.SAMP, 1)
            gcl = cluster_points(gp)
            for c in gcl:
                c.pop("idx")
            rec["stray_%s_clusters" % key] = gcl
            if key == "wall":
                rec["stray_wall_layers"] = lcnt     # 近的边线是被哪个图层解释的
            if key == "any":
                # ★ 「刚过容差」和「图上真的空」在**计数**上一样，在**分布**上完全不同
                #   （铁律 23(a)：判据全绿先问它是不是在全部样本上取极值）。
                #   实测 c113 F0：p50 0.74m、max 3.1m、5m 外 0 点 ⇒ 0.40 这条线切在
                #   一个连续分布的中段，不是切在「有/无」的界上。
                arr = np.asarray([d for d in gd if d is not None], dtype=float)
                rec["stray_any_dist"] = (
                    dict(p10=round(float(np.percentile(arr, 10)), 2),
                         p25=round(float(np.percentile(arr, 25)), 2),
                         p50=round(float(np.percentile(arr, 50)), 2),
                         p75=round(float(np.percentile(arr, 75)), 2),
                         p90=round(float(np.percentile(arr, 90)), 2),
                         mx=round(float(arr.max()), 2)) if arr.size else None)
        if rec.get("stray_any_n") is not None and rec.get("stray_wall_n") is not None:
            # 嵌套是这三档的**定义性**性质（三份参考集互为子集）。破了不是「数据怪」，
            # 是**取集错了**：某一档拿的实体与另一档不是同一批（本仓铁律 18/23(b)）。
            if not (rec["stray_any_n"] <= rec["stray_wall_n"] <= n_nomask <= len(xs)):
                raise RuntimeError(
                    "② 三档不满足嵌套 n_any(%d) ≤ n_wall(%d) ≤ n_nomask(%d) ≤ len(xs)(%d)"
                    " —— 三份参考集互为子集是定义性的，破了就是取集/对齐错了"
                    % (rec["stray_any_n"], rec["stray_wall_n"], n_nomask, len(xs)))

    # ③ 曲要素（单列；机制与 ① 相同 ⇒ 与 miss_pct 可比）
    #    ★ 量纲（v4）：长度一律按 `curve_w` 的**真实段长**累加，不再 `点数 × SAMP`。
    #      判漏的规则与 ① 保持同构、但落在**段**上：一段算漏 **当且仅当它的两个端点
    #      都没被盖住**（保守 —— 只有一端在外的那段不计，它至多半段，且绝不虚增分子）。
    #      段长按**点序相邻**取（`i → i+1`），不是「按键值排序后相邻」：后者在折返的
    #      短弧上会凭空多出长度（实测 9 个簇按点距和 11.5m，而它们的 bbox 只有 0.3m）。
    if not curve:
        rec["curve_miss_m"] = None
        rec["curve_miss_pct"] = None
        rec["curve_miss_n"] = None
        rec["curve_clusters"] = []
    else:
        miss = ([not prep.covers(sg.Point(q[0], q[1])) for q in curve]
                if prep is not None else [True] * len(curve))
        seg_miss = [bool(curve_w[i] is not None and miss[i] and miss[i + 1])
                    for i in range(len(curve) - 1)]
        mm = sum(curve_w[i] for i, ok in enumerate(seg_miss) if ok)
        rec["curve_miss_n"] = sum(miss)
        rec["curve_miss_m"] = round(mm, 1)
        # ★ 比值一律用**印出来的那两个数**算（不是用未舍入的 `mm`）：
        #   否则读者拿屏上「15.7 ／ 15.7」自己一除得 100.0，而报告写着 100.1 ——
        #   **两个数各自都对、配起来对不上**，正是本仓记过的「自洽的数才可信」那一类。
        #   实测（v4 落地时抓到的）：全漏的一层，未舍入分子 15.707953 ÷ 舍入后分母 15.7
        #   = 100.05 ⇒ 舍成 100.1。改成同源之后，「全漏」恒好是**恰好 100.0**。
        rec["curve_miss_pct"] = (round(rec["curve_miss_m"] / rec["curve_m"] * 100, 1)
                                 if rec["curve_m"] else None)
        # 簇只吃**判漏的点**，但长度必须用**原表对齐**的段重：过滤会把下标挪位，
        # 所以逐点重建 `cw` —— 只有「下一个点也判漏且相邻」的那一段才算长度
        # （于是 Σ 各簇 len_m 恰好 = curve_miss_m，见下面的守恒断言）。
        cm, cw = [], []
        for i, q in enumerate(curve):
            if miss[i]:
                cm.append(q)
                cw.append(curve_w[i] if (i + 1 < len(curve) and miss[i + 1]) else None)
        ccl = cluster_points(cm, seg_w=cw)
        for c in ccl:
            c.pop("idx")
        # ★ 守恒断言：BFS 必须把每个点恰好收进一个簇。**只查点数、不查米数** ——
        #   米数那个和是构造出来的（乘/加同源），查了也恒真，是装饰不是判据
        #   （本仓铁律 18：自洽的数证明不了它对）。点数守恒则会**真的红**：丢点/重复都破。
        if sum(c["n"] for c in ccl) != len(cm):
            raise RuntimeError("③ 分簇丢点：各簇点数之和 %d ≠ 判漏点数 %d"
                               % (sum(c["n"] for c in ccl), len(cm)))
        rec["curve_clusters"] = ccl

    rec["door_mask"] = list(door_mask or [])
    rec["status"], rec["why"], rec["notes"] = classify_floor(rec)
    return rec


# ── DXF 面（薄壳：把 DXF 变成上面那三个账要的输入） ─────────────────────

#: ③ 出局的理由（**稳定的键**，进排除账）+ 给人看的说法（显示层翻）。
#: 键必须是稳定的标识符，不是句子 —— 句子会随措辞漂，而账本要能与历史比。
CURVE_OUT_LABEL = {
    "arc_door": "门扇开启弧（r 在 %.1f~%.1fm：识别器把它还原成门，不当墙）"
                % (CL.DOOR_LEAF_MIN, CL.CURVE_MIN_R),
    "arc_tiny": "比门扇还小的弧（r < %.1fm：装饰弧/柱圈）" % CL.DOOR_LEAF_MIN,
    "circle": "整圆（两条识别路径都不收：`classify_line.py` 尾注「TEXT/MTEXT/CIRCLE 标注忽略」）",
    "sym_ellipse": "符号椭圆（长半轴 < %.1fm ⇒ 图例符号，非墙）" % (CL.SYMBOL_ELLIPSE_MAX_MM / 1000.0),
    "line_path": "该栋走 `classify_line`：它只收 ARC，ELLIPSE/SPLINE 不进遍历",
    "unknown": "不认识的图元",
}

#: 同一批出局原因的**短**写法 —— 只给**纯文本**那两处（逐层 stdout、叠加图标题）用。
#: 上面的长标签是给 HTML 的（那里有换行、能放长句）；终端里一行本来就长，
#: 再把每个原因的解释整句塞进去，一行能到 300 字符，**读的人直接跳过整行** ——
#: 而「排除了什么必须看得见」的判据就靠这一行（铁律 23(b)）。
CURVE_OUT_SHORT = {
    "arc_door": "门扇弧",
    "arc_tiny": "更小的弧",
    "circle": "整圆",
    "sym_ellipse": "符号椭圆",
    "line_path": "该栋不收的 ELLIPSE/SPLINE",
    "unknown": "不认识的图元",
}


def curve_in_scope(e, p):
    """识别器**会不会把这条曲线当墙**？返回 `(在册?, 出局的理由键)`。

    ★ 判据不是新发明的门槛，是**两条识别路径的交集/差集**（逐行对得上源文件）：
      · `classify_line.py:172-181`（该栋 `classifier == "line"`）：只把
        **ARC 且 r ≥ CURVE_MIN_R(2m)** 收进 `arcs` → `pair_arc_bands`（环形墙带）；
        CIRCLE/SPLINE/ELLIPSE 连遍历都不进。
      · `classify.py:187-216`（默认识别器）：ARC r≥2m → `walls`；ARC 落在门扇区
        `[DOOR_LEAF_MIN, min(2m, DOOR_LEAF_MAX))` → `door_arcs`（**也不进 walls**，
        注释原文「绝不能塞进 walls：会在每扇门的位置长出一堵假墙」）；更小的 ARC 直接丢；
        ELLIPSE 长半轴 < `SYMBOL_ELLIPSE_MAX_MM`(1m) = 符号丢弃；其余 ELLIPSE/SPLINE → walls。
        **CIRCLE 不在 `t not in ("ARC","ELLIPSE","SPLINE")` 的名单里 ⇒ 从来不是墙。**
      ⇒ **任何栋都算曲墙的 = ARC 且 r ≥ 2m**；大 ELLIPSE/SPLINE 只在默认识别器的栋里算。
      ⇒ 半径一律**毫米**（`e.dxf.radius` 原生单位；`classify._ellipse_major_mm` 也是毫米）。
      阈值全部**从识别器 import**（`CL.*`），不抄数进来 —— 上游一改，这里跟着变。
    """
    t = e.dxftype()
    if t == "ARC":
        r = float(getattr(e.dxf, "radius", 0.0) or 0.0)
        if r >= CL.CURVE_MIN_R * 1000.0:
            return True, ""
        return False, ("arc_door" if r >= CL.DOOR_LEAF_MIN * 1000.0 else "arc_tiny")
    if t == "CIRCLE":
        return False, "circle"
    if t in ("ELLIPSE", "SPLINE"):
        if getattr(p, "classifier", "lwpolyline") == "line":
            return False, "line_path"
        if t == "ELLIPSE" and CL._ellipse_major_mm(e) < CL.SYMBOL_ELLIPSE_MAX_MM:
            return False, "sym_ellipse"
        return True, ""
    return False, "unknown"


def curve_segments(doc, p, F, box, led):
    """墙图层上**识别器会当墙的**曲线采样点 ＋ **逐段真实长度**。返回 `(pts, w)`。

    ★ `_source_wall_points` 整类跳过曲线（那行注释「识别器从不建模」已过期，见文件头⑤）。
      本函数把它们**单列**出来量 —— 不混进直墙账（混进去就是 ~千% 虚漏）。

    `w[i]` = 「点 i → 点 i+1」的真实长度（米），**实体末点写 `None`** ⇒
      `len(w) == len(pts)` 恒成立，且 `sum(x for x in w if x)` = 各实体展开长度之和。
      **为什么不沿用 `点数 × SAMP`**（`README` 里那句「量纲必须是所判定量的量纲」）：
      `flattening(A.SAMP)` 的入参是**矢高容差**不是步长，实现里还有**最小分段数**
      （实测 ARC 恒 65 点、CIRCLE 恒 129 点）⇒ 点距与曲线长度**无关**
      （c043 F0 中位 0.0248m、c113 F0 0.0373m，而 SAMP=0.35）⇒ 米数虚高 7.8~20.5 倍。
      `curve_points` 内部**本来就算了这个真长度**（做 `L < MIN_ENTITY` 的短实体过滤），
      v4 之前**算完就丢**，回报时改写成 `点数 × SAMP`。

    ★ 作用域（v4）：只收 `curve_in_scope` 认账的那一类；出局的**逐类计数 + 记米数**
      进 `led["curve_excl"]` —— 「排除了什么」必须能看见（本仓铁律 23(b)：
      排除规则把真值排除了也是一种坏法，所以要把它数出来）。
      旧版把墙图层上**所有** ARC/CIRCLE/SPLINE/ELLIPSE 都算进分母，实测：
      c043 F0 的 25.2m「曲要素」是 **18 段门开启弧**（r≈1.0~1.28m）、
      c113 F0 有 **46 个柱/圆符号 + 27 段门弧**（占分母 54%）、
      c057 F1 的 45.1m「曲要素」只是 **一个 r≈0.35m 的圆** —— 全是假红。
    """
    layer = getattr(p, "wall_layer", None) or "4.2墙体"
    x0, y0, x1, y1 = box
    bw, bh = (x1 - x0) + 5.0, (y1 - y0) + 5.0
    pool = []
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "INSERT":
            try:
                pool.extend(e.virtual_entities() or [])
            except Exception:
                led["insert_fail"] = led.get("insert_fail", 0) + 1
        elif t in ("ARC", "CIRCLE", "SPLINE", "ELLIPSE"):
            pool.append(e)
    out, w = [], []
    for e in pool:
        if (getattr(e.dxf, "layer", "") or "") != layer:
            continue
        try:
            raw = [(v.x, v.y) for v in ezpath.make_path(e).flattening(A.SAMP)]
        except Exception:
            led["unflattenable"] = led.get("unflattenable", 0) + 1
            continue
        if len(raw) < 2:
            continue
        lv = [to_local(p, float(a), float(b), F) for a, b in raw]
        # ★ 作用域判定放在**图层之后、定位之前**：出局的实体连「在哪一层」都不必问 ——
        #   识别器根本不看它。但长度要算出来记账（展平已在手上，不额外花钱）。
        in_scope, why = curve_in_scope(e, p)
        if not in_scope:
            L = sum(math.dist(lv[i], lv[i + 1]) for i in range(len(lv) - 1))
            d = led.setdefault("curve_excl", {}).setdefault(why, dict(n=0, m=0.0))
            d["n"] += 1
            d["m"] = round(d["m"] + L, 2)
            continue
        # 定位：_entity_floor 对 ARC/CIRCLE 给圆心，但 **SPLINE 没有分支（返回 None）**
        # ⇒ 用它会把样条曲线静默漏掉，所以取不到时用折线重心兜底（实话实说，不假装）。
        anchor = None
        try:
            anchor = R._entity_floor(e)
        except Exception:
            anchor = None
        if anchor is None:
            anchor = (sum(q[0] for q in raw) / len(raw), sum(q[1] for q in raw) / len(raw))
        try:
            if int(round(floor_of(p, anchor[0], anchor[1]))) != F:
                led["other_floor"] = led.get("other_floor", 0) + 1
                continue
        except Exception:
            led["other_floor"] = led.get("other_floor", 0) + 1
            continue
        ax = min(q[0] for q in lv); bx = max(q[0] for q in lv)
        ay = min(q[1] for q in lv); by = max(q[1] for q in lv)
        if (bx - ax) > bw or (by - ay) > bh:
            led["bbox"] = led.get("bbox", 0) + 1
            continue
        if bx < x0 - 1.5 or ax > x1 + 1.5 or by < y0 - 1.5 or ay > y1 + 1.5:
            led["bbox"] = led.get("bbox", 0) + 1
            continue
        if e.dxftype() in ("CIRCLE", "ELLIPSE"):
            # 实心块判据（照 _dxf_audit._source_wall_points:239-247：面积/周长>1 ⇒ 块，不是墙线）
            try:
                pg = sg.Polygon(lv)
                if pg.is_valid and pg.area > 1e-6 and pg.area / pg.length > 1.0:
                    led["fill_block"] = led.get("fill_block", 0) + 1
                    continue
            except Exception:
                pass
        # ★ 真实段长：就取上面这个已经算过、之前被丢掉的量（**同一个函数、同一个值**）
        seg = [math.dist(lv[i], lv[i + 1]) for i in range(len(lv) - 1)]
        if sum(seg) < A.MIN_ENTITY:
            led["short"] = led.get("short", 0) + 1
            continue
        led["runs"] = led.get("runs", 0) + 1
        out.extend(lv)
        w.extend(seg + [None])          # 末点：跨实体不连段
    if len(w) != len(out):
        raise RuntimeError("curve_segments: 段重表与点表不等长（%d ≠ %d）⇒ 量纲已经错位"
                           % (len(w), len(out)))
    return out, w


def curve_points(doc, p, F, box, led):
    """只要点、不要段长的薄壳（`--selftest` 与 `_scratch/_curve_len_gauge.py` 用它按点对账）。

    ★ 生产路径**不走这个**：`analyze_floor` 调 `curve_segments` 并把 `w` 一起交给
      `measure_floor` —— 只给点不给长度会被 `measure_floor` 当场拒绝（拒绝回落到错口径）。
    """
    return curve_segments(doc, p, F, box, led)[0]


def _flat_pool(doc, led=None):
    """modelspace 全部可展图元，INSERT 摊开 —— 取法与 `_source_wall_points` 同一套。"""
    pool = []
    for e in doc.modelspace():
        if e.dxftype() == "INSERT":
            try:
                pool.extend(e.virtual_entities() or [])
            except Exception:
                if led is not None:
                    led["insert_fail"] = led.get("insert_fail", 0) + 1
            continue
        pool.append(e)
    return pool


def layer_geoms(doc, p, F, layer=None, near=None, pad=STRAY_ANY_PAD, led=None):
    """某一图层的图元 → **本地米折线几何** 列表（`layer=None` ⇒ 所有图层）。对账尺专用。

    ★ 这个函数**故意什么过滤都不做**：不筛楼层带、不筛框、不筛长短、不筛曲直、不把闭口环
      当填充丢掉。它唯一的用处是当 ② 的**对账尺** —— 它与 `_source_wall_points` 的差
      **就是**「参考集口径」本身（文件头「② 的口径分解」）。
      ⇒ 谁要往这里加过滤，先读那一节：**少一个过滤不是漏写，多一个过滤才是错。**

    用**线几何**而不是采样点：`query_nearest(..., return_distance=True)` 给的是**真距离**
    （2026-09-24 实测：10m 水平线正上方 0.4m 处查询得 0.4、与 `.distance()` 逐位相等），
    于是不必把线密化成点 —— 密化会把 0.40m 这条分界糊掉（0.35m 步长误差 ±0.175m）。

    `near` 给一组点时只收**本地框外扩 pad 内有点**的图元（剪枝，**保守**：pad 必须 > WALL_DIST，
    否则会把本该算进来的图元筛掉 —— 量程卡在待检对象之上就是放行）。剪掉多少要计数进 led。
    返回 (几何列表, 图层名并行列表, led)。

    ★ **只收「线状」图元**（`LINE/LWPOLYLINE/POLYLINE/ARC/CIRCLE/SPLINE/ELLIPSE`），
      文字/标注/填充/块参照**不算「对应物」** —— 一条墙的对应物是**墙线**，不是压在它上面的
      那一行字。这条界是语义上的，不是省事：`TEXT` 若也算，就会出现「墙下正好标了个房间号
      ⇒ 判它图上有对应物」这种**把真缺陷藏起来**的绿。所以这里**不是**「什么都收」。
      （与已登记的实测同源：口径分解那一节的 3.1% 用的是同一批线状图元。）
    """
    led = led if led is None else led
    tree = STRtree(shpoints(np.asarray(near, dtype=float))) if near else None
    out, lays = [], []
    for e in _flat_pool(doc, led):
        if e.dxftype() not in _GEOM_TYPES:
            led["skipped_type"] = led.get("skipped_type", 0) + 1
            continue
        lay = getattr(e.dxf, "layer", "") or ""
        if layer is not None and lay != layer:
            continue
        try:
            lv = [to_local(p, float(v.x), float(v.y), F)
                  for v in ezpath.make_path(e).flattening(A.SAMP)]
        except Exception:
            led["unsupported"] = led.get("unsupported", 0) + 1
            continue
        if len(lv) < 2:
            continue
        if getattr(e, "closed", False) and lv[0] != lv[-1]:
            lv = lv + [lv[0]]          # 闭合环要补回最后一段，否则少一条边
        if tree is not None:
            ax = min(q[0] for q in lv); bx = max(q[0] for q in lv)
            ay = min(q[1] for q in lv); by = max(q[1] for q in lv)
            if not tree.query(sg.box(ax - pad, ay - pad, bx + pad, by + pad)).size:
                led["pruned"] = led.get("pruned", 0) + 1
                continue
        led["kept"] = led.get("kept", 0) + 1
        out.append(sg.LineString(lv))
        lays.append(lay)
    return out, lays, led


def bulge_chords(doc, p, F, layer, min_sag=MISS_CHORD_SAG, led=None):
    """墙图层上「带 bulge 的段」→ [(弦 LineString, 弧 LineString, 矢高m)]，**只留矢高 ≥ min_sag**。

    ★ 为什么需要它（文件头「① 的口径分解」）：`_source_wall_points`（只读、不许改）取顶点用
      `rv = list(e.get_points("xy"))` —— **不展开 bulge**，所以图上一条 R=24m 的弧在参考集里
      成了 34m 的**直弦**，① 就把「弧被弦替掉」读成「墙没建」。要判「这条漏点是尺子造的」，
      就得有图纸上那段**真的弧**。
    ★ 弧的**圆心与半径**取自 `ezdxf.math.bulge_to_arc`（手算基准验过：p1=(0,0)→p2=(1,0)、
      |b|=tan(π/8) ⇒ 圆心 (0.5,±0.5)、R=0.70710678，精确）；**扫掠方向按 DXF 定义**
      （b>0 = 逆时针）由本函数自己定 —— **不依赖该 API 返回的 a1/a2 排列**：实测真图上按
      `(a1+a2)/2` 取「角中点」有 197/421 条落到**对径点**（`_scratch/_stray_bulge_arcapi.py`），
      那是个「小样本上全对、真数据上错一半」的口径。⇒ 全仓弧只有这一份实现：库给圆心半径，
      方向是规范自己的定义。
    ★ 采样步长跟 `A.SAMP`（与别处同一分辨力），不另立一个精度。
    """
    out = []
    for e in _flat_pool(doc, led):
        if e.dxftype() != "LWPOLYLINE":
            continue
        if (getattr(e.dxf, "layer", "") or "") != layer:
            continue
        pts = [(float(q[0]), float(q[1]), float(q[4])) for q in e.get_points("xyseb")]
        n = len(pts)
        if n < 2:
            continue
        pairs = [(i, i + 1) for i in range(n - 1)]
        if getattr(e, "closed", False) and (abs(pts[0][0] - pts[-1][0]) > 1e-9
                                           or abs(pts[0][1] - pts[-1][1]) > 1e-9):
            pairs.append((n - 1, 0))
        for i, j in pairs:
            b = pts[i][2]
            if abs(b) < 1e-12:
                continue
            x1, y1 = pts[i][0], pts[i][1]
            x2, y2 = pts[j][0], pts[j][1]
            cl_mm = math.hypot(x2 - x1, y2 - y1)
            if cl_mm < 1e-9:
                continue
            sag = abs(b) * cl_mm / 2.0 / 1000.0            # ★ 定义式 b = 2s/c，不带圆心
            if sag < min_sag:
                continue                                   # 弦≈弧，谈不上「弦化」
            try:
                cc, _a1, _a2, R = bulge_to_arc((x1, y1), (x2, y2), b)
            except Exception:
                continue
            s0 = math.atan2(y1 - cc[1], x1 - cc[0])
            s1 = math.atan2(y2 - cc[1], x2 - cc[0])
            d = s1 - s0
            tau = 2.0 * math.pi
            d = (d % tau) if b > 0 else -((-d) % tau)      # 逆时针落 (0,2π)、顺时针落 (−2π,0)
            step_mm = A.SAMP * 1000.0
            k = int(max(2, min(4096, math.ceil(abs(d) * R / step_mm))))
            qs = [to_local(p, cc[0] + R * math.cos(s0 + d * t / k),
                           cc[1] + R * math.sin(s0 + d * t / k), F) for t in range(k + 1)]
            out.append((sg.LineString([to_local(p, x1, y1, F), to_local(p, x2, y2, F)]),
                        sg.LineString(qs), round(sag, 3)))
    return out


def audit_floor(name, p, doc, F, fl, diagnose=False):
    """一层 → 一条 rec（或 None = 这层没有 outline，跳过并**计数**）。"""
    ol = fl.get("outline")
    if not ol:
        return None
    box = (min(q[0] for q in ol), min(q[1] for q in ol),
           max(q[0] for q in ol), max(q[1] for q in ol))
    cov = A._walls_geom(fl)
    mask = A._door_zone_mask(fl)
    stats = {}
    raw = A._source_wall_points(doc, p, F, box, stats)   # ★ 这份 stats 以前从没人传过
    src, door_n = [], 0
    for q in raw:
        if mask and A._in_any_door_zone(q[0], q[1], mask):
            door_n += 1
        else:
            src.append(q)
    cled = {}
    curve, curve_w = curve_segments(doc, p, F, box, cled)

    # ── ② 的两份几何参考（v2，见文件头「② 的口径分解」）──────────────────────
    # 剪枝用**交付墙边线采样点**当 `near`、pad=STRAY_ANY_PAD > WALL_DIST：
    # 「离某个采样点 ≤0.40m 的图元」必落在「≤0.45m」内 ⇒ **不可能被剪掉**（剪枝是保守的）。
    # ★ 剪枝的 near **必须是 xs**，不能是 src 点：用 src 剪会让「没被任何 src 点解释」的
    #   图元先被剪掉，于是 wall/any 两档凭空变小 —— 那正好是会**藏住真缺陷**的方向。
    xs0 = boundary_samples(cov, A.SAMP) if (cov is not None and not cov.is_empty) else []
    wall_geom = any_geom = None
    wall_layers = []
    wled, aled = {}, {}
    # ── ① 的弦化档参考（v3，见文件头「① 的口径分解」）─────────────────────────
    #   只留**矢高 ≥ WALL_DIST** 的段：弦≈弧的那些谈不上「弦化」，不必参与判定
    #   （c113 F0 实测 421 段里只有 71 段过线；c057 F1 一段都没有）。**与 src 无关** ——
    #   参考集有没有点落上去是后面的事，这里只准备「图纸上哪些弧被弦替掉了」这一个事实。
    bulge_arcs = None
    if src:
        bulge_arcs = bulge_chords(doc, p, F, getattr(p, "wall_layer", None) or "4.2墙体")
    if src and xs0:
        wall_layer = getattr(p, "wall_layer", None) or "4.2墙体"
        wall_geom, wall_layers, wled = layer_geoms(doc, p, F, wall_layer, xs0,
                                                   STRAY_ANY_PAD, wled)
        any_geom, any_layers, aled = layer_geoms(doc, p, F, None, xs0, STRAY_ANY_PAD, aled)

    led = dict(
        tread_m=round(stats.get("tread_m", 0.0), 1), tread_runs=stats.get("tread_runs", 0),
        door_n=door_n, door_m=round(door_n * A.SAMP, 1),
        curve_runs=cled.get("runs", 0), curve_fill_block=cled.get("fill_block", 0),
        curve_other_floor=cled.get("other_floor", 0), curve_short=cled.get("short", 0),
        curve_bbox=cled.get("bbox", 0), curve_unflattenable=cled.get("unflattenable", 0),
        # ★ ③ 的作用域排除账（v4）：**逐类计数 + 记米数** —— 出局的曲线不进分母，
        #   但必须看得见（否则「本层无曲要素」与「有，只是被排除了」同形）。
        curve_excl=dict(cled.get("curve_excl", {})),
        # ★ 「没量过」不许写成 0：`_source_wall_points` **内部**还会丢实体
        #   （bbox / 短于 1m / 弧形偏离>0.12 / 填充块 / 超预算），那部分在我**不改**的
        #   那份代码内部，本引擎数不到 ⇒ 如实写「未计数」，不写 0。
        unaccounted=("bbox/短于1m/弧形偏离>0.12m/填充块/超预算 由 "
                     "_dxf_audit._source_wall_points 内部丢弃 ⇒ 本引擎未计数（不是 0）"),
        # ② 的对账尺（v2）：两份参考几何各自收了多少、剪了多少、跳过了多少非线状图元
        geom_caliber=dict(
            wall_n=len(wall_geom or []), any_n=len(any_geom or []),
            wall_pruned=wled.get("pruned", 0), any_pruned=aled.get("pruned", 0),
            wall_unsupported=wled.get("unsupported", 0), any_unsupported=aled.get("unsupported", 0),
            any_skipped_type=aled.get("skipped_type", 0),
            any_layers=len(set(any_layers)) if any_geom else 0),
    )
    rec = measure_floor(src, cov, curve, mask, led, bool(getattr(p, "pair_curved", False)),
                        src_raw=raw, wall_geom=wall_geom, any_geom=any_geom,
                        wall_layers=wall_layers, bulge_arcs=bulge_arcs, curve_w=curve_w)
    rec["building"] = name
    rec["F"] = F
    rec["nwalls"] = len(fl.get("walls", []))
    rec["doors"] = len(fl.get("doors", []))
    rec["stairwells"] = len(fl.get("stairwells", []))
    rec["rooms"] = len(fl.get("rooms", []))
    # 分布池内外都要看得见：池外的层不进分布（与 _dxf_audit.html 的 296 层可比），
    # 但**照样判**（30m 墙全漏也是 100%）。
    rec["in_pool"] = rec["src_m"] >= POOL_MIN_SRC_M
    rec["delivered_union_m2"] = (round(cov.area, 1)
                                 if (cov is not None and not cov.is_empty) else 0.0)
    try:
        rec["outline_m2"] = round(sg.Polygon(ol).area, 1) if len(ol) >= 3 else 0.0
    except Exception:
        rec["outline_m2"] = 0.0
    rec["diag"] = None
    rec["diag_note"] = ("未请求（--diagnose 才问判别器）" if not diagnose
                        else ("漏墙率 %.1f%% < 判别阈值 %.1f%%" % (rec["miss_pct"], DR.THRESH)
                              if rec["miss_pct"] is not None and rec["miss_pct"] < DR.THRESH
                              else "已问"))
    if diagnose and rec["miss_pct"] is not None and rec["miss_pct"] >= DR.THRESH:
        # ★ 判别器只有一份（_dxf_audit_report.classify），这里只**调**它。
        #   它的第二个参数 base_stats 在函数体里根本没用到（读了源码确认），传 rec 只为兼容签名。
        try:
            rec["diag"] = DR.classify(name, F, rec)
        except Exception as e:
            rec["diag"] = {"cls": "ERR %s" % str(e)[:80]}
    # 只给画图用（源点上万，不许进 JSON）；出图后由 audit_building 立刻摘掉
    rec["_src_pts"] = src
    return rec


def audit_building(name, want_overlay=True, diagnose=False, cross=False):
    """一栋楼 → (recs, extra)。extra 里带 cross-check 结果与叠加图的成败（**不静默**）。"""
    p = run_step.load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    fd = os.path.join(BASE, name, "floors")
    floors = sorted(int(os.path.basename(f)[5:-5])
                    for f in glob.glob(os.path.join(fd, "floor*.json")))
    recs, extra = [], {"no_outline": 0, "overlay_fail": 0}
    for F in floors:
        try:
            fl = json.load(open(os.path.join(fd, "floor%d.json" % F), encoding="utf-8"))
            rec = audit_floor(name, p, doc, F, fl, diagnose)
        except Exception as e:
            # 一层崩了不许把整栋抹掉，也不许静默：留一条 UNAVAILABLE 在表上
            recs.append(dict(building=name, F=F, status="UNAVAILABLE",
                             why="本层审计崩了：%s" % str(e)[:110],
                             miss_pct=None, stray_pct=None, curve_miss_pct=None,
                             src_m=0.0, miss_m=0.0, ledger={}, notes=[]))
            continue
        if rec is None:
            extra["no_outline"] += 1
            continue
        sp = rec.pop("_src_pts", None)     # ★ 无条件摘掉：进 JSON 的载荷里不许有上万个点
        if want_overlay:
            png = os.path.join(BASE, name, "audit", "floor%d_wall_audit.png" % F)
            try:
                overlay_png(rec, fl, png, sp)
                rec["overlay"] = os.path.relpath(png, BASE).replace("\\", "/")
            except Exception as e:
                extra["overlay_fail"] += 1
                rec["overlay"] = "画图失败：%s" % str(e)[:80]
        recs.append(rec)
    if cross:
        extra["cross"] = cross_check(name, recs)
    return recs, extra


def cross_check(name, recs):
    """★ 「两把尺子量同一个东西，必须给出同一个数」。

    调 `_dxf_audit.audit_building(name)`（那份 2026-09-14 立的实现）逐层比
    `miss_m / miss_pct / src_m`。**不相等就是本引擎长出了第二套实现** ——
    那正是本仓反复栽的那一类（一个判断多份实现，然后两边各自演化）。
    """
    mine = {r["F"]: r for r in recs}
    bad = []
    # 容差不是放水，是承认两边的**求和方式不同**：_dxf_audit 是 `miss_m += SAMP` 逐点累加，
    # 本引擎是 `len(missed) * SAMP` 一次乘。同一批点在浮点上可能差最后几位，
    # 精确相等会在 3406m 上抖出一个 1e-13，报成「不等」是**假告警**。
    # 0.1m 远小于一个采样(0.35m)，摸不到真实分歧；而且实际最大差每次都打出来给人看。
    TOL = {"miss_m": 0.1, "miss_pct": 0.05, "src_m": 0.1}
    worst = {k: 0.0 for k in TOL}
    try:
        theirs = {r["F"]: r for r in A.audit_building(name)}
    except Exception as e:
        return {"ok": False, "why": "对不上账：_dxf_audit.audit_building 崩了 %s" % str(e)[:80],
                "bad": [], "worst": worst, "tol": TOL, "n_floors": 0}
    for F, r in sorted(theirs.items()):
        m = mine.get(F)
        if m is None:
            bad.append(dict(F=F, why="_dxf_audit 有这层而本引擎没有"))
            continue
        for k in ("miss_m", "miss_pct", "src_m"):
            a, b = m.get(k), r.get(k)
            if a is None or b is None:
                if a != b:
                    bad.append(dict(F=F, why="%s 一边有值一边没有：本引擎 %r vs _dxf_audit %r"
                                    % (k, a, b)))
                continue
            d = abs(float(a) - float(b))
            if d > worst[k]:
                worst[k] = round(d, 4)
            if d > TOL[k]:
                bad.append(dict(F=F, why="%s 差 %.3f > 容差 %.2f（本引擎 %r vs _dxf_audit %r）"
                                % (k, d, TOL[k], a, b)))
    return {"ok": not bad, "bad": bad, "n_floors": len(theirs), "worst": worst, "tol": TOL,
            "why": ("逐层一致（%d 层；miss_m 最大差 %.3fm，容差 %.1fm）"
                    % (len(theirs), worst["miss_m"], TOL["miss_m"])
                    if not bad else "%d 处不等（%s）" % (len(bad), bad[0]["why"][:60]))}


# ── 产物 ────────────────────────────────────────────────────────────

def atomic_json(path, payload):
    """原子写（tmp + os.replace）+ ensure_ascii=False, indent=1 —— 本仓约定（roster.py 同款）。"""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    fd, tmp = tempfile.mkstemp(dir=d or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


COL = dict(src="#111111", miss="#ff7f0e", stray="#d62728", wall="#f2b8b8",
           door="#17becf", stair="#c7e9c0", line="#8b0000")


def overlay_png(rec, fl, out_png, src_pts=None):
    """人眼那一页：**同一批向量**画出来的叠加图（不是另算一份）。

    同一坐标系，**不做任何拟合/配准** —— 图纸线与交付墙本来就是同一套局部米坐标
    （to_local 与 floor JSON 同基准）。做 bbox/质心对齐会把要量测的那个平移误差**消掉**，
    屏幕上变成「对得很齐」（本仓铁律 23(c) 的同族）。
    """
    d = os.path.dirname(out_png)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    fig, ax = plt.subplots(figsize=(17, 9), dpi=95)
    for w in fl.get("walls", []):
        ring = [(float(q[0]), float(q[1])) for q in w.get("poly", [])]
        if len(ring) < 3:
            continue
        para = (w.get("type") == "parapet")
        ax.add_patch(plt.Polygon(ring, closed=True,
                                 facecolor="none" if para else COL["wall"],
                                 edgecolor=COL["line"], alpha=1.0 if para else 0.85,
                                 linewidth=0.6, linestyle="--" if para else "-", zorder=2))
    for s in fl.get("stairwells", []):
        try:
            ax.add_patch(plt.Rectangle((s["x0"], s["yBot"]), s["x1"] - s["x0"],
                                       s["yTop"] - s["yBot"], facecolor=COL["stair"],
                                       edgecolor="#4a7c3f", linewidth=0.4, zorder=1))
        except Exception:
            continue
    for (cx, cy, r) in rec.get("door_mask") or []:
        ax.add_patch(plt.Circle((cx, cy), r, facecolor="none", edgecolor=COL["door"],
                                linewidth=0.5, alpha=0.55, zorder=3))
    srcpt = [(p[0], p[1]) for p in src_pts or []]
    if srcpt:
        a = np.asarray(srcpt)
        ax.scatter(a[:, 0], a[:, 1], s=0.6, c=COL["src"], label="图纸墙线采样（黑）", zorder=4)
    for c in rec.get("miss_clusters") or []:
        ax.scatter([c["cx"]], [c["cy"]], s=26, facecolor="none", edgecolor=COL["miss"],
                   linewidth=1.2, zorder=6)
        ax.add_patch(plt.Rectangle((c["x0"], c["y0"]), c["x1"] - c["x0"] + 0.4,
                                   c["y1"] - c["y0"] + 0.4, facecolor="none",
                                   edgecolor=COL["miss"], linewidth=0.8, linestyle=":", zorder=5))
        ax.text(c["cx"], c["cy"], " 漏%.1fm" % c["len_m"], color=COL["miss"], fontsize=7, zorder=7)
    # ★ v2：**强调的**是 E 类（任何图层上都无对应物 = 真疑问），红色的 ② 总账
    #   降为**细虚线**。v1 把两者画成同一种红框，屏幕上「口径损失」与「模型多建」
    #   长得一模一样 —— 而这正是这一轮要分开的东西（本仓铁律：两者不许同形）。
    for c in rec.get("stray_clusters") or []:
        ax.add_patch(plt.Rectangle((c["x0"], c["y0"]), c["x1"] - c["x0"] + 0.4,
                                   c["y1"] - c["y0"] + 0.4, facecolor="none",
                                   edgecolor=COL["stray"], linewidth=0.5,
                                   linestyle=(0, (1, 3)), alpha=0.7, zorder=5))
    for c in rec.get("stray_any_clusters") or []:
        ax.add_patch(plt.Rectangle((c["x0"], c["y0"]), c["x1"] - c["x0"] + 0.4,
                                   c["y1"] - c["y0"] + 0.4, facecolor="none",
                                   edgecolor="#7a0018", linewidth=1.4, linestyle="-", zorder=6))
        ax.text(c["cx"], c["cy"], " E类%.1fm" % c["len_m"], color="#7a0018",
                fontsize=7, fontweight="bold", zorder=7)
    for c in rec.get("curve_clusters") or []:
        ax.add_patch(plt.Rectangle((c["x0"], c["y0"]), c["x1"] - c["x0"] + 0.4,
                                   c["y1"] - c["y0"] + 0.4, facecolor="none",
                                   edgecolor="#7f0fd6", linewidth=0.9, linestyle=(0, (3, 2)),
                                   zorder=6))
    mp, mpct = rec.get("miss_m"), rec.get("miss_pct")
    sp, spct = rec.get("stray_edge_m"), rec.get("stray_pct")
    apct = rec.get("stray_any_pct")
    # ★ 曲那一栏走 `_curve_txt`，**不在这里自己拼百分数**：图上曾经印过
    #   「曲在册 4 段 155.5m 漏 8.6%」，而这一层其实**没判**（该栋没写 pair_curved）
    #   —— 一个裸百分数会被读成「判过了」（见 `_curve_state` 的 docstring）。
    ttl = ("%s F%d · 状态 %s ｜ 漏墙 %s（%s/%sm）｜ 交付墙边线离图纸 %s（%sm）"
           "【其中 E 类 %s —— 图上任何图层都无对应物】｜ 曲 %s\n"
           "图纸墙线=黑 · 交付墙=浅红(女儿墙虚线) · 门带=青圈 · 漏=橙框 · "
           "② 总账=红细虚框 · **E 类=深红实框(判定只看它)** · 曲墙=紫虚框 "
           "｜ 尺子 v%d·%s · 不拟合、同坐标系叠加")
    ax.set_title(ttl % (rec["building"], rec["F"] + 1, rec["status"],
                        "%s%%" % mpct if mpct is not None else "未量到", mp, rec["src_m"],
                        "%s%%" % spct if spct is not None else "未量到", sp,
                        "%s%%" % apct if apct is not None else "未量到",
                        _curve_txt(rec),
                        CRITERION_VERSION, self_sha12()), fontsize=9, loc="left")
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for sp_ in ax.spines.values():
        sp_.set_visible(False)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(out_png, facecolor="white")
    plt.close(fig)


def _fmt(v, suf="", nd=1):
    return "未量到" if v is None else ("%s%s" % (round(v, nd) if isinstance(v, float) else v, suf))


def _sub(a, b):
    """a - b，**任一个没量到就整体没量到**（不许拿 0 当中性值 —— None 不是 0）。"""
    if a is None or b is None:
        return None
    return round(a - b, 1)


def _dstr(d, n=None):
    """距离分布印成一行：**只看中位数永远看不出「刚过线」还是「真的空」**。"""
    if n == 0:
        return "E 类 0 点（没有要量的距离）"     # 「0 点」与「没量到」不是同一件事
    if not d:
        return "未量到"
    return "p25 %.2f / 中位 %.2f / p90 %.2f / max %.2fm" % (d["p25"], d["p50"], d["p90"], d["mx"])


def _curve_excl_txt(r, with_m=True, short=False):
    """「按作用域排出去了多少」的一句话 —— 三处渲染共用（纯文本）。

    逐类**计数 + 米数**，因为「排除了什么」必须看得见（铁律 23(b)：
    排除规则把真值排除了也是一种坏法，所以要把排除本身数出来）。
    `short=True` 时用 `CURVE_OUT_SHORT` 的短名（终端/图标题那两处用）。
    """
    ex = ((r.get("ledger") or {}).get("curve_excl") or {})
    if not ex:
        return ""
    n = sum(d.get("n", 0) for d in ex.values())
    m = sum(d.get("m", 0.0) for d in ex.values())
    lab = CURVE_OUT_SHORT if short else CURVE_OUT_LABEL
    parts = "；".join("%s %d 段" % (lab.get(k, k), v.get("n", 0))
                     for k, v in sorted(ex.items(), key=lambda kv: -kv[1].get("m", 0.0)))
    return "（另排出 %d 段%s：%s）" % (n, (" %.1fm" % m) if with_m else "", parts)


def _curve_state(r, short=False):
    """③ 曲要素的**唯一判定**。返回 dict(kind, ent, m, pct, ex)。

    `short` 只影响**排除账的标签长短**（渲染细节）；`kind` 这个判定与它无关。

    `kind` 只有三种（**这就是「判了没有」这件事的全部形状**）：
      · `"none"`   —— 本层没有**在册**曲要素（真曲墙 < `CURVE_MIN_M`）
      · `"blind"`  —— 有在册曲要素，但该栋 `pair_curved` 未开 ⇒ **没判**
      · `"judged"` —— 判过，`pct` 才是一个有意义的百分数

    ★ 为什么必须抽成一个函数：这一栏在**三处**渲染（叠加图标题、逐层 stdout、
      楼内/全仓 HTML），而旧版三处各写各的 —— 其中两处直接印 `curve_miss_pct`，
      于是 c113 的盲区层在终端上显示成「曲 在册4段 **8.6%**」（一个裸百分数，
      会被读成「判过了、结果就是这个数」），而**紧接着自己的 `why` 又写**
      「该栋 pair_curved=False ⇒ 曲墙不在识别范围内」—— **同一行自相矛盾**，
      而 HTML 那一份（`_curve_cell`）当时是对的。
      「一个判断只许一份实现」：判断留在这里，三处只负责**渲染**它。
    ★ `"none"` 与 `"blind"` 都是「不判」，但**必须不同形**：
      「本层真没有曲墙」与「有，但我没判」在屏幕上一模一样的话，
      前者会被读成「通过了」、后者会被读成「通过」但其实是盲区（铁律 16 的同族）。
    ★ `"blind"` 那一支**故意不带 `pct`**：`pct` 描述的是「识别器会当墙的那批曲线建了没有」，
      而盲区层根本没有这个前提 ⇒ 印出来就是一个**没有判过的百分数**。
      全仓总目录的图例自己写着「该栋 profile 没写 `pair_curved` 时报『未判』
      **而不是一个百分数**」—— 产物必须跟它自己的承诺一致。
      盲区该带的是**量级**（在册多少段、多少米 ⇒ 盲区有多大），不是结论。
    """
    ex = _curve_excl_txt(r, short=short)
    ent = r.get("curve_ent_n") or 0
    m = _fmt(r.get("curve_m"), "m")
    pct = _fmt(r.get("curve_miss_pct"), "%")
    if (r.get("curve_m") or 0) < CURVE_MIN_M:
        return dict(kind="none", ent=ent, m=m, pct=pct, ex=ex)
    return dict(kind=("judged" if r.get("pair_curved") else "blind"),
                ent=ent, m=m, pct=pct, ex=ex)


def _curve_txt(r):
    """③ 的**纯文本**渲染（逐层 stdout、叠加图标题共用的那一份）。

    排除账走**短名**：终端一行本来就长，把每个原因的解释整句塞进去能到 300 字符，
    读的人会直接跳过整行 —— 而「排除了什么必须看得见」这件事就靠这一行。
    """
    s = _curve_state(r, short=True)
    if s["kind"] == "none":
        return ("无在册曲要素" if s["ex"] else "无曲要素") + (" " + s["ex"] if s["ex"] else "")
    if s["kind"] == "blind":
        return ("未判（盲区：该栋没写 pair_curved；在册 %d 段 %s）%s"
                % (s["ent"], s["m"], s["ex"]))
    return "漏 %s（%d 段 %s）%s" % (s["pct"], s["ent"], s["m"], s["ex"])


def _curve_cell(r):
    """③ 的 **HTML** 渲染（与 `_curve_txt` 同源同判断，只换标记）。

    ★ 裸百分数在这一栏会被读成「已经判过、结果就是这个数」。实测 c113 的曲墙
      （旧口径 1197.7m，真值 70.4m/4 段）落在这支上，而它的状态停在 WATCH ——
      唯一原因是该栋 profile 没写 `pair_curved: True`，于是 ③ 走「不在识别范围内」。
      ⇒ 「未判」与「判了是这个数」必须不同形（本仓铁律 16 的同族）。
    ★ v4 把「不判」那一支**劈成两个形状**：**「本层真没有曲墙」与「有，但全是识别器
      不收的图元」** —— 判定都是「不判」，但后者必须看得见它排掉了多少、为什么排。
      旧口径下 c043 F0 的 14.9% 与 c057 F1 的 17.8% 就是被排掉的那批门弧与柱圆
      充出来的**假红**（那两层一段真曲墙都没有）。⇒ 有排出就把那句话缀在后面。
    """
    s = _curve_state(r)
    tail = (" <small>%s</small>" % s["ex"]) if s["ex"] else ""
    if s["kind"] == "none":
        return ("无<b>在册</b>曲要素" if s["ex"] else "无曲要素") + tail
    if s["kind"] == "blind":
        return ("<b>未判</b>（盲区：该栋 profile 没写 pair_curved；在册 %d 段 %s）%s"
                % (s["ent"], s["m"], tail))
    return "漏 %s（%d 段 %s）%s" % (s["pct"], s["ent"], s["m"], tail)


def building_html(name, recs, extra, when=""):
    """楼内 index：每层一行 + 叠加图 + 链接（不回写成交付件，只在自己目录里加页）。

    `when` 一律由调用方把**同一个**时间戳传进来（与落 `<楼>.json` 用的是同一个变量）：
    页面上印的「生成」和 JSON 里的 `when` 于是是**同一个字段**，不是两次 `strftime`
    各写各的 —— 差一秒就等于「页与表谁新」说不清，而这正是要防的那件事。
    """
    rows = []
    # ① 弦化档的**本栋**合计（逐层印一次不如在这里印一次 —— 但**不许写死别人的数**）
    n_ch = [r for r in recs if (r.get("miss_chord_m") or 0) > 0]
    ch_m = sum((r.get("miss_chord_m") or 0) for r in recs)
    ch_mx = max([((r.get("miss_chord_sag") or {}).get("mx") or 0) for r in recs] or [0])
    for r in sorted(recs, key=lambda x: x["F"]):
        img = ("<img src='%s' loading=lazy>" % os.path.basename(r["overlay"])
               if r.get("overlay") and r["overlay"].endswith(".png") else
               "<b style=color:#b00>%s</b>" % (r.get("overlay") or "未出图"))
        diag = ""
        if r.get("diag"):
            diag = "<br><small>判别：%s %s</small>" % (r["diag"].get("cls", ""), r["diag"].get("off", ""))
        led = r.get("ledger") or {}
        rows.append(
            "<li><b>F%d</b> <span class=st>%s</span> ｜ 漏 总账 <b>%s</b>（%s/%sm）"
            "→ <b class=eq>真实 %s</b>（%sm，弦化档扣 %sm）｜ 多建/歪 <b>%s</b>"
            "（%sm，最近图纸线 %s m）｜ 曲 在册%d段 %s %s ｜ 墙%d 门%d 梯%d 房%d<br>%s"
            "<br><small><b>① 口径分解</b>：总账与真实档只差一件事 —— 参考集取顶点时不展 bulge"
            "（`get_points(\"xy\")`），图纸上的曲墙因此成了<b>弦</b>，按弧建好的交付墙就被读成"
            "「这一带没建」。判定只看<b>真实档</b>；总账照样印，它是与 `_dxf_audit` 逐层对账的"
            "那个数。曲要素另在 ③ 单列，从不混进这两个数的分母。</small>"
            "<br><small><b>② 口径分解</b>：总账 %s ｜ 其中 "
            "<b class=eq>E 类 %s（图上任何图层都无对应物 —— 判定只看它）</b> ｜ "
            "口径损失 %s = 门带掩蔽 %s ＋ 参考集其余规则 %s ＋ 别层有物 %s"
            "（E 类距离分布 %s）</small>"
            "<br><small>排除账：踏步 %s m/%s 段 · 门带 %s m/%s 点 · 曲要素在册 %s 段 → 排出 %s"
            " · 填充块 %s · 别层 %s · 过短 %s · 超框 %s · 展不开 %s ｜ %s</small>%s%s</li>"
            % (r["F"] + 1, r["status"], _fmt(r.get("miss_pct"), "%"),
               _fmt(r.get("miss_m")), _fmt(r.get("src_m")),
               _fmt(r.get("miss_real_pct"), "%"), _fmt(r.get("miss_real_m")),
               _fmt(r.get("miss_chord_m")),
               _fmt(r.get("stray_pct"), "%"),
               _fmt(r.get("stray_edge_m")), _fmt(r.get("stray_med_dist_m")),
               r.get("curve_ent_n") or 0, _fmt(r.get("curve_m"), "m"), _curve_cell(r),
               r.get("nwalls", 0), r.get("doors", 0), r.get("stairwells", 0), r.get("rooms", 0),
               r.get("why", ""),
               _fmt(r.get("stray_pct"), "%"), _fmt(r.get("stray_any_pct"), "%"),
               _fmt(_sub(r.get("stray_pct"), r.get("stray_any_pct")), "%"),
               _fmt(r.get("stray_door_pct"), "%"),
               _fmt(_sub(_sub(r.get("stray_pct"), r.get("stray_any_pct")),
                         r.get("stray_door_pct")), "%"),
               _fmt(_sub(r.get("stray_wall_pct"), r.get("stray_any_pct")), "%"),
               _dstr(r.get("stray_any_dist"), r.get("stray_any_n")),
               _fmt(led.get("tread_m")), led.get("tread_runs", 0),
               _fmt(led.get("door_m")), led.get("door_n", 0), led.get("curve_runs", 0),
               (_curve_excl_txt(r).strip("（）") or "无"), led.get("curve_fill_block", 0),
               led.get("curve_other_floor", 0),
               led.get("curve_short", 0), led.get("curve_bbox", 0),
               led.get("curve_unflattenable", 0), led.get("unaccounted", ""), img, diag))
    xc = extra.get("cross")
    xh = ""
    if xc:
        xh = ("<p class=%s>与 `_dxf_audit` 逐层对账：%s</p>"
              % ("ok" if xc["ok"] else "bad", xc["why"]) +
              ("<ul>" + "".join("<li>F%d %s</li>" % (b["F"] + 1, b["why"]) for b in xc["bad"]) + "</ul>"
               if xc["bad"] else ""))
    return (STYLE +
            "<h1>%s · 建好后墙级对账 <small>（%s）</small></h1>"
            "<p class=leg>图纸墙线 ↔ 交付墙，同一坐标系叠加、<b>不拟合</b>。"
            "判据：点距交付墙 &gt;%.2fm 记漏；交付墙边线离最近图纸点 &gt;%.2fm 记「② 总账」。"
            "★ <b>两个方向都是两段，两段不许同形</b>："
            "① 「漏」= <b>总账 → 真实档</b>（本栋弦化档扣掉 <b>%s</b>，%d 层，最大矢高 %s）："
            "参考集取顶点不展 bulge，图纸上的曲墙在它眼里是<b>弦</b>，而交付墙按弧建 ⇒ 被读成漏。"
            "判定只看真实档；总账照样印，它是与 <a href='_dxf_audit.html'>_dxf_audit</a> 逐层对账的那个数。"
            "② 「多建/歪」= <b>总账 → E 类</b>（判定只看 E 类）：总账里「参考集自己少收的线」"
            "（门带掩蔽／闭口填充／别层有物）与「任何图层都找不到对应物」是两件事，"
            "前者是尺子的口径损失，后者才轮到问模型。"
            "曲要素单列，不混进任何一档的分母；且 ③ 只把<b>识别器真会当墙的那些曲线</b>"
            "算作曲要素（<b>ARC 且半径 ≥2m</b>；该栋走 classify_line 时 ELLIPSE/SPLINE 也不收）"
            "—— 门扇开启弧、整圆、符号椭圆是识别器<b>不收</b>的图元，逐类计数与米数"
            "写在每层的排除账里（本仓铁律 23(b)：排除了什么必须数出来）。"
            "曲长按<b>真实段长</b>累加，不用「点数 × 采样步长」"
            "（`flattening()` 的入参是矢高容差、不是步长，旧口径把米数放大 7.8~20.5 倍）。"
            "尺子 v%d · %s · 生成 %s</p>%s<ul>%s</ul>"
            % (name, extra.get("cross", {}).get("why", "本栋"), A.WALL_DIST, A.WALL_DIST,
               (_fmt(ch_m, "m") if ch_m else "0（本栋无此情形）"), len(n_ch),
               (_fmt(ch_mx, "m") if ch_mx else "0m"),
               CRITERION_VERSION, self_sha12(), (when or time.strftime("%Y-%m-%d %H:%M")),
               xh, "".join(rows)))


STYLE = ("<!DOCTYPE html><html lang=zh><head><meta charset=utf-8>"
         "<title>建好后墙级对账</title><style>"
         "body{font-family:sans-serif;background:#eef0f3;padding:18px;color:#222}"
         "h1{font-size:18px}h1 small{font-weight:400;color:#666;font-size:12px}"
         "p.leg{font-size:12px;color:#555;max-width:1100px}"
         "p.ok{color:#186a3b;font-size:12px}p.bad{color:#b00;font-size:13px;font-weight:600}"
         "a{color:#0366d6;text-decoration:none}li{margin:8px 0;font-size:13px;list-style:none}"
         "img{max-width:100%;border:1px solid #ccd;border-radius:4px;margin-top:6px}"
         "small{color:#777}.st{display:inline-block;padding:0 5px;border-radius:3px;"
         "background:#ddd;font-size:11px}"
         "b.eq{color:#7a0018}"
         "</style></head><body>")


def fleet_html(allrecs, when=""):
    """全仓总目录 —— **只在没给楼名时**才写（与 _dxf_audit.py 的单栋保护同一条规矩）。

    全部行都出自**同一次运行**（不给楼名时 targets = 全库），所以一个运行级 `when`
    对整页是忠实的；它由调用方传进来，与各栋 JSON 的 `when` 同源同格式。
    """
    order = {"GAP": 0, "WATCH": 1, "UNAVAILABLE": 2, "PASS": 3, "NOT_APPLICABLE": 4}
    # 排序用**被判定的那个数**（真实档），不用总账：总账里可能大半是尺子造的，
    # 按它排序会把「尺子造出来的」排在真缺陷前面（c113 F0 总账 4.7% / 真实 1.5%）。
    rows = sorted(allrecs, key=lambda r: (order.get(r["status"], 9),
                                          -(r.get("miss_real_pct") or 0)))
    n = {}
    for r in allrecs:
        n[r["status"]] = n.get(r["status"], 0) + 1
    inpool = [r for r in allrecs if r.get("in_pool")]
    lis = []
    for r in rows:
        if r["status"] == "PASS" and (r.get("miss_real_pct") or 0) < 1:
            continue                      # 干净的层不进总目录（要看得清的都在）
        png = ("%s/audit/floor%d_wall_audit.png" % (r["building"], r["F"])
               if r.get("overlay", "").endswith(".png") else None)
        t = ("<a href='%s'>图</a>" % png) if png else ""
        lis.append("<li><b>%s</b> <span class=st>%s</span> F%d ｜ 漏 总账 %s → "
                   "<b class=eq>真实 %s</b>（%s/%sm，扣弦化 %sm）｜ 多建/歪总账 %s（%sm）"
                   "→ <b class=eq>E 类 %s</b>（%sm）｜ 曲 在册%d段 %s %s ｜ %s %s</li>"
                   % (r["building"], r["status"], r["F"] + 1,
                      _fmt(r.get("miss_pct"), "%"), _fmt(r.get("miss_real_pct"), "%"),
                      _fmt(r.get("miss_real_m")), _fmt(r.get("src_m")),
                      _fmt(r.get("miss_chord_m")),
                      _fmt(r.get("stray_pct"), "%"), _fmt(r.get("stray_edge_m")),
                      _fmt(r.get("stray_any_pct"), "%"), _fmt(r.get("stray_any_m")),
                      r.get("curve_ent_n") or 0,
                      _fmt(r.get("curve_m"), "m"), _curve_cell(r), t,
                      r.get("why", "")[:120]))
    return (STYLE + "<h1>全库 · 建好后墙级对账总目录</h1>"
            "<p class=leg>共 %d 层：%s。按状态排序（GAP → WATCH），同状态内按<b>真实档</b>排。"
            "同一坐标系叠加、<b>不拟合</b>；曲要素单列。<br>"
            "★ <b>两个方向都是两段</b>：「漏」= <b>总账 → 真实档</b>"
            "（后者扣掉「参考集把曲墙弦化」造出来的那批，<b>判定只看真实档</b>；"
            "总账照印，它是与 _dxf_audit 逐层对账的那个数）；"
            "「多建/歪」= <b>总账 → E 类</b>（<b>判定只看 E 类</b>：交付墙边线在<b>任何图层</b>上"
            "都没有对应物）。每一段的<b>前一半都是尺子的口径损失</b>，两段之差都不是缺陷。<br>"
            "★ 曲墙那一栏：该栋 profile 没写 <code>pair_curved</code> 时报「<b>未判</b>」"
            "而不是一个百分数 —— 裸百分数会被读成「判过、就是这个数」，而那是<b>没判</b>。"
            "尺子 v%d · %s · %s</p>"
            "<p class=leg><b>分布池</b>：src_m ≥ %.0fm 的 <b>%d</b> 层（与 "
            "<a href='_dxf_audit.html'>_dxf_audit.html</a> 同一个池子，可逐层比）。"
            "池外另 <b>%d</b> 层：**照判**（30m 墙全漏也是 100%%），只是不进分布。</p><ul>%s</ul>"
            % (len(allrecs), "、".join("%s %d" % kv for kv in sorted(n.items())),
               CRITERION_VERSION, self_sha12(), (when or time.strftime("%Y-%m-%d %H:%M:%S")),
               POOL_MIN_SRC_M, len(inpool), len(allrecs) - len(inpool), "".join(lis)))


# ── 尺子自检：九格，两个阴性对照 ─────────────────────────────────────

def _line(y, x0=0.0, x1=10.0, step=A.SAMP):
    n = max(2, int((x1 - x0) / step))
    return [(x0 + (x1 - x0) * i / n, y) for i in range(n + 1)]


def _arc_pts(r=5.0, step=A.SAMP):
    """半径 r 的半圆，沿**弧长**按 ≈step 取点（r=5 → 45 点、间距 0.357m）。

    ★ 第一版是「按角度取 181 点，再用 `> step*0.5` 过滤」，而半圆上相邻角度点的间距只有
      0.087m ⇒ **全被滤掉，只剩 1 个点**。于是 T5/T6 拿一个退化输入在跑：
      T6 那句「曲漏=0%」在 1 个点上是**恒真**的（本仓铁律 23(a)：饱和的判据没有分辨力）。
      合并后的 T6b 就是为这件事立的（曲墙远离交付墙 ⇒ 必须红）。
    """
    half = math.pi * r
    n = max(2, int(half / step))
    return [(r * math.cos(math.pi * i / n), r * math.sin(math.pi * i / n)) for i in range(n + 1)]


def _seg_w(pts):
    """夹具体的 `curve_w`：**按夹具自己的形状**量段长，末点写 `None`（照 `curve_segments` 的构造）。

    ★ 绝不许「一律填 `A.SAMP`」—— 那正是被修的错口径。夹具若也这么填，T17（量纲）
      与「真实弧长」那一格会**一起绿**，等于把尺子和被测对象一起写错
      （本仓铁律 26：对照的前提必须把要验的那个变量孤立出来）。
    `len(w) == len(pts)` 恒成立；`sum(x for x in w if x)` = 该实体的展开长度。
    """
    if len(pts) < 2:
        return []
    return [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)] + [None]


def selftest():
    """★ 每组都要**能红在指名的理由上**；每组的关键格都配一个**刑具**或**阳性对照**。

    四个阴性对照在场才算尺子：T4（相隔 5m 的两处缺墙不许并成一段）、
    T5（曲要素未开识别时不许判红）、T10（**没有可比对象时不许拿它当结论**）、
    T13 的阴性对照（没有门带掩蔽就不许凭空记一笔「门带吃掉了参考」）。
    T12/T13 是**量具自检**（判近/判远与距离必须同源；三档必须嵌套）——
    它们量的不是被测对象，是这把尺子自己，且各配一个**刑具**（改坏输入要求它抛）。
    再加 T8 那组**边界值**（14.9 必须 WATCH、15.0 必须 GAP）—— 边界值本身写错时，
    只有这组会红（本仓铁律 18 附条：量程把待检对象滤掉了，测了也白测）。
    v3 新增三组，正好把 ① 弦化档拆成三段各验一段：
      · T14 **判词**（`classify_floor`）：判定跟真实档、不跟总账；真实档未知 ⇒ 不判；
      · T15 **用法**（`measure_floor`）：扣不扣的两个条件 (a)(b) **各配一个刑具**，
        外加一对「同一个点只挪离弦距离」的对照；
      · T16 **输入**（`bulge_chords` 直接吃 DXF）：只收墙图层、矢高按定义式、
        **弧顶必须在圆心对面**（镜像位对照 —— 探针就是在这里把弧翻错了边）。

    ★ 夹具的**形状**要跟真产物一致：生产调用点（`audit_floor`）每次都会交代
      「弦化档跑没跑」（传 `bulge_arcs`），所以下面除了 T14~T16 自己控制的那些，
      一律走 `mf()`（= 显式声明「跑了、没有弦」）。**不穿同一件衣服，整组格子量的
      就是「档没跑」而不是它们各自要验的几何** —— 这不是推测：v3 落地当天，
      14 个老格子里有 6 个正是这么变成 WATCH 的。
    """
    bad = 0
    cells = []

    def chk(label, got, want, tol=None):
        nonlocal bad
        if tol is not None and isinstance(want, (int, float)) and isinstance(got, (int, float)):
            ok = abs(got - want) <= tol
        else:
            ok = got == want
        cells.append((label, ok, got, want))
        if not ok:
            bad += 1

    def mf(*a, **kw):
        """自检里的 `measure_floor`：**显式声明「弦化档跑了、这一层没有弦」**。

        生产调用点（`audit_floor`）每次都会传 `bulge_arcs`（可能是空表），所以夹具也得
        交代同一件事 —— 不传的默认是 `None`，而那会读成「档没跑」，① 整层一律 WATCH。
        ★ 只写「不知道」的那一半：T14~T16 要验档本身，它们**直接调** `measure_floor`，
          把 `bulge_arcs` 摆在自己那一行上（免得被这里顺手盖掉 —— 那就白验了）。
        """
        kw.setdefault("bulge_arcs", [])
        return measure_floor(*a, **kw)

    L1 = _line(0.0)
    T1 = mf(L1, sg.box(-0.1, -0.1, 10.1, 0.1))
    chk("T1 干净层：漏墙率=0", T1["miss_pct"], 0.0)
    chk("T1 干净层：状态 PASS", T1["status"], "PASS")
    chk("T1 干净层：交付侧几乎无离群", T1["stray_edge_m"] <= 4 * A.SAMP, True)

    # 平移 1.0m：两侧都要动，且**距离量纲**对（最近距离≈0.9 = 1.0 − 半墙厚 0.1）
    T2 = mf(L1, sg.box(-0.1, 0.9, 10.1, 1.1))
    chk("T2 平移1m：漏墙率=100%", T2["miss_pct"], 100.0)
    chk("T2 平移1m：漏点最近距离≈0.9m（量纲）", T2["miss_med_dist_m"], 0.9, 0.06)
    chk("T2 平移1m：交付侧也报出来（>85%）", T2["stray_pct"] > 85.0, True)
    chk("T2 平移1m：状态 GAP", T2["status"], "GAP")

    L2 = _line(5.0)
    T3 = mf(L1 + L2, sg.box(-0.1, -0.1, 10.1, 0.1))
    chk("T3 缺一面墙：只报 1 段", len(T3["miss_clusters"]), 1)
    chk("T3 缺一面墙：段落点数对", T3["miss_clusters"][0]["n"], len(L2))
    chk("T3 缺一面墙：定位到那一面（y≈5）", round(T3["miss_clusters"][0]["cy"]), 5)

    # ★ 阴性对照：两处都缺 ⇒ 必须是 2 段，不许并成 1 段（判据宽了会误报）
    T4 = mf(L1 + L2, None)
    chk("T4 阴性对照：两处相隔 5m 必须分成 2 段", len(T4["miss_clusters"]), 2)

    # ★ 阴性对照：曲要素不许把直墙账判红
    arc = _arc_pts()
    T5 = mf([], None, arc, None, None, False, curve_w=_seg_w(arc))
    chk("T5 阴性对照：无直墙线时漏墙率是 None（没量到，不是 0）", T5["miss_pct"], None)
    chk("T5 阴性对照：曲要素在、未开识别 ⇒ 不报 GAP", T5["status"] != "GAP", True)
    chk("T5 阴性对照：但盲区必须露出来（WATCH）", T5["status"], "WATCH")

    ring = sg.Point(0, 0).buffer(5.0).boundary.buffer(0.12)
    T6 = mf([], ring, arc, None, None, True, curve_w=_seg_w(arc))
    chk("T6 已建曲墙：曲漏=0%", T6["curve_miss_pct"], 0.0)
    chk("T6 已建曲墙：状态 PASS", T6["status"], "PASS")
    # ★ T6b —— T6 的**分辨力证据**：同一把尺子、同一段弧，交付墙挪到 100m 外 ⇒ 必须报 100%。
    #   没有这一格，T6 在「弧只采到 1 个点」甚至「一个点都没有」时**照样绿**。
    T6b = mf([], sg.box(100.0, 100.0, 110.0, 100.4), arc, None, None, True,
             curve_w=_seg_w(arc))
    chk("T6b 曲墙全没建 ⇒ 曲漏 100%（T6 有没有分辨力，就看这一格）",
        T6b["curve_miss_pct"], 100.0)
    chk("T6b 曲墙全没建 ⇒ GAP", T6b["status"], "GAP")

    # ★ T17 —— ③ 的**量纲**刑具（v4 新增，是本次改口径的那一格）。
    #   一条**点距远小于 SAMP** 的弧：真弧长 π·5 = 15.71m，而 `flattening(0.35)` 会给它
    #   786 个点 ⇒ 旧口径 `点数 × SAMP` = 275.1m（虚高 17.5×）。
    #   ⇒ 这一格要求 `curve_m` 报 **15.7**。把 `curve_m` 改回 `len(curve)*A.SAMP`，
    #     它立刻红成 275 —— 而 T6/T6b 那两条（弧是按 ≈SAMP 采的）**照样绿**：
    #     那两条的夹具点距恰好≈SAMP，量纲错在那上面不可见。这就是为什么必须有这一格。
    arc_fine = _arc_pts(r=5.0, step=0.02)
    T17 = mf([], ring, arc_fine, None, None, True, curve_w=_seg_w(arc_fine))
    chk("T17 量纲：密采样弧上 curve_m 必须是**真实弧长**（π·5=15.7m）",
        T17["curve_m"], round(math.pi * 5.0, 1), 0.3)
    chk("T17 量纲：实体数=1（段重表末尾恰好一个 None）", T17["curve_ent_n"], 1)
    # 分辨力：把这条弧按旧口径写出来的数**必须**明显不同 —— 否则本格量不出东西
    # （本仓 memory: saturated-criterion-has-no-resolution）
    chk("T17 分辨力：旧口径（段数×SAMP）与真值相差 >10× ⇒ 这一格真的能分辨",
        (len(arc_fine) - 1) * A.SAMP > 10.0 * (math.pi * 5.0), True)
    # ★ T17 的**反面对照**：同一条弧、同一个交付环，只把 `curve_w` 换成「全部填 SAMP」
    #   ⇒ 必须复现旧口径。这一格证明上面那格不是被别的什么顺手点亮的。
    T17n = mf([], ring, arc_fine, None, None, True,
              curve_w=[A.SAMP] * (len(arc_fine) - 1) + [None])
    chk("T17 反面对照：段重全填 SAMP ⇒ 必须复现旧口径（证明 T17 真在验量纲）",
        T17n["curve_m"], round((len(arc_fine) - 1) * A.SAMP, 1), 0.2)
    # ★ T17m —— **分子**的量纲（T17 只管分母）。同一条密采样弧**全没建** ⇒
    #   判漏的米数必须是真实弧长 15.7m，不是 786×0.35=275.1m。
    #   ★ 为什么必须另立一格：**只查百分比查不出来** —— 旧口径下分母分子一起虚高
    #     （275.1/275.1）⇒ 曲漏照样是 100%，`curve_miss_pct` 对这件事是**盲的**
    #     （铁律 18 同族：自洽的数证明不了它对）。所以这一格查的是**米数**。
    T17m = mf([], sg.box(100.0, 100.0, 110.0, 100.4), arc_fine, None, None, True,
              curve_w=_seg_w(arc_fine))
    chk("T17m 量纲：判漏的**米数**也必须是真实弧长（不是 点数×SAMP）",
        T17m["curve_miss_m"], round(math.pi * 5.0, 1), 0.3)
    chk("T17m 曲漏 100%（这一格对量纲是盲的 —— 上面那格才查得出来）",
        T17m["curve_miss_pct"], 100.0)

    T7 = mf(L1, None)
    chk("T7 无交付墙几何：全计漏=100%", T7["miss_pct"], 100.0)
    chk("T7 无交付墙几何：交付侧不判（None）", T7["stray_pct"], None)
    chk("T7 无交付墙几何：状态 GAP", T7["status"], "GAP")

    # T8 阈值边界：值本身写错时这两格会红（14.9 必须 WATCH、15.0 必须 GAP）
    # ★ `b` 要照**真记录**的样子给全（含 v3 的两档）—— 这几格验的是阈值本身，
    #   两档给成同一个值，它们就还是原来那件事；缺一档会让它们改验「档没跑」。
    b = dict(src_n=1000, src_m=350.0, curve_n=0, curve_m=0.0, pair_curved=False, ledger={},
             miss_m=52.2, miss_pct=14.9, miss_med_dist_m=0.5, miss_clusters=[],
             miss_chord_n=0, miss_chord_m=0.0, miss_chord_sag=dict(n=0, p50=None, mx=None),
             miss_real_n=100, miss_real_m=52.2, miss_real_pct=14.9,
             cov_edge_m=100.0, cov_edge_sampled_m=100.0, stray_edge_m=5.0, stray_pct=5.0,
             stray_med_dist_m=0.5, stray_near_src_n=0, stray_clusters=[],
             curve_miss_m=None, curve_miss_pct=None, curve_clusters=[], door_mask=[])
    chk("T8 边界 14.9% ⇒ WATCH（不是 GAP）", classify_floor(dict(b))[0], "WATCH")
    # ★ 下面三格每次改 `miss_pct` 都**必须同时改 `miss_real_pct`**：判定看的是后者，
    #   只改前者会让这一格量的变成「另一档」—— 它照样红、照样绿，而量的不是阈值
    #   （本仓铁律 26：错不在断言也不在被测代码，在「我传进去的那份输入并不只差一个变量」）。
    chk("T8 边界 15.0% ⇒ GAP", classify_floor(dict(b, miss_pct=15.0, miss_real_pct=15.0))[0], "GAP")
    chk("T8 边界 4.9% ⇒ PASS", classify_floor(dict(b, miss_pct=4.9, miss_real_pct=4.9,
                                                   stray_pct=0.0))[0], "PASS")
    # T9 交付侧：边线太短时比值不判（小分母的比值会发疯）
    chk("T9 边线<20m ⇒ 不按比值判", classify_floor(dict(b, miss_pct=0.0, miss_real_pct=0.0,
                                                      stray_pct=99.0, stray_edge_m=8.0))[0], "PASS")

    # ★ T14 —— ① 的**判词**（v3）：判定跟「真实档」，不跟总账。
    #   T14a/T14b 是一对：总账都 6.0%（> MISS_WATCH=5），只有真实档一个 1.0 一个 6.0。
    #   若判定还看总账，T14a 会跟着红 —— 绿的那一格就是「扣了才算合格」的正身。
    chk("T14a 总账 6.0% 但真实档 1.0% ⇒ PASS（判定跟真实档，不跟总账）",
        classify_floor(dict(b, miss_pct=6.0, miss_real_pct=1.0, miss_real_m=3.5))[0], "PASS")
    chk("T14b 刑具：同一份记录、真实档改回 6.0% ⇒ 必须 WATCH（证明 T14a 不是空的）",
        classify_floor(dict(b, miss_pct=6.0, miss_real_pct=6.0, miss_real_m=21.0))[0], "WATCH")
    # ★ T14c/T14d —— 「档没跑」这一支（`miss_real_pct is None`）：**不许退回总账去判**。
    #   退回总账正是 v2 那个病（拿被弦化污染的数当结论），所以这里只许 WATCH + 点名。
    _s14, _w14, _r14 = classify_floor(dict(b, miss_pct=0.5, miss_real_pct=None))
    chk("T14c 弦化档没跑（真实档未知）⇒ 不判「漏墙」，必须 WATCH 而不是 PASS", _s14, "WATCH")
    chk("T14d 且理由里必须点名「弦化档」（「没量到」与「量到 0」不许同形）",
        "弦化档" in _w14, True)

    # ★ T10 —— 这一格专验 measure_floor 里 `if not src` 那一支：
    #   删掉它，交付墙边线会整片变成「离图纸墙线最远」⇒ stray_pct=100 ⇒ GAP，
    #   于是「这一层图纸上没有墙线」被报成「这一层模型多建了 100% 的墙」。
    T10 = measure_floor([], ring, arc, None, None, True, curve_w=_seg_w(arc))
    chk("T10 无图纸墙线 ⇒ 交付侧**不许**报成 100% 多建/歪建", T10["stray_pct"], None)
    chk("T10 无图纸墙线 ⇒ 状态不是 GAP", T10["status"] != "GAP", True)
    chk("T10 但必须说明「不判」，不是留空", bool(T10["stray_note"]), True)
    T11 = measure_floor([], ring, [], None, None, False, curve_w=[])
    chk("T11 图纸侧空、交付侧有墙 ⇒ 必须 WATCH（没量到≠通过）", T11["status"], "WATCH")

    # ★ T12 —— 专验「判近/判远」与「报出来的距离」**出自同一次计算**。这一格是踩坑之后补的。
    #   源集里故意放两个**完全重复**的点：`query_nearest` 默认 `all_matches=True` 时并列会
    #   **多出行**，于是 `dists[i]` 不再对应 `xs[i]` —— 实测 c113 F0 是 18445 行 vs 17490 点。
    #   症状是**自相矛盾**而不是报错：「离群 24%，其中位最近距离 0.15m」，
    #   而「离群」的定义就是 >0.40m（铁律 18：自洽的数也可能是错的；这次是不自洽才露馅）。
    #   这一格要求：那唯一一个离群点报出的距离**必须是 5.0**，不是被错位取到的 0.1。
    dup_src = [(0.0, 0.0), (0.0, 0.0), (10.0, 0.0)]
    dup_xs = [(0.10, 0.0), (5.00, 0.0), (10.20, 0.0)]
    try:
        _sp, _sd, _sn = stray_samples(dup_xs, dup_src, A.WALL_DIST)
        t12 = ([round(v, 3) for v in _sd], _sp, _sn)
    except RuntimeError as exc:            # 对齐自检响了 ⇒ 这格红，且要说清是它拦下的
        t12 = ("对齐自检拦下：%s" % exc, None, None)
    chk("T12 重复源点：离群点报出的距离=5.0（判定与距离必须同源）", t12[0], [5.0])
    chk("T12 重复源点：离群的就是那一个远点", t12[1], [(5.0, 0.0)])
    chk("T12 重复源点：近点数=2（重复点不许把近点算丢）", t12[2], 2)

    # ★ T13 —— ② 的**口径分解**（v2）：三档必须嵌套，且「参考被门带吃掉的那一档」
    #   必须**只靠相减**得出（再写一遍「判近」就有机会不一致 —— T12 的教训）。
    #   几何：交付墙 = 10×0.2 的长条，边线就是上下两条长边（相距 0.2 ⇒ 两条都在容差内）。
    #   ★ 参考集必须做成**逐级放大**：掩蔽后到 x=4 ⊂ 未掩蔽到 x=8（门带那一档）
    #     ⊂ 墙图层不过滤几何到 x=6 ⊂ 所有图层到 x=10 —— 四个环互为子集，这才叫嵌套。
    #     （第一版我把 any 写成 x=7 而 wall 写成 x=9.5，**嵌套自检当场把我拦下** ——
    #       那正是它该有的反应，不是故障；写测试的人自己也会把子集关系写反。）
    cov13 = sg.box(0.0, 0.0, 10.0, 0.2)
    src13 = _line(0.10, 0.0, 4.0)          # 掩蔽后的（门带内那一段被删掉）
    raw13 = _line(0.10, 0.0, 8.0)          # 未掩蔽的（补回 x=4..8 那一段）
    wall13 = [sg.LineString([(0.0, 0.10), (6.0, 0.10)])]      # 墙图层不过滤的几何
    any13 = [sg.LineString([(0.0, 0.10), (10.0, 0.10)])]      # 所有图层（⊇ 墙图层）
    T13 = mf(src13, cov13, None, None, None, False, src_raw=raw13,
             wall_geom=wall13, any_geom=any13,
             wall_layers=["4.2墙体"])
    chk("T13 门带那一档：未掩蔽的参考补回来 ⇒ 必须 >0 点（参考确实被门带吃了）",
        (T13["stray_door_n"] or 0) > 0, True)
    chk("T13 嵌套：n_any ≤ n_wall ≤ n_nomask（三份参考集互为子集，破了就是取集/对齐错）",
        T13["stray_any_n"] <= T13["stray_wall_n"] <= T13["stray_nomask_n"], True)
    chk("T13 所有图层都盖满 ⇒ E 类必须正好 0 点（图上处处有对应物）",
        T13["stray_any_n"], 0)
    # 阴性对照：**没有门带掩蔽**时不许凭空说「门带吃掉了参考」
    T13n = mf(src13, cov13, None, None, None, False, src_raw=src13,
              wall_geom=wall13, any_geom=any13, wall_layers=["4.2墙体"])
    chk("T13 阴性对照：src_raw 与 src 同 ⇒ 门带那一档必须正好 0（不许凭空记账）",
        T13n["stray_door_n"], 0)
    # 阳性对照：所有图层只到 x=7（仍 ⊇ 墙图层到 x=6）⇒ E 类必须 >0，
    # 且它报出的距离**必须都 >0.40**（判远与报距离同源，这条纪律从 T12 带到几何这条路上）
    T13b = mf(src13, cov13, None, None, None, False, src_raw=raw13,
              wall_geom=wall13,
              any_geom=[sg.LineString([(0.0, 0.10), (7.0, 0.10)])],
              wall_layers=["4.2墙体"])
    chk("T13 阳性对照：所有图层只到 x=6 ⇒ E 类必须 >0 点", (T13b["stray_any_n"] or 0) > 0, True)
    chk("T13 E 类报出的距离必须都 >0.40m（判远与距离同源）",
        (T13b["stray_any_dist"] or {}).get("p25", 0.0) > A.WALL_DIST, True)
    # ★ 刑具：把 any 档做成**比 wall 档还穷**（模拟「所有图层那一份没取到」）。
    #   这种情况下它会把每一段边线都报成「任何图层都无对应物」= 满屏假缺陷。
    #   嵌套是定义性的，所以这一格**必须抛**，不许静默给出一个漂亮的 E 类。
    try:
        mf(src13, cov13, None, None, None, False, src_raw=raw13,
           wall_geom=wall13, any_geom=[], wall_layers=["4.2墙体"])
        t13bad = "没抛（坏输入被当成了正常结果）"
    except RuntimeError as exc:
        t13bad = "嵌套自检拦下：%s" % str(exc)[:72]
    chk("T13 刑具：any 档比 wall 档还穷 ⇒ 必须抛（不许静默报满屏 E 类）",
        t13bad.startswith("嵌套自检拦下"), True)

    # ★ T15 —— ① 弦化档的**用法**（v3）：扣不扣的两个条件 (a)(b) 各配一个对照，
    #   而且这两个对照**都要求代码里真有那一条** —— 删掉哪一条，对应的那一格就红。
    #   几何能手算：弦 (0,0)→(10,0)、b=+0.4 ⇒ 矢高 2.0m、弧顶 (5,−2.0)、圆心 (5,+5.25)。
    b15 = 0.4
    cc15, _a15, _a2_15, R15 = bulge_to_arc((0.0, 0.0), (10.0, 0.0), b15)
    a0_15 = math.atan2(0.0 - cc15[1], 0.0 - cc15[0])
    a1_15 = math.atan2(0.0 - cc15[1], 10.0 - cc15[0])
    d_15 = (a1_15 - a0_15) % (2.0 * math.pi)            # b>0 ⇒ 逆时针
    n_15 = 400
    arc15 = sg.LineString([(cc15[0] + R15 * math.cos(a0_15 + d_15 * t / n_15),
                            cc15[1] + R15 * math.sin(a0_15 + d_15 * t / n_15))
                           for t in range(n_15 + 1)])
    ch15 = sg.LineString([(0.0, 0.0), (10.0, 0.0)])
    arcs15 = [(ch15, arc15, 2.0)]
    cov15 = arc15.buffer(0.15)          # 弧建了（墙落在弧上）；弦没建（弦离弧 2m）
    g15 = dict(wall_geom=[arc15], any_geom=[arc15], wall_layers=["4.2墙体"])
    pt15 = [(1.0, 0.0), (3.0, 0.0), (5.0, 0.0), (7.0, 0.0), (9.0, 0.0)]
    T15 = measure_floor(pt15, cov15, None, None, None, False, bulge_arcs=arcs15, **g15)
    chk("T15 总账口径不改：弦上 5 点全判漏 ⇒ 100%",
        T15["miss_pct"], 100.0)
    chk("T15 条件 (a)+(b) 都成立 ⇒ 真实档 0 点（弦造的这批全扣掉）", T15["miss_real_n"], 0)
    chk("T15 扣了就要说清扣的是什么：矢高最大 2.0m", T15["miss_chord_sag"]["mx"], 2.0)
    chk("T15 判定跟真实档走 ⇒ PASS", T15["status"], "PASS")

    # (b) 的对照：**弧没建**（交付墙挪到 100m 外）⇒ (a) 单独成立、一个点都不许扣
    T15b = measure_floor(pt15, sg.box(100.0, 100.0, 120.0, 100.4), None, None, None, False,
                         bulge_arcs=arcs15, **g15)
    chk("T15b (b) 的对照：弦在、**弧没建** ⇒ 5 点全留（这条漏是真的，不许被扣掉）",
        T15b["miss_real_n"], 5)
    chk("T15b 扣不掉就还是全漏 ⇒ GAP", T15b["status"], "GAP")

    # (a) 的对照：同一个点、只挪**离弦的距离**（弧仍然建着）
    T15c = measure_floor([(5.0, 1.00)], cov15, None, None, None, False,
                         bulge_arcs=arcs15, **g15)
    T15d = measure_floor([(5.0, 0.01)], cov15, None, None, None, False,
                         bulge_arcs=arcs15, **g15)
    chk("T15c (a) 的对照：离弦 1.00m（>ON_CHORD）⇒ **不许扣**（它不是弦造的）",
        T15c["miss_real_n"], 1)
    chk("T15d (a) 的对照：离弦 0.01m（≤ON_CHORD）⇒ 必须扣", T15d["miss_real_n"], 0)

    # ★ T16 —— ① 弦化档的**输入**（v3）：`bulge_chords` 直接吃 DXF。
    #   三个实体两两只差一个变量：A 墙图层 b=+0.4（矢高 2.0m ⇒ 该收）；
    #   B 墙图层 b=+0.04（矢高 0.2m < 0.40 ⇒ 弦≈弧，不该收）；C 非墙图层 b=+0.4（不该收）。
    #   这一组是**密封**的：自己造 DXF、自己给最小假 profile，不读任何一栋的盘上数据。
    class _P16:
        """最小假 profile —— `to_local` 只需要 `floor_plans` 这一个属性。"""
        floor_plans = {0: (0.0, 0.0)}

    doc16 = ezdxf.new("R2010")
    m16 = doc16.modelspace()
    for x0_16, b16, lay16 in ((0.0, 0.4, "4.2墙体"), (20000.0, 0.04, "4.2墙体"),
                              (40000.0, 0.4, "0")):
        m16.add_lwpolyline([(x0_16, 0.0, 0.0, 0.0, b16),
                            (x0_16 + 10000.0, 0.0, 0.0, 0.0, 0.0)],
                           format="xyseb", dxfattribs={"layer": lay16})
    p16 = _P16()
    c16 = bulge_chords(doc16, p16, 0, "4.2墙体")
    chk("T16 输入：只看墙图层、只留矢高≥0.40 ⇒ 恰好 1 条（B 太直、C 图层不对）", len(c16), 1)
    chk("T16 矢高按**定义式** |b|·c/2 = 2.0m（不是拿圆心算出来的那一档）",
        (c16[0][2] if c16 else None), 2.0, 0.01)
    chk("T16 弦的两端落在本地米 (0,0)–(10,0)（帧换算也要对）",
        ([tuple(round(v, 3) for v in c16[0][0].coords[0]),
          tuple(round(v, 3) for v in c16[0][0].coords[1])] if c16 else None),
        [(0.0, 0.0), (10.0, 0.0)])
    chk("T16 门槛可调：min_sag=0.1 ⇒ 变 2 条（B 那条 0.2m 也进来）",
        len(bulge_chords(doc16, p16, 0, "4.2墙体", min_sag=0.1)), 2)
    #   ★ 镜像位对照 —— 探针就是在这里把弧翻错了边：**矢高对这个完全瞎**（|s| 一样，
    #     镜像后还是 2.0m），只有逐点位置能认出来。弧顶必须在**圆心对面**。
    chk("T16 弧顶在 (5,−2.0)＝圆心对面：到它 ≤5mm",
        (c16[0][1].distance(sg.Point(5.0, -2.0)) if c16 else 9e9) <= 0.005, True)
    chk("T16 镜像位 (5,+2.0) 必须**远**（>1m）—— 探针正是栽在这一格",
        (c16[0][1].distance(sg.Point(5.0, 2.0)) if c16 else 0.0) > 1.0, True)

    # ★ T18 —— ③ 的**作用域**刑具（v4 新增）。分母里不许含识别器根本不收的图元：
    #   旧口径把墙图层上**所有** ARC/CIRCLE/SPLINE/ELLIPSE 都算进「曲要素」，
    #   于是 c043 F0 的 25.2m 全是 18 段门开启弧、c057 F1 的 45.1m 只是一个 r≈0.35m 的圆
    #   —— 两层的 14.9% / 17.8% GAP **全是假红**（那两层一段真曲墙都没有）。
    #   七条曲线两两只差**一个变量**（半径 / 类型 / 该栋走哪个识别器），且全部走
    #   `curve_segments` 这条**生产路径** —— 判据写在助手函数里而生产路径没接上去，
    #   是本仓栽过的那种空判据（memory: executor-must-run-the-gate-itself）。
    class _P18:
        """最小假 profile —— 只给 `curve_segments` 真正读的那几个属性。

        `floor_plans` 的形状照 `profile.frame_center/floor_of` 读的那几栏给：
        `(帧x, 帧y, x下界, x上界)`（毫米）；x 区间放到无穷 ⇒ 这七条全归 F0。
        """
        wall_layer = "4.2墙体"
        classifier = "lwpolyline"
        floor_plans = [(0.0, 0.0, -1e12, 1e12)]

    class _P18L(_P18):
        """只差**一个变量**：这一栋走 `classify_line`（它只收 ARC）。"""
        classifier = "line"

    doc18 = ezdxf.new("R2010")
    m18 = doc18.modelspace()
    m18.add_arc((0, 0), 3000.0, 0.0, 90.0, dxfattribs={"layer": "4.2墙体"})       # 在册
    m18.add_arc((0, 20000), 1000.0, 0.0, 90.0, dxfattribs={"layer": "4.2墙体"})   # 门扇弧
    m18.add_arc((0, 40000), 300.0, 0.0, 90.0, dxfattribs={"layer": "4.2墙体"})    # 更小
    m18.add_circle((0, 60000), 5000.0, dxfattribs={"layer": "4.2墙体"})           # 整圆
    m18.add_ellipse((0, 80000), (500, 0, 0), 0.5, dxfattribs={"layer": "4.2墙体"})
    #   ★ 在册那条必须**细长**（20m×1m）：③ 里还有一道既有的「实心块」判据
    #     （`面积/周长 > 1.0` ⇒ 当块丢掉，照 `_source_wall_points` 抄的）。第一版我
    #     写成 5m×2.5m ⇒ 比值 1.62 被当块丢掉，于是这一格量到的是**那道判据**、
    #     不是作用域（铁律 26：前提必须把要验的那个变量孤立出来）。真图上的椭圆墙
    #     也是细长的，细长才既是「大椭圆」又不触发实心块。
    m18.add_ellipse((0, 100000), (20000, 0, 0), 0.05, dxfattribs={"layer": "4.2墙体"})
    m18.add_line((0, 120000), (5000, 120000), dxfattribs={"layer": "4.2墙体"})    # 直线
    _box18 = (-300.0, -300.0, 300.0, 300.0)
    led18 = {}
    _pts18, w18 = curve_segments(doc18, _P18(), 0, _box18, led18)
    ex18 = led18.get("curve_excl") or {}
    n18 = sum(1 for x in w18 if x is None)          # 在册实体数 = 段重表里 None 的个数
    chk("T18 作用域：在册的只有 ARC r=3m 与大 ELLIPSE 两条", n18, 2)
    chk("T18 作用域：直线根本不进 ③（它归 ① 的直墙账）⇒ 在册仍是 2", n18, 2)
    chk("T18 作用域：门扇开启弧 r=1.0m 必须出局", (ex18.get("arc_door") or {}).get("n"), 1)
    chk("T18 作用域：比门扇还小的弧 r=0.3m 必须出局", (ex18.get("arc_tiny") or {}).get("n"), 1)
    chk("T18 作用域：整圆必须出局（两条识别路径都不收）",
        (ex18.get("circle") or {}).get("n"), 1)
    chk("T18 作用域：符号椭圆（长半轴 0.5m<1m）必须出局",
        (ex18.get("sym_ellipse") or {}).get("n"), 1)
    # ★「排除了什么必须数出来」不只要个数，还要**米数**：记 0 就等于没看见
    #   （铁律 23(b)：排除规则把真值排除了也是一种坏法）。
    chk("T18 排除账：出局的米数也要记（整圆 r=5m ⇒ 周长 31.4m）",
        (ex18.get("circle") or {}).get("m"), 31.4, 0.3)
    # ★ 端到端量纲：在册那条 ARC r=3m 的展开长度 = 四分之一圆 = 4.712m。
    #   段重表第一条实体的段都排在**第一个 None 之前**。
    _i18 = w18.index(None)
    chk("T18 量纲：在册 ARC r=3m 的展开长度 = 四分之一圆 4.71m（不是 点数×SAMP）",
        round(sum(x for x in w18[:_i18] if x), 2), 4.71, 0.02)
    # ★ 只差**一个变量**的对照：同一张图、同一个 box，只有 `classifier` 不同。
    led18l = {}
    _pts18l, w18l = curve_segments(doc18, _P18L(), 0, _box18, led18l)
    ex18l = led18l.get("curve_excl") or {}
    chk("T18 逐栋识别器：同一张图走 classify_line ⇒ 两个 ELLIPSE 都出局（它只收 ARC）",
        (ex18l.get("line_path") or {}).get("n"), 2)
    chk("T18 逐栋识别器：在册从 2 条降到 1 条（只剩 ARC r=3m）",
        sum(1 for x in w18l if x is None), 1)
    chk("T18 逐栋识别器：ARC 那一侧不受影响（门扇弧照样出局、仍只有 1 条）",
        (ex18l.get("arc_door") or {}).get("n"), 1)

    # ★ T19 —— ③ 那一栏的**三种形状**（v4 补）。为什么单立一组：
    #   这一栏在**三处**渲染（叠加图标题、逐层 stdout、楼内/全仓 HTML），而旧版三处各写各的
    #   —— 实测 c113 的四个盲区层（该栋 profile 没写 pair_curved）在**终端**与**图上**都印成
    #   「曲在册 4 段 155.5m 漏 8.6%」，一个**没判过**的裸百分数，而**同一行的 `why`**
    #   紧接着写「⇒ 曲墙不在识别范围内」：**同一行自相矛盾**，且只有 HTML 那份是对的
    #   （本仓既有教训：一个判断只许一份实现）。
    #   判据要钉的**就一件事**：`"blind"` 这一支**不许**出现百分数 —— 它必须长得跟
    #   「判过、就是这个数」不一样（铁律 16：没量到 ≠ 0）。
    r_none = dict(curve_m=0.0, curve_ent_n=0, pair_curved=False, ledger={})
    r_none_ex = dict(curve_m=0.0, curve_ent_n=0, pair_curved=False,
                     ledger={"curve_excl": {"arc_door": dict(n=18, m=25.2)}})
    r_blind = dict(curve_m=155.5, curve_ent_n=4, curve_miss_pct=8.6,
                   pair_curved=False, ledger={})
    r_judged = dict(curve_m=70.4, curve_ent_n=4, curve_miss_pct=5.4,
                    pair_curved=True, ledger={})
    chk("T19 形状① 无曲要素 ⇒ 「无曲要素」", _curve_txt(r_none), "无曲要素")
    #    ★ 形状①与形状①'**必须不同形**：「这层真没有」与「有、但我全排掉了」
    chk("T19 形状①' 有排出 ⇒ 「无在册曲要素」并把排除账带上（两种「不判」不许同形）",
        _curve_txt(r_none_ex).startswith("无在册曲要素") and "另排出 18 段" in _curve_txt(r_none_ex),
        True)
    chk("T19 形状② 盲区 ⇒ 必须印「未判」", "未判" in _curve_txt(r_blind), True)
    chk("T19 形状② 盲区 ⇒ **不许出现裸百分数**（这一格才是真判据，其余格对它是盲的）",
        "8.6" in _curve_txt(r_blind), False)
    chk("T19 形状③ 判过 ⇒ 印出百分数（与盲区不同形）", "5.4%" in _curve_txt(r_judged), True)
    chk("T19 同源：盲区在 HTML 渲染里也是「未判」", "未判" in _curve_cell(r_blind), True)
    chk("T19 同源：判过在 HTML 渲染里也印百分数", "5.4%" in _curve_cell(r_judged), True)
    # ★ 同源的**机械**判据（不靠人记）：两处渲染都从 `_curve_state` 取 kind，
    #   所以「在一个渲染里被读成 blind、在另一个里被读成 judged」这件事**不可能发生**。
    #   下面这格是在**验这条结构**：把 kind 直接与两处的表现对上。
    chk("T19 同源：`_curve_state` 的 kind 就是两处渲染的唯一出处",
        [(_curve_state(r)["kind"], "未判" in _curve_txt(r), "未判" in _curve_cell(r))
         for r in (r_none, r_none_ex, r_blind, r_judged)],
        [("none", False, False), ("none", False, False),
         ("blind", True, True), ("judged", False, False)])

    # ── T20 `--probe` 的写入目录不许有默认值 ──────────────────────────
    # ★ 为什么这格必须存在：`--probe` 是**门禁轮**用的开关，它的全部意义就是
    #   「一个字节都不落在被测栋的目录里」。而这条性质**只由一个 if 保证** ——
    #   把它写坏（回落成 META、或忘了配变量时静默用 META）不会有任何报错，
    #   只会一路安静地重演 2026-09-24 那次实测损坏（三栋视觉页的 <img> 变 0）。
    #   所以喂纯函数三档：给了 / 没给 / 不是 probe 轮。
    def _probe_cell(fl, env):                       # (产物目录, 有没有硬错)
        _d, _e = probe_target(fl, env)
        return (_d, bool(_e))

    chk("T20 probe 的产物目录：调用方给了就用它 / 没给就硬错（**不许**回落到 META）/ 非 probe 轮不写",
        [_probe_cell({"--probe"}, {PROBE_OUT_ENV: r"D:\tmp\x"}),
         _probe_cell({"--probe"}, {}),
         _probe_cell(set(), {PROBE_OUT_ENV: r"D:\tmp\x"})],
        [(r"D:\tmp\x", False), ("", True), ("", False)])

    for label, ok, got, want in cells:
        print("%s %s  实得 %r 期望 %r" % ("✓" if ok else "✗", label, got, want))
    print("尺子自检：%s（%d 格，%d 格不对）" % ("PASS" if not bad else "GAP", len(cells), bad))
    return 1 if bad else 0


# ── 入口 ───────────────────────────────────────────────────────────

def probe_target(flags, env):
    """`--probe` 时产物该写哪儿 —— **纯函数**（自检就靠这一层单独驱动它）。

    返回 `(dir, err)`：不是 probe 轮 ⇒ `("", "")`；是 probe 轮而调用方没给目录 ⇒
    `("", 一句人话)`。

    ★ 这里**故意不存在"默认目录"这个分支**：一旦有默认值，调用方忘了给就会静默写到
      某处，而"产物落在哪"恰恰是出问题时第一个要问的（本仓铁律 16）。宁可硬错。
    """
    if "--probe" not in flags:
        return "", ""
    out = (env.get(PROBE_OUT_ENV) or "").strip()
    if not out:
        return "", ("--probe 必须配 %s（产物写哪儿由调用方说了算，不猜）" % PROBE_OUT_ENV)
    return out, ""


def main():
    names, flags, badf = [], set(), []
    for a in sys.argv[1:]:
        if a.startswith("-"):
            (flags.add(a) if a in FLAGS else badf.append(a))
        else:
            names.append(a)
    if badf:
        print("不认识的开关 %s（本脚本不认 --help；用法见文件头 docstring）" % badf)
        return 2
    if "--selftest" in flags:
        return selftest()
    quiet = "--quiet" in flags
    # ── `--probe`：门禁轮。真跑一遍、产物写到调用方指定的目录，**一个字节都不落在
    #    被测栋的交付目录里**（不写 META/<楼>.json、不写楼内 index.html、不画 PNG）。
    #    为什么"不许猜临时目录"：猜出来的路径会静默生效，而产物落在哪恰恰是
    #    出问题时第一个要问的（本仓铁律 16）。
    probe = "--probe" in flags
    probe_out, probe_err = probe_target(flags, os.environ)
    if probe_err:
        print(probe_err)
        return 2
    if probe_out and not os.path.isdir(probe_out):
        os.makedirs(probe_out)

    known = sorted(d for d in os.listdir(BASE)
                   if os.path.isdir(os.path.join(BASE, d, "floors")))
    if names:
        unknown = [n for n in names if n not in known]
        if unknown:
            # ★ 硬错，**绝不**回落成全库：本仓栽过「--help 被当成楼名 → 按默认全量跑」
            print("不认识的楼名 %s（%d 栋可选，如 %s）—— 不回落成全库"
                  % (unknown, len(known), ", ".join(known[:5])))
            return 2
        targets = names
    else:
        targets = known

    t0 = time.time()
    print("=== 建好后墙级对账：%d 栋（%s）尺子 v%d·%s ==="
          % (len(targets), "全库" if not names else "指定", CRITERION_VERSION, self_sha12()))
    allrecs, extras = [], {}
    for i, name in enumerate(targets, 1):
        try:
            recs, extra = audit_building(name, want_overlay=not (probe or "--no-overlay" in flags),
                                         diagnose="--diagnose" in flags,
                                         cross="--cross-check" in flags)
        except Exception as e:
            print("[%d/%d] %-6s ✗ 整栋崩了：%s" % (i, len(targets), name, str(e)[:110]))
            allrecs.append(dict(building=name, F=-1, status="UNAVAILABLE",
                                why="整栋审计崩了：%s" % str(e)[:110], miss_pct=None,
                                stray_pct=None, curve_miss_pct=None, src_m=0.0, miss_m=0.0,
                                ledger={}, notes=[]))
            continue
        extras[name] = extra
        allrecs += recs
        if extra.get("cross") and not extra["cross"]["ok"]:
            print("    ✗✗ 与 _dxf_audit 对账不等（本引擎可能已长出第二套实现）：")
            for b in extra["cross"]["bad"][:5]:
                print("       F%d %s" % (b["F"] + 1, b["why"]))
        when = time.strftime("%Y-%m-%d %H:%M:%S")
        atomic_json(os.path.join(probe_out or META, "%s.json" % name),
                    dict(name=name, when=when,
                         criterion_version=CRITERION_VERSION, engine_sha12=self_sha12(),
                         wall_dist=A.WALL_DIST, samp=A.SAMP, floors=recs, extra=extra))
        # ★ **一律写楼内 index**（包括 `--no-overlay` 那趟）。旧版把它和出图绑在一起，
        #   后果实测过：c057 的 `audit/index.html` 是 19:34 那次（带图）写的，
        #   而 `<楼>.json` 被 19:40 那次 `--no-overlay` 重写了 ⇒ **页面与 JSON 是两个轮次的数**
        #   躺在同一个目录里，而屏幕上没有任何东西说这件事（本仓铁律 24 那一族）。
        #   绑在一起的动机原本是「不出图就别写只剩破图的页」—— 但 `building_html` 对
        #   `overlay=None` 本来就是诚实的（逐层印红字「未出图」），不需要靠不写来回避。
        # ★ 这里必须自己建目录：`audit/` 一直是靠 `overlay_png` 顺手建的
        #   （`overlay_png:1337`），而 PNG 那一步在「本层没有轮廓」时会**先 continue**
        #   （`no_outline`）。于是「整栋一层 PNG 都没写」的楼跑到这一行就
        #   `FileNotFoundError` —— 而它落在**逐栋循环体内**，全库重跑会**整趟死在这一栋**，
        #   前面所有栋的数白量（本仓铁律 20 那一族：跑了一半、屏幕上看不出死因）。
        d = os.path.join(BASE, name, "audit")
        if probe:
            # ★ 门禁轮**不动被测栋的视觉产物**（见 PROBE_OUT_ENV 那段）：页面与 PNG
            #   属于「出图那一轮」，门禁的产物在 probe_out 里。写与不写都**明说一行** ——
            #   「没写页面」和「写了但页面坏了」在屏幕上必须不是同一行字。
            print("     （--probe：产物 → %s；**不写** %s/audit/index.html、不画 PNG —— "
                  "门禁轮不改被测栋的视觉产物）" % (probe_out, name))
        else:
            if not os.path.isdir(d):
                os.makedirs(d)
            with io.open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(building_html(name, recs, extra, when))
        g = [r for r in recs if r["status"] not in ("PASS", "NOT_APPLICABLE")]
        print("[%d/%d] %-6s %d 层，需看 %d 层%s"
              % (i, len(targets), name, len(recs), len(g),
                 ("（对账 %s）" % extra["cross"]["why"]) if extra.get("cross") else ""), flush=True)
        if not quiet:
            for r in sorted(recs, key=lambda x: (x["status"] == "PASS",
                                                 -(x.get("miss_real_pct")
                                                   if x.get("miss_real_pct") is not None
                                                   else (x.get("miss_pct") or 0)))):
                if r["status"] == "PASS" and (r.get("miss_real_pct") or 0) < 1:
                    continue      # 干净层不逐行刷屏；它仍在 JSON 与总目录里
                print("     F%-2d %-14s 漏 %-6s→%-6s（%s/%sm）②总账 %-6s → E类 %-6s ｜ 曲 %s ｜ %s"
                      % (r["F"] + 1, r["status"], _fmt(r.get("miss_pct"), "%"),
                         _fmt(r.get("miss_real_pct"), "%"),
                         _fmt(r.get("miss_m")), _fmt(r.get("src_m")),
                         _fmt(r.get("stray_pct"), "%"), _fmt(r.get("stray_any_pct"), "%"),
                         # ★ 不在这里印 `curve_miss_pct`：盲区层（该栋没写 pair_curved）
                         #   会印出一个**没有判过**的裸百分数，而同一行的 `why` 又说
                         #   「不在识别范围内」—— 同一行自相矛盾。判断在 `_curve_state`。
                         _curve_txt(r),
                         (r.get("why") or "")[:64]))

    n = {}
    for r in allrecs:
        n[r["status"]] = n.get(r["status"], 0) + 1
    print("\n=== 结论（%d 层，%.0fs）===" % (len(allrecs), time.time() - t0))
    print("  " + "、".join("%s %d" % kv for kv in sorted(n.items())))
    npool = [r for r in allrecs if r.get("in_pool")]
    print("  分布池（src_m≥%.0fm）%d 层，池外 %d 层（照判、不进分布）—— 分母就在这里，"
          "便于与 _dxf_audit.html 逐层比" % (POOL_MIN_SRC_M, len(npool),
                                              len(allrecs) - len(npool)))
    nmiss = [r for r in allrecs if r.get("miss_pct") is None]
    if nmiss:
        print("  其中 %d 层**没量到**漏墙率（图纸墙图层上没有可用直墙线）——"
              "不是 0%%：%s" % (len(nmiss), "、".join("%s F%d" % (r["building"], r["F"] + 1)
                                                     for r in nmiss[:8])))
    # ★ ① 的两档**必须分开印**（v3）：拿总账去判，实测 c113 F0 有 92.3% 是尺子造的
    for key, lbl in (("miss_pct", "① 总账（图纸采样点离交付墙 >0.40m）"),
                     ("miss_real_pct", "★ 真实档（扣掉参考集把弧弦化造的；判定只看它）")):
        vs = sorted(r[key] for r in allrecs if r.get(key) is not None)
        if vs:
            print("  %s：%d 层有值，中位 %.1f%%，≥%.0f%% 的 %d 层"
                  % (lbl, len(vs), vs[len(vs) // 2], MISS_WATCH,
                     sum(1 for v in vs if v >= MISS_WATCH)))
    nreal = [r for r in allrecs if r.get("miss_pct") is not None
             and r.get("miss_real_pct") is None]
    if nreal:
        print("  其中 %d 层**没量到**真实档（弦化档没跑）⇒ ① 不判 —— 这不是「没有漏墙」"
              % len(nreal))
    cut = [r for r in allrecs if r.get("miss_chord_m")]
    if cut:
        print("  弦化档扣掉了 %d 层共 %.1fm 的「漏」（其中矢高最大者 %.1fm —— 弦离弧那么远，"
              "弦上那批点不可能是图纸上的墙）"
              % (len(cut), sum(r["miss_chord_m"] for r in cut),
                 max((r.get("miss_chord_sag") or {}).get("mx") or 0 for r in cut)))
    # ★ ② 的两档**必须分开印**：它们以前是同一个数（v1 只印前者，判定也只看前者）
    for key, lbl in (("stray_pct", "② 总账（离掩蔽后的图纸点的距离>0.40m）"),
                     ("stray_any_pct", "★ E 类（任何图层都无对应物；判定只看它）")):
        vs = sorted(r[key] for r in allrecs if r.get(key) is not None)
        if vs:
            print("  %s：%d 层有值，中位 %.1f%%，≥%.0f%% 的 %d 层"
                  % (lbl, len(vs), vs[len(vs) // 2], STRAY_WATCH,
                     sum(1 for v in vs if v >= STRAY_WATCH)))
    nany = [r for r in allrecs if r.get("stray_pct") is not None and r.get("stray_any_pct") is None]
    if nany:
        print("  其中 %d 层**没量到** E 类（口径分解没跑）⇒ ② 不判 —— 这不是「没有多建」"
              % len(nany))
    hard = [r for r in allrecs if r["status"] in ("GAP", "WATCH")]
    hard.sort(key=lambda r: -(r.get("miss_real_pct")
                              if r.get("miss_real_pct") is not None else (r.get("miss_pct") or 0)))
    for r in hard[:15]:
        print("  · %-6s F%-2d %-10s %s" % (r["building"], r["F"] + 1, r["status"],
                                           (r.get("why") or "")[:90]))
    if names or probe:
        print("  （指定楼名/probe 模式：**不写**全仓总目录 data/buildings/_wall_audit.html）")
    else:
        with io.open(os.path.join(BASE, "_wall_audit.html"), "w", encoding="utf-8") as fh:
            fh.write(fleet_html(allrecs, time.strftime("%Y-%m-%d %H:%M:%S")))
        print("  写 data/buildings/_wall_audit.html（全仓总目录）")
    print("  JSON 落 %s/<楼>.json" % (probe_out or "data/_meta/wall_audit"))
    if n.get("UNAVAILABLE"):
        return 2
    return 1 if n.get("GAP") else 0


if __name__ == "__main__":
    sys.exit(main())
