# -*- coding: utf-8 -*-
"""控制台的「参数化 + 流程化」元数据（单一事实源）。

为什么单独一个模块：控制台要展示的**全部**可调参数（档案 + 规格）与**全部**流程阶段，
必须在一处集中定义、由后端下发给前端。前端不再硬编码字段表——
否则加一个 profile 字段要改两个地方，必然漂移。

三张表：
  PROFILE_GROUPS  —— data/buildings/<name>/profile.json 的字段（识别阶段参数）
  SPEC_GROUPS     —— <name>/spec.json 的字段（建模阶段参数，GLB 几何全靠它）
  PIPELINE        —— 从 DWG 到索引的完整阶段链（含每阶段产物、作用域、危险级别）
                     ★ **事实源是 `config/pipeline.json`**，本模块的 `PIPELINE_FALLBACK`
                       只是读不到配置时的回落。要改流程/加阶段/改机位，改那个 JSON。

不变式（`self_check()` 在启动时校验，非致命只告警）：
  · SPEC_GROUPS 的每个 key 都必须是 build_standard_glb 真实消费的键
  · PROFILE_GROUPS 的每个 key 都必须在 `config/branches.json` 里有**消费者**
    （`consumers` 列非空），且必须**登记在册** —— 页面上能改但没人读 = 死旋钮，
    改了不生效且不报错；这条闸就是为它设的（用户「写在后台、我后面能修改」）
  · PIPELINE 里 runnable=True 的阶段，其脚本必须真的接受单栋 argv
    （`_wall_thin_batch.py` / `convert_dwg_to_dxf.py` 忽略 argv、会跑全仓，故标 runnable=False）
  · **值送得到吗**：PROFILE_GROUPS 的每个 key 都必须被**至少一条投递通道**读到 ——
    「有消费者」只答了「有人读这个键名」，答不了「这个值真被送进流程」。
    通道是**列出来的、有名字的**（`_delivery_channels()`）。
    ★ 这里**故意不写条数、也不列通道名** —— 写在这里的数是一次**带时刻的测量**，
      而新增通道的人不会回来改这段文档；写下的数与表里此刻的条数对不上时，
      两句话**在屏幕上同样通顺**，所以这个数过期了**不报错**。
      本段原先就写着一个条数并列了对应那几个名字，而表后来被加过行 ——
      **要引用条数与名字，读 `_delivery_channels()` 此刻的返回**，别抄文档。
    ★ 通道表是**手抄的**（本仓「一个判断多份实现」的老毛病）⇒ 新增一条投递通道
      必须显式加一行；漏一条的后果与死旋钮**长得一模一样**（改了不生效、不报错），
      成因却相反：死旋钮是「没人读」，这里是「值根本没到」。
    ★ 两档的措辞必须**点明是哪条路**：「影响识别吗」「批量那条路读不读」——
      只说「不影响识别」会把「批量出图不读它」这个真缺口盖掉。
"""
import json
import os

# 字段 type 语义（前端渲染 + 回写转换）：
#   text  字符串 | num 浮点 | int 整数 | bool 复选 | select 下拉
#   list  逗号分隔数字列表 → [float, ...]
#   json  结构化数组/对象 → 原样 JSON（在「高级」区编辑）
PROFILE_GROUPS = [
    {"group": "① 基本信息", "fields": [
        {"k": "title", "label": "中文名", "type": "text",
         "help": "只影响显示，不参与几何"},
        {"k": "classifier", "label": "分类器", "type": "select",
         "options": ["lwpolyline", "line"],
         "help": "唯一的分类器分派开关。lwpolyline = 闭合多段线约定（47 栋）；"
                 "line = LINE 双线+INSERT 约定（仅 c006 逸夫楼）"},
        {"k": "dxf", "label": "DXF 路径", "type": "text",
         "help": "源图纸绝对路径，管线第一步的输入"},
        {"k": "rooms", "label": "rooms.json 路径", "type": "text",
         "help": "房间标注来源；不存在时识别会自动建空表"},
        {"k": "out_dir", "label": "楼层输出目录", "type": "text",
         "help": "floor*.json 落盘处。批次楼 = data/buildings/<name>/floors；"
                 "GLB 落在其父目录"},
    ]},
    {"group": "② 坐标变换（毫米）", "fields": [
        {"k": "offset", "label": "层偏移 offset", "type": "num", "step": 1000,
         "help": "均匀楼每层沿 Y 的排布间距。floor = round((y-cy)/offset)"},
        {"k": "cx", "label": "中心 X", "type": "num", "step": 1000,
         "help": "局部坐标原点 X。所有几何先减它落到米制局部系"},
        {"k": "cy", "label": "中心 Y", "type": "num", "step": 1000,
         "help": "局部坐标原点 Y（首层中心）"},
    ]},
    {"group": "③ 图层约定", "fields": [
        {"k": "wall_layer", "label": "墙/门/台阶图层", "type": "text",
         "help": "三者共用同一图层，靠几何形状区分"},
        {"k": "column_layer", "label": "结构柱图层", "type": "text",
         "help": "留空 = 该图无独立柱图层（识别出 0 柱属忠实结果，非缺陷）"},
    ]},
    {"group": "④ 构件分类", "fields": [
        {"k": "door_min_points", "label": "门点数阈值", "type": "int",
         "help": "仅 door_by_points=True 时生效：多段线点数 ≥ 此值判为门"},
        {"k": "stair_points", "label": "台阶点数", "type": "int",
         "help": "仅 door_by_points=True 时生效：点数 == 此值判为台阶"},
        {"k": "door_by_points", "label": "按点数判门", "type": "bool",
         "help": "True=点对判据（仅理化楼）。False=通用 _hinge_leaf 判据"
                 "（两条轴对齐、等长、互垂、共铰链端点）。改错会让门全丢或全假"},
    ]},
    {"group": "⑤ 墙皮配对（米）", "fields": [
        {"k": "wall_min", "label": "墙厚 min", "type": "num", "step": 0.01,
         "help": "小于此间距不配成墙（防细线当墙）"},
        {"k": "wall_max", "label": "墙厚 max", "type": "num", "step": 0.01,
         "help": "大于此间距不配成墙（防粗环/巨块当墙）"},
        {"k": "wall_extend", "label": "墙段外延", "type": "num", "step": 0.01,
         "help": "配对前墙段沿走向延长，补图纸端点虚接触"},
        {"k": "wall_fallback", "label": "单边墙厚兜底", "type": "num", "step": 0.01,
         "help": "无配对时按此厚度成墙"},
        {"k": "single_wall_t", "label": "单线墙可见厚", "type": "num", "step": 0.01,
         "help": "line 约定下孤线（门垛/短段/女儿墙）的渲染厚度，不冒充有厚度的墙"},
        {"k": "outer_wall_t", "label": "外墙厚", "type": "num", "step": 0.01,
         "help": "外墙无内皮线可配对的楼，按此单向 buffer 成实体（理化楼门垛实测 0.24）"},
        {"k": "wall_thicknesses", "label": "真实墙厚集合", "type": "list",
         "help": "从图纸双线间距直方图读出，如 0.24,0.27,0.35。"
                 "配对的中间值会 snap 到最近真值并 recenter，消除「有的墙很厚」。留空=不 snap"},
    ]},
    {"group": "⑥ 门（米）", "fields": [
        {"k": "door_w_single", "label": "单扇门宽", "type": "num", "step": 0.1},
        {"k": "door_w_double", "label": "双扇门宽", "type": "num", "step": 0.1},
        {"k": "door_depth", "label": "门洞深", "type": "num", "step": 0.1,
         "help": "门洞盒深度基准。实际取 max(外墙厚,内墙厚)+0.05 —— "
                 "必须比墙厚深，门才是 gap 不是 hole"},
    ]},
    {"group": "⑦ 楼板轮廓（米）", "fields": [
        {"k": "outline_buf", "label": "轮廓缓冲", "type": "num", "step": 0.01},
        {"k": "open_r", "label": "开运算半径", "type": "num", "step": 0.01,
         "help": "去掉毛刺/孤立碎片"},
        {"k": "outline_close_r", "label": "闭运算半径", "type": "num", "step": 0.01,
         "help": "LINE 墙被门洞断成碎带时先桥接再回缩成封闭足迹。"
                 "0=不闭运算（LWPOLYLINE 楼已有闭合填充矩形）"},
        {"k": "parapet_margin", "label": "女儿墙余量", "type": "num", "step": 0.1},
        {"k": "outline_unify", "label": "统一 footprint", "type": "bool",
         "help": "多翼/阶梯楼低层墙 union 碎片化时，全楼复用「最完整那层」的轮廓。"
                 "退台楼误用会把塔楼盖成裙楼轮廓"},
        {"k": "outline_unify_floors", "label": "统一足迹的楼层子集", "type": "list",
         "itype": "int",
         "help": "只统一指定层（如裙楼 0-5），塔楼/过渡层各自推导。优先于上面的总开关"},
    ]},
    {"group": "⑧ 层高", "fields": [
        {"k": "layer_height", "label": "层高（米）", "type": "num", "step": 0.1},
        {"k": "slab", "label": "楼板厚（米）", "type": "num", "step": 0.05},
    ]},
    {"group": "⑨ 高级结构（JSON / 列表）", "fields": [
        {"k": "x_range", "label": "X 隔离区间", "type": "list",
         "help": "图纸多栋并排/重复复制时只取主列（毫米）。留空=不隔离"},
        {"k": "pair_curved", "label": "识别斜墙/曲墙", "type": "bool",
         "help": "默认关：轴对齐段走原配对，剩下的斜段/弧弦交给 pair_curved_faces。"
                 "开=无斜墙的楼一个字节都不变"},
        {"k": "floor_ys", "label": "逐层 Y 中心", "type": "json",
         "help": "阶梯楼各层平面在图上非均匀排布（裙楼宽、塔楼窄交错），"
                 "单 offset 表示不了。留空=均匀楼"},
        {"k": "floor_plans", "label": "逐层 [cx,cy,xmin,xmax]", "type": "json",
         "help": "两列布局（裙楼+塔楼分列 X）如 c006。X 先判列，列内按 Y 最近取层。"
                 "留空=单列楼"},
        {"k": "transition", "label": "过渡层规则", "type": "json",
         "help": "如 {\"6\": {\"slab_from\": 5, \"wall_x\": [x0,x1]}} —— "
                 "楼板全宽但墙只占窄条（六教第 7 层：裙楼屋面 + 塔楼耸起）"},
    ]},
    # ★ 这一组就是「单独流程」：**按楼不同、必须逐栋决定**的那些开关。
    #   目的：它们以前只活在 profiles/*.py 与注册表里，用户在参数页上看不见 ⇒ 改不了。
    #   进这一组的前提（**逐条实测过，不是按同族推的**）：`run_building.load_profile`
    #   真的读它 —— 控制台保存是直接合并写 `data/buildings/<name>/profile.json`，
    #   而批量通道读同一个文件 ⇒ 「页面上改得动」与「流程真的变」才是同一件事。
    #   `floor_y_bands` **故意不进**：它批量通道不读，且 2026-09-24 接上后
    #   6/6 栋在 recognize.py 的 sorted({…None…}) 直接崩（窗口外 floor_of 故意返回 None）。
    {"group": "⑩ 单独流程（按楼不同，逐栋定）", "fields": [
        {"k": "room_route", "label": "房间路由", "type": "select",
         "options": ["", "auto", "single"], "step": "rooms",
         "help": "房间从哪来。auto=逐层按图纸房号择优；single=读交付墙（单源墙路）；"
                 "留空=走**主线**（默认）。★ 主线那个分支内部自报的名字叫 regen，"
                 "但 regen **不是这里能填的取值**（本下拉里也没有它）—— 实测 96 栋里"
                 "0 栋填过它，手填它也只是落回主线，与留空**同一支**。"
                 "**这一项决定后面几项生不生效**："
                 "room_seal / room_grow_to_wall 只对 auto 或 single 路生效"},
        {"k": "room_seal", "label": "房间密封（米）", "type": "num", "step": 0.05,
         "help": "房号 polygon 封口的容差。只对 room_route=auto/single 生效；"
                 "留空=0（不密封）。c006 实值 0.08"},
        {"k": "room_grow_to_wall", "label": "房间长到墙（米）", "type": "num", "step": 0.05,
         "help": "房间边界往外顶到墙线的距离。只对单源墙路（room_route=single）生效；留空=0"},
        {"k": "rooms_from_floors", "label": "房间取自 floors（旧）", "type": "bool",
         "help": "★ 已由「房间路由」取代，只为老楼保留。开=等价于 room_route=single。"
                 "新楼请用 room_route，不要两个都设"},
        {"k": "label_nearest_max", "label": "房号远置阈值（毫米）", "type": "num", "step": 100,
         "help": "房号标注画在楼外（ny27 式）时，容纳「标注→房间」的最大距离。"
                 "留空=0=只认标注落在房间里的常规图"},
        {"k": "keep_courtyard_holes", "label": "保留内院洞", "type": "bool",
         "help": "回字形平面有真实内院/天井的楼：开=轮廓不把内院填实。默认关"},
        {"k": "tread_cluster_filter", "label": "踏步线过滤", "type": "bool",
         "help": "斜向楼梯踏步线画在**墙体图层**上的楼（c006 实测）：开=把这类簇从墙里剔掉。"
                 "默认关；无此病的楼开了会少墙"},
        {"k": "sheet_floors", "label": "一图多层", "type": "json",
         "help": "一张图描述多层（如通高圆厅）时的展开规则。留空=一图一层"},
        {"k": "outdoor_steps", "label": "室外大台阶", "type": "json",
         "help": "图上有室外大台阶的楼，**故意不自动判**（自动判会命中室内楼梯间）。"
                 "留空=不做。形如 {\"0\": [[x, y, 宽, 高, ...]]}"},
        {"k": "roof_rooms", "label": "屋面封顶", "type": "json",
         "help": "下层是该房间、本层图上没有楼板的地方要封顶（塔楼出屋面处）。"
                 "形如 {\"4\": [\"6-C-04-05\"]}；留空=不做"},
        {"k": "atrium_rooms", "label": "中庭房间表", "type": "json",
         "help": "中庭：**该层图上有这个房间登记** ⇒ 挖洞。形如 {\"层\": [\"房号\"]}；"
                 "与「中庭来源层」配对使用，两者都留空=不处理中庭"},
        {"k": "atrium_from", "label": "中庭来源层", "type": "json",
         "help": "中庭：**只补围护墙、不挖洞**（封顶层图上不画八角厅）。"
                 "形如 {\"层\": 源层}；与「中庭房间表」配对"},
    ]},
    {"group": "⑪ 建模输出口径（控制台记账用，不参与识别）", "fields": [
        {"k": "glb_windows", "label": "导出合成窗", "type": "bool",
         "help": "该楼重出 GLB 时是否带 synthetic 窗。**必须记账**："
                 "所有 floor JSON 的窗都是 synthetic=True，本键是唯一的开关。"
                 "★ 实测（2026-09-26，两臂逐字节比对）：run_building --glb **不读本键** —— "
                 "批量路的模块默认就是 True，`--windows` 是空操作；"
                 "只有控制台这条路（run_step）读它。"
                 "★ 本键不止管 GLB：SU 交付规格（su_spec_floors_fleet.py）读同一个键，"
                 "决定 .skp 里有没有合成窗。"},
        {"k": "skip_floors", "label": "导出时剔除的层", "type": "json",
         "help": "要从模型里去掉的层号列表（0 基，如 [0] = 不要首层）。"
                 "**只影响 GLB 导出，floor JSON 一个字节都不动**，随时删掉本键即可恢复。"
                 "保留的层会重新落到地面（标高按剩余层数重排），"
                 "所以只适合从**最底下**往上剔层——剔中间层会让上面的层凭空下沉。"},
    ]},
]

