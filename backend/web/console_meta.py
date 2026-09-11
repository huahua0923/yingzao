# -*- coding: utf-8 -*-
"""控制台的「参数化 + 流程化」元数据（单一事实源）。

为什么单独一个模块：控制台要展示的**全部**可调参数（档案 + 规格）与**全部**流程阶段，
必须在一处集中定义、由后端下发给前端。前端不再硬编码字段表——
否则加一个 profile 字段要改两个地方，必然漂移。

三张表：
  PROFILE_GROUPS  —— data/buildings/<name>/profile.json 的字段（识别阶段参数）
  SPEC_GROUPS     —— <name>/spec.json 的字段（建模阶段参数，GLB 几何全靠它）
  PIPELINE        —— 从 DWG 到索引的完整阶段链（含每阶段产物、作用域、危险级别）

不变式（`self_check()` 在启动时校验，非致命只告警）：
  · SPEC_GROUPS 的每个 key 都必须是 build_standard_glb 真实消费的键
  · PIPELINE 里 runnable=True 的阶段，其脚本必须真的接受单栋 argv
    （`_wall_thin_batch.py` / `convert_dwg_to_dxf.py` 忽略 argv、会跑全仓，故标 runnable=False）
"""
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
    {"group": "⑩ 建模输出口径（控制台记账用，不参与识别）", "fields": [
        {"k": "glb_windows", "label": "导出合成窗", "type": "bool",
         "help": "该楼重出 GLB 时是否带 synthetic 窗。**必须记账**："
                 "所有 floor JSON 的窗都是 synthetic=True，而 run_step / "
                 "run_building --glb 的 INCLUDE_SYNTHETIC_WINDOWS 默认 False —— "
                 "不记住这个口径，「流程 → 生成 GLB」不勾选就会静默把窗户全剥掉。"
                 "load_profile 逐键读取，本键被识别层忽略、只给控制台用"},
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
#   upstream 该阶段产物的**上游真值**：'dxf' 或 'floors'。
#            过期判据 = 产物 mtime 早于它的上游 mtime。**不能一刀切用 floors** ——
#            spec.json 和 floor0.json 是 recognize 的同批产物（互为兄弟），
#            dxf_plan 是「从 DXF 渲染的源图纸真值」、跟 floors 无关；
#            拿 floors 当所有人的上游会把它们全误标成「过期」。
#   inplace  True = 就地改写楼层、没有独立产物，完成与否**无法从产物推断**。
#            （thin / doorpunch 改的就是 floors/floor0.json，那个文件 recognize 早就写了，
#             拿它的存在当「这一步做过了」是假信号。）
PIPELINE = [
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
    {"id": "thin", "no": 2, "label": "重建内墙（单栋强制）", "scope": "single",
     "script": "_wall_thin_force.py", "args": ["{name}"],
     "writes": True, "slow": True, "runnable": True, "danger": "high",
     "produces": ["floors/floor0.json"], "upstream": "dxf", "inplace": True,
     "why_manual":
         "批量版 _wall_thin_batch.py 忽略 argv、会遍历全部 48 栋 —— 绝不能在控制台一键跑。"
         "此处接的是单栋强制版，逐层 .orig 备份 + 数值验收 + 不通过自动回滚该层",
     "desc": "⭐ 交付链的真正一环：recognize 产的内墙是粗环 blob（覆盖率>20%）不是交付物，"
             "真内墙由这一步从 DXF 双线重配对；门洞也必须在这里再挖一次"},
    {"id": "doorpunch", "no": 3, "label": "门洞外科打穿", "scope": "single",
     "script": "_door_punch_apply.py", "args": ["{name}"],
     "writes": True, "slow": False, "runnable": True, "danger": "high",
     "produces": ["floors/floor0.json"], "upstream": "dxf", "inplace": True,
     "desc": "备份 → 挖门洞 → 数值复验 → 失败自动回滚。门=gap 不是 hole，盒深必须 > 墙厚"},
    {"id": "glb", "no": 4, "label": "生成 GLB", "scope": "single",
     "script": "backend/web/run_step.py", "args": ["{name}", "glb"],
     "writes": True, "slow": False, "runnable": True,
     "produces": ["{name}-building.glb"], "upstream": "floors",
     "desc": "只用现有 floors + spec 重建 GLB（不重跑识别，快）"},
    {"id": "qa", "no": 5, "label": "结构体检 I1–I10", "scope": "single",
     "script": "qa_structural.py", "args": ["{name}"],
     "writes": False, "slow": False, "runnable": True,
     "produces": [], "upstream": None,
     "desc": "不变量门禁，只读存档 JSON 不写任何数据。任何改动后必跑。"
             "ERROR 数量是回归的第一指标"},
    {"id": "cadrender", "no": 6, "label": "出忠实源图纸", "scope": "single",
     "script": "_dxf_cad_render.py", "args": ["{name}"],
     "writes": True, "slow": True, "runnable": True,
     "produces": ["dxf_plan/index.html"], "upstream": "dxf",
     "desc": "白底黑线、忠实还原 CAD 线稿（真值参照）"},
    {"id": "recogrender", "no": 7, "label": "出识别叠加图", "scope": "single",
     "script": "_dxf_png_batch.py", "args": ["{name}"],
     "writes": True, "slow": True, "runnable": True,
     "produces": ["dxf_plan_recog/floor0.png"], "upstream": "floors",
     "desc": "灰细线源墙垫底 + 彩色识别结果（灰实=墙/红=门/绿=楼梯井/蓝=柱）"},
    {"id": "compare", "no": 8, "label": "A|B 对比页", "scope": "single",
     "script": "_dxf_compare_render.py", "args": ["{name}"],
     "writes": True, "slow": False, "runnable": True,
     "produces": ["compare.html"], "upstream": "floors",
     "desc": "源图纸(真值) vs 第一轮识别，逐层并排 —— 找识别漏/错的主要视窗"},
    {"id": "audit", "no": 9, "label": "覆盖度审计", "scope": "single",
     "script": "_dxf_audit.py", "args": ["{name}"],
     "writes": True, "slow": True, "runnable": True,
     "produces": [], "upstream": None,
     "desc": "带洞覆盖 + 门 mask 的墙漏检审计，输出可疑层排名"},
    {"id": "sweep", "no": 10, "label": "全仓缺陷扫描", "scope": "all",
     "script": "_sweep_modeling.py", "args": [],
     "writes": False, "slow": True, "runnable": True,
     "produces": [], "upstream": None,
     "desc": "只读回归扫描，跑全部楼的几何缺陷统计"},
    {"id": "index", "no": 11, "label": "刷新索引", "scope": "all",
     "script": "build_index.py", "args": [],
     "writes": True, "slow": False, "runnable": True,
     "produces": ["buildings/index.json"], "upstream": "floors",
     "desc": "生成 data/buildings/index.json，供网页选择器消费"},
]

_BY_ID = {s["id"]: s for s in PIPELINE}


def get_stage(step):
    """按 id 取阶段定义；不存在返回 None。"""
    return _BY_ID.get(step)


def runnable_ids():
    return [s["id"] for s in PIPELINE if s["runnable"]]


# ---------------------------------------------------------------- 规格默认值
_SPEC_DEFAULT_CACHE = None


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


def self_check():
    """启动自检：规格键是否都被建模层真实消费；可跑阶段是否都有 argv。

    返回告警字符串列表（空 = 干净）。非致命：只打印，不拦启动。
    """
    warn = []
    try:
        real = set(spec_defaults()) | {"style", "roofType"}
    except Exception as e:  # noqa: BLE001
        warn.append("无法读取建模层规格默认值: %s: %s" % (type(e).__name__, e))
        real = None
    if real is not None:
        for g in SPEC_GROUPS:
            for f in g["fields"]:
                if f["k"] not in real:
                    warn.append("规格键 %r 不在 build_standard_glb 消费列表里" % f["k"])
    for s in PIPELINE:
        if s["runnable"] and s.get("scope") == "single" and not s.get("args"):
            warn.append("阶段 %s 标为可跑但没有 args 模板" % s["id"])
    return warn