SPEC_GROUPS = [
    {"group": "① 楼层与楼板", "fields": [
        {"k": "floor_h", "label": "层高 floor_h", "type": "num", "step": 0.1,
         "help": "GLB 里第 F 层标高 = F * floor_h，全楼用同一值"},
        {"k": "slab_t", "label": "楼板厚 slab_t", "type": "num", "step": 0.05},
    ]},
    {"group": "② 墙体", "fields": [
        {"k": "wall_h", "label": "墙高 wall_h", "type": "num", "step": 0.1,
         "help": "墙从楼板顶起算的净高。墙上部留空 = floor_h - slab_t - wall_h"},
        {"k": "outer_wall_t", "label": "外墙厚", "type": "num", "step": 0.01,
         "help": "门头过梁厚度取此值（外门）"},
        {"k": "inner_wall_t", "label": "内墙厚", "type": "num", "step": 0.01,
         "help": "门头过梁厚度取此值（内门）"},
    ]},
    {"group": "③ 门", "fields": [
        {"k": "door_h", "label": "门高", "type": "num", "step": 0.1,
         "help": "门板高度；门顶以上补回过梁（墙从 door_h 补到 wall_h）"},
        {"k": "door_panel_t", "label": "门板厚", "type": "num", "step": 0.01},
    ]},
    {"group": "④ 柱", "fields": [
        {"k": "column_w", "label": "柱宽（兜底）", "type": "num", "step": 0.1,
         "help": "仅在该层柱无实测尺寸时使用"},
        {"k": "column_d", "label": "柱深（兜底）", "type": "num", "step": 0.1},
    ]},
    {"group": "⑤ 合成窗（DXF 无窗时沿外墙等距生成）", "fields": [
        {"k": "win_sill", "label": "窗台高", "type": "num", "step": 0.1},
        {"k": "win_h", "label": "窗高", "type": "num", "step": 0.1},
        {"k": "win_w", "label": "窗宽", "type": "num", "step": 0.1},
        {"k": "win_spacing", "label": "窗间距", "type": "num", "step": 0.1,
         "help": "沿外墙等距布窗的步长"},
        {"k": "win_in_depth", "label": "内凹深", "type": "num", "step": 0.01,
         "help": "窗洞往墙内侧挖的深度（墙面凹进）"},
        {"k": "win_out", "label": "外凸", "type": "num", "step": 0.01},
        {"k": "glass_t", "label": "玻璃厚", "type": "num", "step": 0.01},
        {"k": "win_frame_t", "label": "窗框厚", "type": "num", "step": 0.01,
         "help": "铝合金窗框型材厚度"},
        {"k": "win_margin", "label": "端点避让", "type": "num", "step": 0.1,
         "help": "墙两端各留出这么长不放窗（避开转角）"},
        {"k": "win_min_seg", "label": "最小墙长", "type": "num", "step": 0.1,
         "help": "墙段短于此值不布窗"},
        {"k": "win_min_run", "label": "最小窗间净距", "type": "num", "step": 0.1},
    ]},
    {"group": "⑥ 屋顶与女儿墙", "fields": [
        {"k": "roof_t", "label": "屋面板厚", "type": "num", "step": 0.05},
        {"k": "parapet_h", "label": "女儿墙高", "type": "num", "step": 0.1},
        {"k": "parapet_t", "label": "女儿墙厚", "type": "num", "step": 0.05},
    ]},
    {"group": "⑦ 楼梯", "fields": [
        {"k": "stair_landing", "label": "休息平台厚", "type": "num", "step": 0.05},
    ]},
]

# style 子键（spec.style，与上面并列但独立渲染成颜色选择器）
STYLE_KEYS = [
    {"k": "facade", "label": "外墙 facade"},
    {"k": "inner", "label": "内墙 inner"},
    {"k": "roof", "label": "屋顶 roof"},
    {"k": "parapet", "label": "女儿墙 parapet"},
    {"k": "glass", "label": "玻璃 glass"},
    {"k": "door", "label": "门 door"},
]

# 流程阶段链。字段含义：
#   id       前端与 API 用的阶段名
#   scope    single=按当前楼跑 | all=全仓 | source=图纸源目录
#   writes   True=会改盘上数据（前端弹确认）；False=只读/只出报告
#   runnable 能否由控制台一键跑（False 必须在命令行跑，why_manual 说明原因）
#   produces 产物相对路径模板（算「完成/过期」用）
#   upstream 该阶段产物的**上游真值**：取值必须在下面的 `UPSTREAM_KEYS` 里登记。
#            过期判据 = 产物 mtime 早于它的上游 mtime。**不能一刀切用 floors** ——
#            spec.json 和 floor0.json 是 recognize 的同批产物（互为兄弟）。
#            ★ 这个键**只有在各消费侧的「键 → mtime」取值表里也有一项才有效**：
#            旧写法 `up_m.get(upstream)` 对未登记的键静默返回 None ⇒
#            `bool(up and m < up)` 恒 False ⇒ stale 恒 False ⇒ 静默假绿。
#            现在两侧都收紧了：这里用 `self_check()` 在启动时**点名**未登记的阶段；
#            两个消费侧（`control.py:building_status`、`api/services/console.py:status`）
#            取值一律走 `up_m[key]`，键不在就报错，不再有静默 None 这条路。
#            2026-09-14：cadrender 的 upstream 由 'dxf' 订正为 'floors' —— 实测
#            `_dxf_cad_render.py:400-401` 读 `floors/floor{F}.json` 的 outline 当
#            包围盒过滤实体 ⇒ 它对 floors 是真依赖，旧值会让「楼层改了图没重出」漏判。
#            反过来 dxf_plan 并不因为是「源图纸」就不依赖 floors，注释里的旧理由不成立。
#   inplace  True = 就地改写楼层、没有独立产物，完成与否**无法从产物推断**。
#            （thin / doorpunch 改的就是 floors/floor0.json，那个文件 recognize 早就写了，
#             拿它的存在当「这一步做过了」是假信号。）
#
# ★ 顺序铁律（2026-09-14 重排）：**结构先识别 → 与 CAD 图纸比对（第一位）→ 结构自洽
#   → 房间 → 交付**。旧顺序把「识别 vs 源图纸」（audit）放在 no=9、排在建模与 QA 之后，
#   且 produces=[] ⇒ 整条管线**没有任何一环会在建模前喊出「这一层少了一半墙」**。
#   现把门禁提到 no=2（recognize 之后、任何房间/建模动作之前），且产出
#   `{name}-audit.json` 让控制台看得见完成/过期。
#   三个「看图纸」视窗（cadrender/recogrender/compare）随门禁，供人眼核实 ——
#   它们看的是**第一轮识别**，所以排在 thin/doorpunch（交付前修边）之前。
#   `rooms` 标 runnable=False：★ 真正的理由是**覆盖即不可回滚**（rooms.json 是交付件、
#   不在 git，脚本就地覆盖、没有 .orig 备份也没有自动回滚）—— 见 why_manual。
#   ⚠ 2026-09-26 实测订正：这里原先写「全库 49 栋混着两套顺序（room_route='regen' 的楼
#   在同一次运行内从 DXF 墙推房）」。逐栋量过 96 份 profile.json 后并不是这样：
#   room_route 取值**只有 'auto'（95 栋）**，c006pub **缺这个键**，
#   'regen' 与 'single' **0 栋在用**；派发侧（extract_rooms_generic.py 的 room_route
#   分支）也只比较 'auto' 与 'single' 两个值。⇒ `regen` 是**主线那个分支自报的名字**
#   （RR.ROUTE_REGEN，只在 auto 分支内部当候选标签用），**不是一个存在 profile.json 里的
#   取值** —— 别拿它去 grep data/（那里一个也找不到）。原句里的「49 栋」也是**当时的库容**
#   （现 96，本仓 `audit_walls.py:23` 记过同一件事：分母是当时的库容）。
#
# upstream 键的**登记表**（单一事实源）。各消费侧维护的是「键 → mtime」的取值表，
# 键集必须与这里一致：取值用 `up_m[key]`，键不在就**报错**。
# 不许写回 `up_m.get(key)` —— 它对未登记的键静默返回 None，而 None 会让过期判据
# 恒判「不过期」，屏幕上与「真的没过期」完全同形（铁律 19：恒不触发的判据）。
UPSTREAM_KEYS = ("dxf", "floors", "source", None)

# ★ 下面这份是**回落**，不是事实源。事实源在 `config/pipeline.json`（同目录的上层
#   `config/`）。搬出去的理由：流程表是「用户要能改」的东西，而改 .py 会连带触发
#   识别增量指纹失效（指纹含 backend/recognizer/*.py）。配置在数据侧，改它零代价。
PIPELINE_FALLBACK = [
    {"id": "dwg2dxf", "no": 0, "label": "DWG → DXF", "scope": "source",
     "script": "convert_dwg_to_dxf.py", "writes": True, "slow": True, "runnable": False,
     "produces": [], "upstream": None, "why_manual":
         "需要 ODA File Converter 桌面程序 + DWG 源目录，属一次性摄入。"
         "命令行：python -u convert_dwg_to_dxf.py --filter <名>（audit=1 是铁律，不开会漏实体）",
     "desc": "二进制 DWG 转成 ezdxf 可读的 DXF，是整个管线的地基"},
    {"id": "recognize", "no": 1, "label": "识别出图", "scope": "single",
     "script": "backend/web/run_step.py", "args": ["{name}", "recognize"],
     "writes": True, "slow": True, "runnable": True,
     "produces": ["floors/floor0.json", "spec.json"], "upstream": "dxf",
     "desc": "读 DXF → 分类构件 → 按 22 步逐层组装 → 写 floors/floor*.json + spec.json"},
    {"id": "gate", "no": 2, "label": "★ 结构 × 源图纸门禁", "scope": "single",
     "script": "audit_gate.py", "args": ["{name}"],
     "writes": True, "slow": True, "runnable": True,
     "produces": ["{name}-audit.json"], "upstream": "floors",
     "desc": "把「识别 vs CAD 图纸」提到第一位：逐层量漏墙率（M）/糊块（W）/错位（F）"
             "+ 量具自检（G，源墙量不到就报 GATE_BLIND 不许判绿）+ 层身份辨识"
             "（D段=地下室 / 内容集中=屋面层嫌疑）。退出码非 0 = 有 ERROR 层。"
             "只读 floors，不改一个字节"},
    {"id": "qa", "no": 3, "label": "结构体检 I1–I10", "scope": "single",
     "script": "qa_structural.py", "args": ["{name}"],
     "writes": False, "slow": False, "runnable": True,
     "produces": [], "upstream": None,
     "desc": "不变量门禁，只读存档 JSON 不写任何数据。任何改动后必跑。"
             "ERROR 数量是回归的第一指标。★ 它**只查内部自洽、完全不碰源图纸**，"
             "所以不能替代 gate（自洽的错几何照样自洽）"},
    {"id": "cadrender", "no": 4, "label": "出忠实源图纸", "scope": "single",
     "script": "_dxf_cad_render.py", "args": ["{name}"],
     "writes": True, "slow": True, "runnable": True,
     "produces": ["dxf_plan/index.html"], "upstream": "floors",
     "desc": "白底黑线、忠实还原 CAD 线稿（真值参照）"},
    {"id": "recogrender", "no": 5, "label": "出识别叠加图", "scope": "single",
     "script": "_dxf_png_batch.py", "args": ["{name}"],
     "writes": True, "slow": True, "runnable": True,
     "produces": ["dxf_plan_recog/floor0.png"], "upstream": "floors",
     "desc": "灰细线源墙垫底 + 彩色识别结果（灰实=墙/红=门/绿=楼梯井/蓝=柱）"},
    {"id": "compare", "no": 6, "label": "A|B 对比页", "scope": "single",
     "script": "_dxf_compare_render.py", "args": ["{name}"],
     "writes": True, "slow": False, "runnable": True,
     "produces": ["compare.html"], "upstream": "floors",
     "desc": "源图纸(真值) vs 第一轮识别，逐层并排 —— 找识别漏/错的主要视窗"},
    {"id": "thin", "no": 7, "label": "重建内墙（单栋强制）", "scope": "single",
     "script": "_wall_thin_force.py", "args": ["{name}"],
     "writes": True, "slow": True, "runnable": True, "danger": "high",
     "produces": ["floors/floor0.json"], "upstream": "dxf", "inplace": True,
     "why_manual":
         "批量版 _wall_thin_batch.py 忽略 argv、会遍历全部 48 栋 —— 绝不能在控制台一键跑。"
         "此处接的是单栋强制版，逐层 .orig 备份 + 数值验收 + 不通过自动回滚该层",
     "desc": "⭐ 交付链的真正一环：recognize 产的内墙是粗环 blob（覆盖率>20%）不是交付物，"
             "真内墙由这一步从 DXF 双线重配对；门洞也必须在这里再挖一次"},
    {"id": "doorpunch", "no": 8, "label": "门洞外科打穿（写盘）", "scope": "single",
     # ★ args 必须带 `--apply`：脚本 `_door_punch_apply.py` **默认是只报不写的干跑**
     #   （源码第 18 行「`--apply` 才写盘」、第 21 行用法、第 33-39 行 argv 解析）。
     #   历史上这里只有 ["{name}"] ⇒ 按钮按下去只干跑，而本阶段标着 writes=True、
     #   danger=high，前端弹的是「会改写本楼楼层数据」——按钮在说谎。
     "script": "_door_punch_apply.py", "args": ["{name}", "--apply"],
     "writes": True, "slow": False, "runnable": True, "danger": "high",
     "produces": ["floors/floor0.json"], "upstream": "dxf", "inplace": True,
     "why_manual":
         "三个前提（都不是按钮能替你满足的）："
         "①需先有 recognize 的临时产物 `_tmp_<名>_door`（同坐标系），缺了脚本会打印"
         "「缺少临时产物」并以退出码 1 结束；"
         "②`--apply` 才写盘 —— 控制台 args 里带着它，去掉就是只报不写的干跑；"
         "③写前逐层备份到 <楼>/.orig/before_doorpunch_<ts>/，任一数值门槛不过的层"
         "整层跳过（不写），不是回滚已写的层",
     "desc": "备份 → 挖门洞 → 数值复验 → 失败自动回滚。门=gap 不是 hole，盒深必须 > 墙厚。"
             "★ 按下去就是真写（args 带 --apply），不是干跑"},
    {"id": "rooms", "no": 9, "label": "房间提取 ⚠ 覆盖交付件", "scope": "single",
     "script": "backend/extract/extract_rooms_generic.py", "args": ["{name}"],
     "writes": True, "slow": True, "runnable": False, "danger": "high",
     "produces": ["rooms.json"], "upstream": "dxf", "why_manual":
         "★ 覆盖即不可回滚：rooms.json 是交付件，**不在 git**，脚本就地覆盖、"
         "没有 .orig 备份也没有自动回滚 ⇒ 跑之前先把现有的 rooms.json 另存一份。"
         "★ 2026-09-26 实测订正（原文下面两句与盘上不符，别照原文理解）："
         "① 房间口径其实**是统一的**：96 栋 profile.json 里 room_route 只有 'auto' 一个取值"
         "（95 栋），c006pub 缺这个键，'regen'/'single' **0 栋在用**；"
         "② c006 的 rooms.json 现在**不是**「35 条整翼汇总行」——实测 **214 条**、每条都带"
         "boundary 与房号、跨 floor 0–10（377315 字节，mtime 2026-09-17 09:22）。"
         "它**确实还有问题**，但属另一类：检查引擎对 c006 报 A2「逐层房间数 vs 图纸房间数」"
         "与 A3「交付楼层 rooms 快照与台账一致」——那是**两边数对不上**，不是文件形状坏。"
         "⇒ 一键推房照样不许（结论不变），但请按上面那条**覆盖即不可回滚**理解，"
         "不要按「全库口径没统一」。命令行：python -u backend/extract/"
         "extract_rooms_generic.py <名>（先加 --dry 看数）",
     "desc": "从 DXF 标注+封闭区推房间 → rooms.json。**排在 thin/doorpunch 之后**，"
             "因为它要读的是已修边的交付墙。"
             "⚠ 本步**就地覆盖** data/buildings/<楼>/rooms.json 且不可回滚"
             "（该目录不在 git）：c006 那份现况见 why_manual 的订正 —— "
             "★ 原文写「35 条整翼汇总行、几何停在平移前」，2026-09-26 实测是 "
             "214 条带 boundary 与房号的正常台账；c006 真有问题，但是 A2/A3 的**数对不上**，"
             "不是形状坏。禁令不变，理由以 why_manual 为准。"
             "先另存一份再跑"},
    {"id": "glb", "no": 10, "label": "生成 GLB", "scope": "single",
     "script": "backend/web/run_step.py", "args": ["{name}", "glb"],
     "writes": True, "slow": False, "runnable": True,
     "produces": ["{name}-building.glb"], "upstream": "floors",
     "desc": "只用现有 floors + spec 重建 GLB（不重跑识别，快）"},
    {"id": "audit", "no": 11, "label": "覆盖度审计", "scope": "single",
     "script": "_dxf_audit.py", "args": ["{name}"],
     "writes": True, "slow": True, "runnable": True,
     "produces": [], "upstream": None,
     "desc": "带洞覆盖 + 门 mask 的墙漏检审计，输出可疑层排名。与 gate 判据同源"
             "（都走 qa_defect_census），是明细视图；gate 是进出口门禁"},
    {"id": "sweep", "no": 12, "label": "全仓缺陷扫描", "scope": "all",
     "script": "_sweep_modeling.py", "args": [],
     "writes": False, "slow": True, "runnable": True,
     "produces": [], "upstream": None,
     "desc": "只读回归扫描，跑全部楼的几何缺陷统计"},
    {"id": "index", "no": 13, "label": "刷新索引", "scope": "all",
     "script": "build_index.py", "args": [],
     "writes": True, "slow": False, "runnable": True,
     "produces": ["buildings/index.json"], "upstream": "floors",
     "desc": "生成 data/buildings/index.json，供网页选择器消费"},
]

# ── 流程表的事实源：config/pipeline.json ─────────────────────────────
_CONFIG_PIPELINE = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "pipeline.json"))


def _stage_from_render(r):
    """把 `成图` 段翻成一条与其余阶段同构的 stage。

    ★ 为什么 `script` 写 `run_step.py` 而不是配置里那个 `blender/render_views.py`：
      控制台点「跑这一阶段」时是**按 stage.script + stage.args** 起子进程的，
      而 render 的真实调用形态是「Blender 逐视图各起一次、每次带不同 `--view`」——
      那是一个循环，不是一个 argv。循环写在 `run_step.step_render()` 里，
      它读的就是配置里的 `views`/`blender`/`res`。
      ⇒ 这里只负责说「这一步怎么被叫起来」；**机位与视图清单仍然只由配置决定**
        （改了配置里的 views，加视图/改机位都不用碰代码）。
    """
    views = r.get("views") or []
    return {
        "id": r.get("id", "render"), "no": r.get("no", 14),
        "label": r.get("label", "三维成图"),
        "scope": r.get("scope", "single"),
        "script": "backend/web/run_step.py", "args": ["{name}", r.get("id", "render")],
        "writes": True, "slow": False, "runnable": True,
        "produces": ["%s/%s.png" % ((r.get("out_dir") or "renders").rpartition("/")[2],
                                    v["id"]) for v in views],
        "upstream": "floors",
        "desc": "按配置里的视图清单出图（%d 档）；机位/分辨率/Blender 路径全在 "
                "config/pipeline.json 的『成图』段" % len(views),
    }


def _load_pipeline():
    """读 `config/pipeline.json` → 与旧 `PIPELINE` 同构的阶段列表。

    读不到 / 读坏了 ⇒ 返回 None，由调用方回落到代码里的 `PIPELINE_FALLBACK`。
    ⇒ 引入本函数**不改变现有行为**（配置是照旧表逐条生成的），只是把事实源换到盘上。

    ★ `成图` 段在配置里是**独立一块**（它带 glb/out_dir/blender/res/views 这些
      只属于它的键），这里把它翻成一条普通 stage 追加到末尾 —— 于是它自动获得
      「完成/过期」判定与控制台一键跑的能力，而别的阶段一个字节都不用改。
    """
    try:
        with open(_CONFIG_PIPELINE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:                                    # noqa: BLE001
        return None
    stages = d.get("stages")
    if not isinstance(stages, list) or not stages:
        return None
    out = list(stages)
    r = d.get("成图")
    if isinstance(r, dict) and r.get("id"):
        out.append(_stage_from_render(r))
    return out


PIPELINE = _load_pipeline() or PIPELINE_FALLBACK

_BY_ID = {s["id"]: s for s in PIPELINE}


def get_stage(step):
    """按 id 取阶段定义；不存在返回 None。"""
    return _BY_ID.get(step)


def runnable_ids():
    return [s["id"] for s in PIPELINE if s["runnable"]]


# ---------------------------------------------------------------- 规格默认值
_SPEC_DEFAULT_CACHE = None
_BRANCH_CACHE = None


def spec_defaults():
    """从 build_standard_glb 读取**权威**兜底默认值（不复制一份，避免漂移）。

    load_spec() 在 DATA/spec.json 不存在时返回内置兜底字典。这里把 DATA 临时指向
    一个不存在的目录来「问」它要默认值 —— 只调用一次并缓存，不在请求期改全局状态
    （control.py 是多线程 server，请求期改模块全局会竞态）。
    """
    global _SPEC_DEFAULT_CACHE
    if _SPEC_DEFAULT_CACHE is not None:
        return _SPEC_DEFAULT_CACHE
    import sys
    MODELING = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modeling"))
    if MODELING not in sys.path:
        sys.path.insert(0, MODELING)
    import build_standard_glb as bsg
    old = bsg.DATA
    try:
        bsg.DATA = os.path.join(os.path.dirname(old) or ".", "_meta_no_such_dir_")
        _SPEC_DEFAULT_CACHE = bsg.load_spec()
    finally:
        bsg.DATA = old
    return _SPEC_DEFAULT_CACHE


def branch_registry():
    """读 `config/branches.json`（开关登记表）→ {键: 记录}；读不到返回 None。

    ★ 返回 None 与返回 {} 必须分开：前者是「**判据没跑**」，后者是「登记表是空的」。
      两者在屏幕上长得一样，但结论相反（铁律 16：坏掉的量具和空对象同形）。
    """
    global _BRANCH_CACHE
    if _BRANCH_CACHE is not None:
        return _BRANCH_CACHE
    p = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "..", "..", "config", "branches.json"))
    try:
        with open(p, encoding="utf-8") as f:
            rows = json.load(f).get("开关")
        if not isinstance(rows, list):
            return None
        _BRANCH_CACHE = {r["key"]: r for r in rows
                         if isinstance(r, dict) and "key" in r}
    except (OSError, ValueError):
        return None
    return _BRANCH_CACHE


def _ctor_kwargs(path, func_name, ctor="BuildingProfile"):
    """该函数体里 `ctor(...)` 那次调用的 **keyword 名集合** = 真被传进去的键。

    取函数体里**全部**匹配的调用并求并（一个函数里构造两次时两次都算投递）。
    函数不存在 / 解析失败 / 一次都没构造 ⇒ **None**（不是空集：铁律 16 ——
    「解析失败」与「一个键都没传」在屏幕上必须不是同一行字）。

    ★ 为什么不用 `_function_literals` 数这个名字出现过没有：那是**文本事实**
      （铁律 23），答的是「这个名字被提到过」。在 `load_profile` 里写一句
      `log("某个键")`，字面量口径就会把它算成「已投递」。这一档要答的是
      「这个值真的被送进 BuildingProfile 了吗」，所以量的是**实参名**。
      提出来做成模块级函数，是为了让刑具能直接对着它做对照
      （`_scratch/_falsify_dead_knob_check.py` 的 L8），而不是另抄一份更弱的。
    """
    import ast
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    fn = None
    for node in ast.walk(tree):
        if getattr(node, "name", None) == func_name and isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = node
            break
    if fn is None:
        return None
    got, n_call = set(), 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        nm = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
        if nm != ctor:
            continue
        n_call += 1
        got |= {kw.arg for kw in node.keywords if kw.arg}
    return got if n_call else None


def _profile_dict_get_keys(path, only_func=None):
    """这个文件从 **`profile.json` 那份原始字典** 里读到哪些键 → `(键集, 装它的名字集)`；读不到 None。

    三把尺子答的是**三个不同的问题**，别互相替代：
      · `_ctor_kwargs`        ：这个值被送进 `BuildingProfile(...)` 了吗（**构造实参名**）；
      · `_function_literals`  ：这个名字在那个函数体里**被提到过**吗（**文本事实**，铁律 23）；
      · 本函数                ：这个文件**从原始字典里读**了哪些键（`X.get("键")` / `X["键"]`）。

    为什么需要第三把：`su_spec_floors_fleet.py` / `build_index.py` 读的是
    `json.load(open("profile.json"))` 那份字典本身，中间**没有** `BuildingProfile(...)`
    可供解析；而按**文件级字面量**扫会造出假投递 —— 同一个文件里
    `rooms[k].get("number")` / `floor.get("atrium_holes")` 全是**别的字典**的读取，
    而 `rooms` 恰好也是一个合法的档案键（实测 `su_spec_floors_fleet.py` 的文件级键集
    与「只在这个文件里、且装了档案字典的那个名字」上的键集差着一大截，差值全是别的字典）。
    ⇒ 所以这里按「**那个名字装的是不是 profile.json 里那份字典**」收键：先解一层不动点
      （`_pj = join(base, "profile.json")` → `_cfg = json.load(open(_pj))`，最多 6 轮），
      再收这些名字上的字符串下标与 `.get("键")`。形参与模块级同名时**按同名收** ——
      对「键集」这个用途是安全的，且错的方向是**多收**（多收的项靠调用方遍历 `exposed` 兜住）。

    `only_func` 给定时只收**那个函数体内**的读取（名字集合仍按全文件解）。
    返回 `None` = 量具坏了（读不了 / 解析不了 / 那个函数不存在），不是空集（铁律 16）。
    """
    import ast
    from pathlib import Path
    try:
        text = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None
    lines = text.splitlines()

    def _span(node):
        return "\n".join(lines[node.lineno - 1:(node.end_lineno or node.lineno)])

    binds = []                       # (名字, 取值表达式)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                tgts = t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]
                binds += [(e.id, node.value) for e in tgts if isinstance(e, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            binds.append((node.target.id, node.value))
        elif isinstance(node, ast.With):
            binds += [(it.optional_vars.id, it.context_expr) for it in node.items
                      if isinstance(it.optional_vars, ast.Name)]
    names = set()
    for _ in range(6):
        grew = False
        for name, val in binds:
            if name in names:
                continue
            # 直接规则：取值里就是 profile.json 路径，或取值里提到一个**已认定**的名字
            if "profile.json" in _span(val) or any(
                    isinstance(n, ast.Name) and n.id in names for n in ast.walk(val)):
                names.add(name)
                grew = True
        if not grew:
            break
    scope = tree
    if only_func:
        scope = next((n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == only_func), None)
        if scope is None:
            return None
    keys = set()
    for node in ast.walk(scope):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                and node.func.value.id in names and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            keys.add(node.args[0].value)
        elif (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id in names and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            keys.add(node.slice.value)
    return keys, names


def _delivery_channels():
    """档案键**全部**投递通道 → [(通道名, 该通道从档案里读到的键集)]；读不到返回 None。

    ★ 通道表是**列出来的、有名字的**：新增一条投递通道要**显式加一行**，
      而不是让判据去猜「还有没有别的路」。★ 每一行都带着**它的源文件**：

        ① 批量识别     `run_building.py:load_profile`      ← `_ctor_kwargs`（构造实参名）
        ② 控制台识别   `run_step.py:profile_from_cfg`       ← `_ctor_kwargs`
        ③ GLB 导出档位 `run_step.py:glb_opts_from_profile`  ← `_profile_dict_get_keys`
        ④ SU 分层建模  `backend/modeling/su_spec_floors_fleet.py` ← `_profile_dict_get_keys`
        ⑤ 楼层清单     `build_index.py`                     ← `_profile_dict_get_keys`

    ★ 上面这些序号**只在本段里有定义**，是**位置**引用 ⇒ 往表中间插一行，它们就集体指错，
      而**指错不报错**（铁律 31）。所以：**表外**一律用通道名或源文件/函数名回指，
      不许写「通道③」这种话 —— 本节自己下面也照这条办。

    ★ 少了③④⑤任何一条，判据就会把那些键**误报成死旋钮** ——
      本仓 `_scratch/_param_gap.py` 的 docstring 里记着它第一版正是栽在这里
      （「某个函数不读它」与「全仓没人读它」是两件事）。
      **这句话 2026-09-26 又栽了一次，形态不同**：当时③只认「`run_step` 那条 GLB 路」，
      而 ④（`G.INCLUDE_SYNTHETIC_WINDOWS = _cfg.get("glb_windows", True)`，**造 SU / 交付
      .skp** 的那条路）与 ⑤（`build_index.exported_floors` 把 `skip_floors` 写进
      `data/buildings/index.json` 的 `floors` 列 —— 这就是 c103 `floors=5 / floors_total=6`
      的来路）都从档案里读了同样的键，却不在表上。告警于是印出一句**假话**：
      「档案键 %r **只由**控制台的 GLB 导出读」。
      ⇒ 一条「只有 X 读它」的判据，X 是**手维护的名单**时必须自己喊出来它不全
        （`backend/checks/builtin.py` 的 `check_a8` 记过这个失败模式：
          手维护的名单必然不全 ⇒ 必然假红 ⇒ 红灯被学会忽略）。

    ★★ **③④⑤ 为什么必须用「原始字典读取」这把尺子**（而不是字面量）：见
      `_profile_dict_get_keys` 的 docstring。一句话：这三个文件的读法是
      `json.load(open("profile.json"))` 之后 `d.get("键")`，中间**没有** `BuildingProfile(...)`
      可供解析；而按**文件级字面量**扫会把 `rooms[k].get("number")` 这类**别的字典**的读取
      算成档案键（`rooms` 恰好也是合法档案键）。实测 ③ 换成这把尺子后键集不变
      （`{glb_windows, skip_floors}`，与旧的字面量口径在这一处**逐位相同**），
      差的是**多出来的那些不再混进来**（旧口径多带 `profile.json` / `utf-8` / `windows`
      与整段文档串 —— 它们今天够不着任何桶，只因为消费侧遍历 `exposed`；那是**靠调用方兜住的耦合**）。

    ★ ③④⑤ **只在各自那条路上** —— 实测，不是从文档读的（2026-09-26，逐条读源码 + 数 96 栋真楼）：
        · `run_building.py`（**批量出图**）实测读到 **50 个**档案键，其中**不含**
          `glb_windows` / `skip_floors` ⇒ 批量路上 `SKIP_FLOORS` 从不赋值 ⇒ 恒为空集，
          没有任何一栋会被跳过；`INCLUDE_SYNTHETIC_WINDOWS` 只按 argv 的 `--windows` 决定。
        · 而 `--windows` 是个**空操作**：`backend/modeling/build_standard_glb.py` 的模块级常量
          `INCLUDE_SYNTHETIC_WINDOWS = True` 本来就是 `True`，`--windows` 只是把它再置一次
          ⇒ 后果是批量路上合成窗**关不掉**。
          （★ 本节原先写「第 145 行那句注释是过期记录」—— 那是**两重过期**：行号已漂，
          而那句注释本身也已经被人改掉了。改成**符号名**引用，理由见铁律 31。）
        · 于是 `glb_windows` 96/96 栋写着 `True` = 模块默认 ⇒ 今天零损害，
          但它在批量路上**两个方向都不生效**；`skip_floors` 则有真存量：c103 = `[5]`
          （它的 floor5.json 恰好 0 个房间）。
        · `su_spec_floors_fleet.py` 里那句 `G.INCLUDE_SYNTHETIC_WINDOWS = ...` 读 `glb_windows`，
          同时把 `G.SKIP_FLOORS` **强制清空**（所以 SU 那条路上 `skip_floors` 不生效 ——
          这是**另一条**「写了不生效」，与批量路那条不是同一件事）。
          ★ 该文件里那句注释写着「c006 已按用户要求把 glb_windows 设成 false」，
          **实测已过期**：c006 与 c006pub 的 profile.json 里都是 `True`（2026-09-26 量）。
      ⇒ 所以这一档**计进告警**，且措辞必须**点明**读它的到底是哪几条通道
        （由本表**推出来**，不写死条数、不写死名字 —— 写死的话，下次加通道又是同一句假话）。

    ★ 读不到源码返回 **None**（不是空表）——「量具坏了」与「没人投递」
      在屏幕上必须不是同一行字（铁律 16）。

    ★★ **①②量的是「构造函数的实参名」，不是「函数体里出现过这个名字」。** 别改回去：
      `_function_literals` 交回的是函数体里**所有**字符串字面量 —— 那是**文本事实**（铁律 23），
      它答的是「这个名字被提到过」。在 `load_profile` 里写一句 `log("某个键")`
      就会让那个键**凭空变成「已投递」**。`BuildingProfile(...)` 的 keyword 才是投递动作本身
      —— 它就是「值被送进去」那一行代码。（旧版用 `字面量 ∩ 字段名`，屏幕上读起来完全正常，
      只是把「提及」当成了「投递」。）

    ★★ **已知的洞，写在这里而不是让人以为它没有**：本表**是手维护的**，所以
      「新增一条投递通道而没人回来加一行」这个漏洞**结构上修不掉**，只能缩小它。
      「按全仓扫描自动发现读取者」这个替代方案**量过了，不能用**（2026-09-26）：
      扫 **140 个** `.py`（1.5 s），**12 个**文件从档案里读了暴露键，其中 **8 个不是通道**
      —— `glb_gate.py`（校验器，只报告）、`backend/checks/floor_levels.py`、
      `backend/checks/_area_audit.py`、`backend/web/console_meta.py`（本文件自己）、
      `backend/web/control.py`、`backend/api/services/{artifacts,checks,console}.py`
      —— 且多数只读 `dxf` / `title` / `out_dir`（**输入定位符**，不是旋钮）
      ⇒ 拿它当告警会造出一条**永久的假红河流**，正是 `backend/checks/builtin.py` 的
        `check_a8` 记下的那个失败模式。
      ⇒ 处置：**不把它接进 payload**（接进去等于教会人忽略这条判据），改成
        「本表 ＋ 每行带源文件 ＋ 这条**带时刻**的普查记录」。说清它是什么：
        **一次 2026-09-26 的测量**，不是一条性质 —— 重跑：
        `python _scratch/_probe_profile_readers.py`（它自己会印分母与命中集）。
    """
    import dataclasses
    from pathlib import Path
    root = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
    rs = root / "backend" / "web" / "run_step.py"
    try:
        from recognizer.profile import BuildingProfile
    except Exception:  # noqa: BLE001 —— 拿不到量具就不给结论
        return None
    try:
        fields = {f.name for f in dataclasses.fields(BuildingProfile)}
        batch = _ctor_kwargs(root / "run_building.py", "load_profile")
        cons = _ctor_kwargs(rs, "profile_from_cfg")
        raw = [_profile_dict_get_keys(rs, only_func="glb_opts_from_profile"),
               _profile_dict_get_keys(root / "backend" / "modeling"
                                      / "su_spec_floors_fleet.py"),
               _profile_dict_get_keys(root / "build_index.py")]
    except Exception:  # noqa: BLE001
        return None
    if batch is None or cons is None or any(r is None for r in raw):
        return None
    glb, su, bi = (r[0] for r in raw)
    # ★ ①② 与字段名求交：`fields` 之外的名字不可能是档案键（真发生的话构造当场就 TypeError 了）。
    #   ③④⑤ 是**原始字典读取**，**不求交**：`glb_windows` / `skip_floors` 本来就不是
    #   `BuildingProfile` 字段（这正是必须有这几行的原因）。混进来的非档案键靠消费侧
    #   **遍历 `exposed`** 兜住 —— 实测 ③ 的 49 个键里 9 个不在 `exposed`，④⑤ 的多余项 0 个。
    return [("批量识别", batch & fields),
            ("控制台识别", cons & fields),
            ("GLB 导出档位", glb),
            ("SU 分层建模", su),
            ("楼层清单", bi)]


def _batch_raw_reads():
    """**批量出图**（`run_building.py`）从档案**原始字典**里读到的键集；读不到返回 None。

    ★ 与「构造实参名那把尺子」（`_ctor_kwargs(run_building.py, "load_profile") & fields`）**量的不是同一件事**，
      两个都得留着，因为它们各自答不了对方那个问题：

        · 构造实参那把尺子答「构造 `BuildingProfile` 时哪个**字段**被投递了」—— 它跑在**构造实参**上，
          **结构上不可能**含非字段键（真含的话构造当场 `TypeError`）；
        · 本函数答「这条路上哪个**非字段**的档案键被读了」。

      ⇒ 追问「`glb_windows` / `skip_floors` 在批量路上生效吗」时，**只有本函数能回答**。
        拿构造实参那把尺子去答会得到「不在里面」—— 那不是测量，是**同义反复**：
        它们本来就不是 `BuildingProfile` 字段（这正是它们需要「原始字典读取」
        那几条通道的原因 —— 别按序号或条数引用那些通道：加一行就指错，见铁律 31）。
        2026-09-26 实测：本函数 **50** 个键、① **49** 个键，两个目标键**两个集合里都没有**
        ⇒ 「批量出图不读它」是**两把独立的尺子都这么说**。
        （两把尺子在**暴露键**上的分歧：`① − 本函数 = {name, style}`；反向 0 个。）

    ★ 已知的**过收**方向，写在这里免得读的人以为它是精确的：不动点解会顺着
      `cfg = json.load(open("profile.json"))` 之后**派生**出来的名字继续收
      ⇒ 某个**子字典**上的 `.get("键")` 也会被算进来。方向是**多收**，
      即可能把「其实没生效」说成「能生效」。⇒ 所以调用处**必须把这个数印出来**，
      让读的人看得见尺子量了多少、是不是活的（铁律 60：分母必须进输出）。

    ★ 读不到源码 / 解析不了 ⇒ **None**（不是空集）—— 「量具坏了」与「它一个键都不读」
      在屏幕上必须不是同一行字（铁律 16）；调用处的告警据此印「未量」，不许退化成「不读」。
    """
    from pathlib import Path
    root = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
    r = _profile_dict_get_keys(root / "run_building.py")
    return None if r is None else r[0]


def _dropped_blast_radius(keys):
    """这些键里，有几个**真楼的 profile.json 里写着**？（＝被静默忽略的存量）。

    只报键名是不够的：`改了这个键没用` 与 `33 栋写着这个键而它被忽略` 是两件事，
    后者才是用户会踩的那一脚。读不到就返回 None（不返回 0 —— 铁律 16）。
    """
    root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "..", "data", "buildings"))
    out = {}
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return None
    n = 0
    for d in names:
        p = os.path.join(root, d, "profile.json")
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                j = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(j, dict):
            continue
        n += 1
        for k in keys:
            if k in j:
                out[k] = out.get(k, 0) + 1
    out["__栋数__"] = n
    return out


_SELF_CHECK_CACHE = None
# ★ 进程内**累计**重算次数（不随 reset 归零）：用来把「它到底重算了吗」
#   变成可以**直接读**的数，而不是靠比时间戳去猜（「量于」只有秒级分辨率，猜不出来）。
_SELF_CHECK_N = 0


def self_check_report():
    """启动自检的**结构化**结果。`self_check()` 只是它的一个投影（见那里）。

    ★ 为什么要结构化：这条判据以前**只往 stderr 印**，它的结论到不了任何页面 ——
      于是「我改的这个键到底是活的还是死的」用户得去看服务器日志。
      用户第 5 条要的是「写在后台、我后面能修改」，那就必须能**在页面上看见**
      哪些键改了不生效。所以判据的结论要和判据本身一起进 `/api/meta`。
    ★ 只此一份实现：下面 `self_check()` 是 `["warnings"]` 的投影，
      `/api/meta` 用的是同一份结果 —— 不许在别处再数一遍
      （本仓铁律：一个判断多份实现 ⇒ 同一屏两句话）。
    """
    import sys
    # ★ 本函数**只往 stderr 印**（下面每一行分母都是 stderr），而 Windows 控制台/
    #   Git Bash 下 stderr 默认按 GBK 编码 ⇒ 那几行中文分母在屏幕上变成乱码
    #   （实测 2026-09-26：`[元数据自检]` 印成 `[Ԫ�����Լ�]`）。
    #   这不是「显示不好看」：**这一档的全部价值就是那行分母**
    #   （「量了 50 个、0 个死」与「判据没跑」必须不是同一行字，见 docstring）——
    #   分母糊掉，用户就分不出「没量」和「干净」，正好把这个函数防的那件事造了出来。
    #   只在本函数内改，不在模块级改：这是 web 后端，别动进程全局的日志编码。
    for _st in (sys.stderr, sys.stdout):
        try:
            _st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass   # 被重定向成非 TextIOWrapper（pytest/自定义流）时保持原样
    warn = []
    # ★ 结构化报告：与本函数的告警**同一趟算出来**（不是一个判断两份实现）。
    #   页面要的就是它 —— 用户改后台时得看得见「这个键改了到底生不生效」。
    #   每一栏都带「状态」：**「没量到」绝不能长得像「量到且没有」**（铁律 16）——
    #   这一列是用户看的第一列，所以它必须能自己说清是量具的事还是真的没值。
    rep = {"版本": 1,
           "规格键": {"状态": "未量"},
           "档案键": {"状态": "未量"},
           "投递通道": {"状态": "未量"},
           "阶段": {"缺args": [], "upstream未登记": []}}
    try:
        real = set(spec_defaults()) | {"style", "roofType"}
    except Exception as e:  # noqa: BLE001
        warn.append("无法读取建模层规格默认值: %s: %s" % (type(e).__name__, e))
        rep["规格键"] = {"状态": "读失败", "错误": "%s: %s" % (type(e).__name__, e),
                       "含义": "这一栏**没量到**，不是「规格键都合规」"}
        real = None
    if real is not None:
        spec_bad = []
        for g in SPEC_GROUPS:
            for f in g["fields"]:
                if f["k"] not in real:
                    spec_bad.append(f["k"])
                    warn.append("规格键 %r 不在 build_standard_glb 消费列表里" % f["k"])
        rep["规格键"] = {"状态": "已读", "消费列表键数": len(real),
                       "不在消费列表": spec_bad}

    # ── 档案键：**页面上能改**，但载入后没人读 ⇒ 改了不生效、且不报错（死旋钮）。
    #    这是用户第 5 条「写在后台、我后面能修改」真正要的那道闸：能改 ≠ 改得动。
    #    判据来源是 `config/branches.json` 的 `consumers` 列（= readers_fn − 三个加载器
    #    − 已判同名异域）。**不许改用 `readers_fn`** —— 它分不清「读这个键」与
    #    「提到这个名字」，实测 `slab` 的 5 条命中量的全是 SU 的 kind="slab" 值标签。
    reg = branch_registry()
    exposed = [f["k"] for g in PROFILE_GROUPS for f in g["fields"]]
    if reg is None:
        rep["档案键"] = {"状态": "读失败", "在参数页上": len(exposed),
                       "含义": "登记表 config/branches.json 读不到 ⇒ 「死旋钮」"
                             "**这一趟没量到**，不是「没有死旋钮」"}
        warn.append("开关登记表 config/branches.json 读不到 ⇒ **死旋钮判据这一趟没跑**"
                    "（不是「没有死旋钮」）。先跑 `python _scratch/_gen_branches.py`")
        print("  [元数据自检] 档案键 %d 个：**未量**（登记表读不到）" % len(exposed),
              file=sys.stderr)
    else:
        n_dead = n_hole = 0
        dead_keys, hole_keys = [], []
        for k in exposed:
            r = reg.get(k)
            if r is None:
                n_hole += 1
                hole_keys.append(k)
                warn.append("档案键 %r 在参数页上，却**不在开关登记表里**"
                            "（config/branches.json 有洞）⇒ 它有没有消费者无人判" % k)
                continue
            if not r.get("consumers"):
                n_dead += 1
                dead_keys.append(k)
                warn.append("档案键 %r 在参数页上可改，但**载入后没有消费者**"
                            "（kind=%s）⇒ 改了不生效、且不报错" % (k, r.get("kind")))
        rep["档案键"] = {"状态": "已读", "在参数页上": len(exposed),
                       "登记表条数": len(reg),
                       "死旋钮": dead_keys, "不在登记表里": hole_keys}
        print("  [元数据自检] 档案键 %d 个：登记表 %d 条，**死旋钮 %d 个**（另有 %d 个不在登记表里）"
              % (len(exposed), len(reg), n_dead, n_hole), file=sys.stderr)

    # ── 档案键的**另一半**：「值送得到吗」。
    #    「有消费者」只答了「有人读这个键名」，答不了「这个值真被送进流程」。
    #    投递通道是**手抄的**（本仓「一个判断多份实现」的老毛病），漏一条的后果与
    #    死旋钮**长得一模一样**（改了不生效、不报错），但成因相反：
    #    死旋钮是「没人读」，这里是「值根本没到」。
    #    实测（2026-09-26）：`outer_wall_t` 在参数页上、**有**消费者（recognize.py:547 读它），
    #    而**每一条投递通道都不读它** ⇒ 永远是 dataclass 默认 0.24，改了永远不生效。
    #    （★ 这里**不写条数**：条数是一次带时刻的测量，写死就会像下面那句告警一样变成假话。）
    #    方向相反的一处：`floor_y_bands` 只有控制台通道读，而**批量识别通道**（96 栋
    #    实际走的那一条，run_step.py:87-89 有 profile.json 就优先它）不读
    #    ⇒ 33 栋 profile.json 里写着它却被忽略。
    chans = _delivery_channels()
    if chans is None:
        rep["投递通道"] = {"状态": "读失败",
                         "含义": "投递通道源码读不到 ⇒ 「值送得到吗」**这一趟没跑**，"
                               "不是「都送得到」"}
        warn.append("投递通道源码读不到 ⇒ **「值送得到吗」这一趟没跑**（不是「都送得到」）")
        print("  [元数据自检] 投递通道：**未量**（源码读不到）", file=sys.stderr)
    else:
        deliv = {}
        for nm, ks in chans:
            for k in exposed:
                if k in ks:
                    deliv.setdefault(k, []).append(nm)
        dead_val = [k for k in exposed if k not in deliv]          # 一条通道都不读
        # ★★ 这里**必须是「包含」，不能是「等值」**。原来是
        #   `deliv.get(k) == ["GLB 导出档位"]` —— 等值口径下，**表上多一行就会把这些键顶出去**：
        #   实测（2026-09-26，加 ④SU 分层建模 ⇒ glb_only 由 2 个掉成 1 个；
        #   再加 ⑤楼层清单 ⇒ 掉成 **0 个**），两个键于是落进下面的 `no_batch`，
        #   屏幕上打出一句**假红**：「批量识别通道不读 ⇒ 被静默忽略」——
        #   而事实上读它们的通道更多了。这正是本文件自己在 `no_batch` 上面记的那句话
        #   （假红会被学会忽略）**换个方向又犯一次**。
        glb_only = [k for k in exposed
                    if "GLB 导出档位" in deliv.get(k, [])
                    and "批量识别" not in deliv.get(k, [])
                    and "控制台识别" not in deliv.get(k, [])]
        # ★ 每个键**真正**由哪几条通道读（给告警用：措辞由它推出来，不写死名字/条数）
        chans_of = {k: list(deliv[k]) for k in exposed if k in deliv}
        # ★ `no_batch` 必须**排除** glb_only。这两个集合此前重叠，屏幕上于是同时出现
        #   「glb_windows 只由 GLB 导出通道读」与「glb_windows 被静默忽略」——
        #   同一个键在两栏里拿到相反的字。一个**被它该负责的那条通道读到了**的键，
        #   不该被印成「没人读」：那是**假红**，而假红会被学会忽略（铁律 47 的镜像）。
        no_batch = [k for k in exposed                                  # 批量识别不读它
                    if k in deliv and "批量识别" not in deliv[k] and k not in glb_only]
        latent = [k for k in exposed                                    # 控制台通道会丢
                  if "批量识别" in deliv.get(k, []) and "控制台识别" not in deliv[k]]
        br = _dropped_blast_radius(sorted(set(dead_val + glb_only + no_batch)))
        nb = (br or {}).get("__栋数__", 0)
        # ★ 分母本身也带状态：`br` 读不到时 `nb` 是 0，而 0 会印成「实测 0/0 栋」——
        #   那读起来正好是「一栋都没写这个键」，与「影响面没量到」同形（铁律 16）。
        rep["投递通道"] = {"状态": "已读", "条数": len(chans),
                         "通道": [nm for nm, _ in chans],
                         "一条都不读": dead_val, "识别通道不读": glb_only,
                         "批量识别不读": no_batch, "控制台通道会丢": latent,
                         # ★ 每个键**真正**由哪几条通道读 —— 给前端用。
                         #   前端此前自己写死了一句「只有「生成 GLB」这条路读它」，
                         #   于是后端一旦多认出一条通道，页面**照旧**说着那句话
                         #   （一个判断两份实现：一份跟着规则走，一份写在模板串里）。
                         "认它的通道": chans_of,
                         "分母": {"状态": "已读" if br is not None else "读失败",
                                # ★ 哨兵键必须挑出去：它在 `br` 里和真键混住，
                                #   谁遍历 `逐键` 都会把 `__栋数__` 当成一个键名
                                #   （本仓记过这个坑：哨兵值当分组键 ⇒ 多出一组假数据）。
                                "栋数": nb,
                                "逐键": {k: v for k, v in (br or {}).items()
                                       if k != "__栋数__"}}}
        for k in dead_val:
            # ★ 条数与通道名**由表推出来**，不写死（原措辞写死「三条投递通道」——
            #   表上加到五条之后，那句话就成了假话，而屏幕上完全看不出来）。
            warn.append("档案键 %r 在参数页上、也有消费者，但**投递通道没有一条读它**"
                        "（本趟核了 %d 条：%s）⇒ 永远是默认值，改了永远不生效"
                        % (k, len(chans), " / ".join(nm for nm, _ in chans)))
        # ★ 「批量出图读不读它」**只能测**，不能从名单推：`glb_only` 里的键都**不是**
        #   `BuildingProfile` 字段，所以「构造实参名 ∩ 字段名」那把尺子**结构上**不含它们 ——
        #   拿①去答会得到「不在里面」，那是同义反复、不是测量（铁律 26：要验的那个变量
        #   必须真的落进判据的作用域）。⇒ 用批量那条路的**原始字典读取**那把尺子。
        batch_reads = _batch_raw_reads() if glb_only else None
        for k in glb_only:
            # 不是死旋钮（它本来就只管 GLB 导出／SU 建模／楼层清单，见各自的 docstring），
            # 但**是一条真的缺口**：这些通道都**不在「批量识别」那条路上**，
            # 而 96 栋实际走的是批量那条（run_step.py:87-89 有 profile.json 就优先它）。
            # ★ 措辞三条纪律：
            #   (a) 通道名**由 `deliv` 推出来**，不写死「只有 GLB 导出」——
            #       那句话 2026-09-26 被实测证伪过（④SU 分层建模也读它），
            #       而它是**手维护名单**上的一句断言，下次加通道还是同一句假话；
            #   (b) 「批量出图不读它」必须是**测出来的负**，不是「名单上没有它」——
            #       量具读不到就印「未量」，不许退化成「不读」（铁律 16）；
            #   (c) 分母照旧从实物读（铁律 30/50）。
            # 实测（2026-09-26，逐条读源码 + 数真楼得出，不是按同族推的）：
            #   · `run_building.py`（批量出图）读到 50 个档案键、**不含这两个**；
            #     `SKIP_FLOORS` 从不赋值 ⇒ 批量路上恒为空集、**没有任何一栋会被跳过**。
            #   · `glb_windows` 96/96 栋 profile.json 写着 True，而模块默认就是 True
            #     （`build_standard_glb.py` 的 `INCLUDE_SYNTHETIC_WINDOWS`）⇒ 今天**零损害**，
            #     但那也意味着批量路上
            #     这个旋钮**两个方向都不生效**（改成 False 照样出合成窗）。
            #   · `skip_floors` 是真有存量的：c103 = [5]（它的 floor5.json 有 0 个房间）。
            if batch_reads is None:
                why_batch = "批量出图读不读它：**未量**（量具读不到，不许当成「不读」）"
            elif k in batch_reads:
                why_batch = "批量出图也读它 ⇒ 这条路**能生效**"
            else:
                why_batch = ("而**批量出图**（run_building.py，实测读 %d 个档案键）不读它，"
                             "在那条路上改了不生效" % len(batch_reads))
            warn.append("档案键 %r 由**非识别通道**读（%s）⇒ 改了不影响识别；%s"
                        "（实测 %d/%d 栋 profile.json 里写着它）"
                        % (k, " / ".join(deliv[k]), why_batch,
                           (br or {}).get(k, 0), nb))
        for k in no_batch:
            # ★ 分母从实物读（铁律 30/50）：原先这里写死「96 栋」，而 96 是**那一刻**的数。
            warn.append("档案键 %r **批量识别通道不读**（%d 栋走的就是它）⇒ 被静默忽略；"
                        "（实测 %d/%d 栋 profile.json 里写着它）"
                        % (k, nb, (br or {}).get(k, 0), nb))
        for k in latent:
            warn.append("档案键 %r 批量识别通道读、但控制台 fallback 会丢它 —— "
                        "那条路目前 0 栋在用，属于**潜伏**，不是现行故障" % k)
        # ★ 这一行也是**一份措辞**，同样是「一个判断一份实现」的危险区：
        #   原文写「只有 GLB 通道读 %d 个」，加了 ④⑤ 之后就成了假话
        #   （读它的通道不止 GLB 导出这一条）。改成由桶名推出来的说法，并带上**桶名本身**。
        print("  [元数据自检] 投递通道 %d 条：档案键 %d 个，**一条通道都不读 %d 个**；"
              "识别通道不读（只有非识别通道读）%d 个；批量识别不读 %d 个；"
              "控制台通道会丢 %d 个（潜伏）"
              % (len(chans), len(exposed), len(dead_val), len(glb_only),
                 len(no_batch), len(latent)), file=sys.stderr)
    for s in PIPELINE:
        if s["runnable"] and s.get("scope") == "single" and not s.get("args"):
            rep["阶段"]["缺args"].append(s["id"])
            warn.append("阶段 %s 标为可跑但没有 args 模板" % s["id"])
        # upstream 键没登记 ⇒ 消费侧的取值表认不出它。旧行为是静默 None
        # （stale 恒 False，屏幕上与「真的没过期」同形），现在消费侧会直接报错，
        # 这里提前在启动时点名，免得等到第一次请求 /status 才炸。
        if s.get("upstream") not in UPSTREAM_KEYS:
            rep["阶段"]["upstream未登记"].append(
                {"阶段": s["id"], "upstream": s.get("upstream")})
            warn.append(
                "阶段 %s 的 upstream=%r 没在 UPSTREAM_KEYS=%r 里登记 —— "
                "过期判据会静默判「不过期」，请登记键并同步各消费侧的取值表"
                % (s["id"], s.get("upstream"), UPSTREAM_KEYS))
    rep["阶段"]["阶段数"] = len(PIPELINE)
    rep["告警"] = warn
    rep["告警条数"] = len(warn)
    return rep


def stamp_self_check(rep, how, n):
    """给自检报告盖上「量于 / 缓存 / 第几次算」三个章。**只有这一处写这三个键**。

    ★ 一份自检结论**是一次带时刻的测量**（铁律 24/50）：同一个「0 个死旋钮」，
      是刚算出来的还是昨天冻结的，页面上必须能分。
    ★ 为什么集中到一处：实时那份（`self_check_cached`）与冻结那份（`freeze_meta`）
      都要盖这三个章，两处各写一份就是「一个判断多份实现」——
      同一个「这份读数有多旧」会有两种说法（本仓记过：同一屏两句话）。
    ★ 「第几次算」不能用「量于」代替：`量于` 只有**秒级**分辨率，
      同一秒内重算过没有，看时间戳**看不出来**（实测：伪指纹触发重算那一趟，
      「量于」与上一份逐字相同）—— 所以重算这件事要有一个能直接读的计数
      （铁律 22：别推理一个数，把它印出来）。
    """
    import time
    out = dict(rep)                       # 浅拷贝：别改调用方手上那份
    out["量于"] = time.strftime("%Y-%m-%d %H:%M:%S")
    out["缓存"] = how
    out["第几次算"] = n
    return out


def self_check():
    """启动自检的告警字符串列表（空 = 干净）。**是 `self_check_report()` 的投影**。

    非致命：只打印，不拦启动。

    ★ 「干净」必须与「没量」分开：报告总会印一行分母（见 `self_check_report`），
      所以屏幕上「量过 N 个、0 个死」与「判据没跑」不是同一行字。
    """
    return self_check_report()["告警"]


def _registry_stamp():
    """`config/branches.json` 的**廉价**指纹（mtime 纳秒 + 大小）；读不到返回 None。

    ★ 它只用来让缓存失效，**不够格当内容指纹**：改内容不改长度、同一纳秒内改两次，
      都可能看不出来。所以它**不产出任何「这个文件没变」的结论**
      （本仓铁律：指纹说「未变」不能当证据，见 `_gen_branches.py` 那两列）。
    """
    p = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "..", "..", "config", "branches.json"))
    try:
        st = os.stat(p)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


_SELF_CHECK_CACHE_KEY = ()


def reset_self_check_cache():
    """显式清缓存。改过 `.py` 源码或某栋 `profile.json` 之后要调用它 ——
    这两类输入**没有**被自动盯着（见 `self_check_cached`）。"""
    global _SELF_CHECK_CACHE, _SELF_CHECK_CACHE_KEY, _BRANCH_CACHE
    _SELF_CHECK_CACHE = None
    _SELF_CHECK_CACHE_KEY = None
    _BRANCH_CACHE = None


def self_check_cached():
    """`self_check_report()` 的**进程内缓存**版；给 `/api/meta` 用。

    ★ 为什么要缓存：这条自检要读每栋楼的 `profile.json`（`_dropped_blast_radius`）、
      跑三次 AST 扫描、还会经 `spec_defaults()` 把建模层拖进来 —— 而 `/api/meta`
      是控制台打开时的**第一个请求**。每请求算一遍纯属浪费。
    ★ 为什么必须**自报时刻**：缓存下来的是一份**带时刻的测量**（铁律 24/50）——
      用户改了 `config/branches.json` 之后这一页还是旧读数，而屏幕上两者长得一样。
      所以把「量于」和「什么会让它重算」一起写进返回体，谁读都能看见它有多旧。
    ★ 失效条件**只能写我兑现得了的**：`config/branches.json` 变了会自动重算
      （连同 `branch_registry()` 自己那份缓存一起清，否则重算出来还是旧表）；
      而**改 `.py` 源码、改某栋 `profile.json` 不会**自动重算 —— 那要显式调
      `reset_self_check_cache()`。这句话必须留在返回体里，不能只留在注释里。
    ★ 只给页面用。启动自检（`console_meta.__main__`）与 `freeze_meta.gate()`
      仍旧调**不缓存**的 `self_check()` —— 那两个场合要的就是此刻。
    """
    global _SELF_CHECK_CACHE, _SELF_CHECK_CACHE_KEY, _BRANCH_CACHE, _SELF_CHECK_N
    import copy
    key = _registry_stamp()
    if _SELF_CHECK_CACHE is not None and key != _SELF_CHECK_CACHE_KEY:
        _BRANCH_CACHE = None
        _SELF_CHECK_CACHE = None
    if _SELF_CHECK_CACHE is None:
        _SELF_CHECK_N += 1
        _SELF_CHECK_CACHE = stamp_self_check(
            self_check_report(),
            "进程内；改 config/branches.json 自动重算，"
            "改 .py 源码或 profile.json 需调 console_meta.reset_self_check_cache()",
            _SELF_CHECK_N)
        _SELF_CHECK_CACHE_KEY = key
    return copy.deepcopy(_SELF_CHECK_CACHE)
