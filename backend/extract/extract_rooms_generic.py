# -*- coding: utf-8 -*-
"""通用房间提取器：按 profile.classifier 分派，兼容 LWPOLYLINE 与 LINE+INSERT 两套约定。

与 extract_rooms.py（理化楼硬编码基线）、extract_rooms_c006.py（六教专版）并列。
本脚本是「房间提取管线」的唯一通用入口，逐栋复用同一套几何 + 标注关联逻辑：

  - 墙/门几何：classifier=='line' → classify_line（墙=LINE 双线、门=INSERT 块）；
                否则 → classify（墙=LWPOLYLINE，门由 detect_doors 几何判定）。
  - 房间边界：outline（derive_walls_and_outline）- wall_geoms - 门洞补丁（门盒补闭）。
  - 标注层：按资产管理图国标层名「数字前缀」定位（5面积/6房间号/7用途/8单位），
    天然免疫 ODA 转换产生的层名乱码（代理项 surrogate）；中文编码 UTF-8。
  - 过渡层 wall_x 过滤：与 floor.py / recognize.py 同口径（如六教第 7 层只取塔楼墙）。

用法:
  python backend/extract/extract_rooms_generic.py c009            # 写该楼 rooms.json
  python backend/extract/extract_rooms_generic.py c009 --dry      # 只打印统计
  python backend/extract/extract_rooms_generic.py --all --dry     # 全楼普查
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from paths import ensure_sys_path  # noqa: E402

ensure_sys_path()                    # 仓库根：run_building.py 等入口在这
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ezdxf
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union

from run_building import load_profile
from recognizer.geometry import derive_walls_and_outline, detect_doors
from recognizer.floor import reference_outline_for, unify_floor_set, outline_for_floor
from recognizer import outline as OUT
from recognizer.profile import to_local, floor_of

try:                                   # 作为包导入（backend.extract.extract_rooms_generic）
    from . import room_route as RR
except ImportError:                    # 作为脚本直接跑（python backend/extract/xxx.py）
    import room_route as RR

ENCODING = "utf-8"   # ODA 转换器写出的教学楼 DXF 中文标注是 UTF-8（房间号/面积 ASCII 不受影响）

# 每楼房间 id 全局唯一偏移（理化楼基线 1..118；教学楼各占 100000 一段）
ID_BASE = {
    "c006": 100000, "c009": 200000, "c022": 300000, "c025": 400000,
    "c026": 500000, "c027": 600000, "c028": 700000, "c041": 800000,
    "c103": 900000, "c104": 1000000, "c114": 1100000, "c108": 1200000,
    # 宿舍/公寓簇（芙蓉园 c017-c034、西区公寓 c079-086、南苑 ny27-29 等面积图式：
    # 单线墙+MTEXT标注，无柱层）：id 段 2000000 起，每楼 10 万段防 DB 主键撞车
    "c031": 2000000, "c017": 2100000, "c018": 2200000, "c019": 2300000,
    "c029": 2400000, "c030": 2500000, "c032": 2600000, "c033": 2700000,
    "c034": 2800000, "c043": 2900000, "c044": 3000000, "c045": 3100000,
    "c046": 3200000, "c054": 3300000, "c055": 3400000, "c056": 3500000,
    "c057": 3600000, "c059": 3700000, "c060": 3800000, "c061": 3900000,
    "c062": 4000000, "c063": 4100000, "c064": 4200000, "c065": 4300000,
    "c072": 4400000, "c073": 4500000, "c079": 4600000, "c080": 4700000,
    "c083": 4800000, "c084": 4900000, "c085": 5000000, "c086": 5100000,
    "c109": 5200000, "c116": 5300000, "ny27": 5400000, "ny28": 5500000,
    "ny29": 5600000,
    # c113（艺术楼）：2026-09-23 补。此前**从没进过本表**，于是 run() 一次都没跑过，
    #   data/buildings/c113/rooms.json 一直是 `[]`（2 字节）——交付 5 层 0 间房，
    #   而图纸自带面积表写着 21/36/23/18/15 间。漏的不是识别，是名单。
    #   本楼图层与默认口径一致（5面积 151 / 6房间号 167 / 7房间名称 148，无需 OVERRIDE）。
    "c113": 5700000,
    # ── 2026-09-23 夜：A1/A6 GAP 批量补名单 ────────────────────────────────────
    # 背景：全库 95 栋里 45 栋 rooms.json 是 `[]`，且那 45 栋**恰好**是没进本表的
    #   45 栋（双向零例外，A1 与 A6 同因）。也就是说缺的不是识别能力，是**名单**。
    # 名单准入判据（缺一不可，逐栋核过）：
    #   ① 源 DXF 在、能读；② 图纸自带面积表里**本栋图号**的层数 == 模型层数
    #      （用 `_scratch/_own_sheets_vs_model.py` 量：层数对不上就**不能**抽，
    #       否则房间会落到错的层或落到层外被丢 —— 抽取前先修层，见 c001 那条）；
    #   ③ 图上有 5/6/7/8 标注层（至少要有 6房间号）。
    # 排除在外的（**不是漏，是有理由**，另档处理）：
    #   · c011 c015 c020 c053 c074 c075 c081 c105 c107 c115 c118
    #     —— 图纸层数 ≠ 模型层数（缺 D1 / 缺夹层 J / 被并成 1 层），**先修层再抽**
    #   · （c001 原在此列，2026-09-24 凌晨已修：见下面那条「水上图书馆」）
    #   · （c002 c003 原在此列，2026-09-23 夜已修：见下面那条「沿 X 并排」）
    #   · c010（银杏体育场）c077（香樟体育场）—— 图上**根本没有房号标注**，应为 N/A
    #   · c005（理化楼）—— 房间已在老位置 data/rooms.json（118 间，building=null），
    #     是**存放位置**问题，不是识别问题
    #   · c037 c012f1 —— 模型层**多于**图纸声明，也先核层
    "c004": 5800000, "c007": 5900000, "c008": 6000000, "c008f1": 6100000,
    "c008f2": 6200000, "c010f1": 6300000, "c012": 6400000, "c021": 6500000,
    "c023": 6600000, "c024": 6700000, "c035": 6800000, "c036": 6900000,
    "c038": 7000000, "c047": 7100000, "c058": 7200000, "c066": 7300000,
    "c066f1": 7400000, "c071": 7500000, "c106": 7600000, "c110": 7700000,
    "c112": 7800000, "c117": 7900000, "m281": 8000000, "m282": 8100000,
    # ── 2026-09-23 深夜：南北翼楼「各层平面沿 X 并排」修好之后进名单 ───────────
    # 用户原话：「南北翼楼，一看就没有分层，都摞在一起，每层楼都写的清楚的很」。
    # 量下来 c002/c003 十层平面**并排画在十个 X 位置、共用一条 Y 带**，
    # 定层代码假设"层沿 Y 分开"⇒ 十层塌成一层（图上 10 层，模型 1 层）。
    # 同上还有个连带的坑：旧 `x_range` 上界 1681941 把 F10（x≈1759~1764k）
    # 整层墙**过滤成 0 段** —— 于是"看模型觉得 F10 不存在"，而图上它好端端在。
    # 修法：写 `floor_plans`（X 判列，既有机制）+ 重算 x_range；
    # 局部原点按体裁取 **cx 逐层、cy 全体共用**（见 _scratch/_fix_row_floors.py 的注解）。
    # 修后：楼层数 10、校验问题 0，F1~F8 各 83~95 段墙、F9/F10 为顶层小平面。
    "c002": 8200000, "c003": 8300000,
    # ── 2026-09-24 凌晨：砚湖图书馆（水上图书馆）补层之后进名单 ─────────────────
    # 用户原话：「水上图书馆，f0其实是两层」。查下来不是"两层"，是**图上最底下那层
    # （D1）压根没进模型**：图把 6 个平面沿 Y 摞着画，而 `floor_ys` 只有 5 个，
    # 定层取"最近层中心"且**没有下界** ⇒ D1 的墙全被并进 F0，交付的 F0 是
    # 「D1 平面 + 1 层平面」两片叠在一起的东西。已用 `_scratch/_add_d1_floor.py` 补层：
    # `floor_ys` = [84750, 203570, 324338, 451968, 574935, 697770]（6 个），
    # 并删掉 `floor_y_bands`（那份是死配置，`load_profile` 从不读 —— 见该脚本注解）。
    # 准入三条逐条核过：① DXF 在能读 ✓；② 图纸自带面积表本栋图号 6 层
    #   （D1 1540.5㎡/6房、1 1508.4/13、2 2732.9/2、3 2626.2/2、4 2471.3/23、
    #   5 1688.7/25）== 模型 6 层 ✓；③ 有 `6房间号` 标注层（MTEXT，带格式码
    #   `\A1;{\fSimSun|b1|i0|c134|p2;01-D1-01}`）✓。故从"先修层再抽"名单移入。
    "c001": 8400000,
}

# 资产管理图国标层名数字前缀 → 语义。逐栋可能不同（如 c006 7=用途/8=单位；
# 理化楼老图 7=使用单位/8=用途），可在下方 LAYER_ROLE_OVERRIDE 覆盖。
LAYER_ROLE = {"5": "area", "6": "number", "7": "purpose", "8": "dept"}
LAYER_ROLE_OVERRIDE = {
    # 例：若某楼 7/8 语义颠倒，写 "c0xx": {"7": "dept", "8": "purpose"}
    # c009/c022 的图层是「7使用单位 / 8用途」（与 c006 的「7用途 / 8单位」相反），
    # 默认 LAYER_ROLE 按 c006 口径，故这两栋需颠倒 7/8。
    "c009": {"7": "dept", "8": "purpose"},
    "c022": {"7": "dept", "8": "purpose"},
    # c114（第十教学楼·启智楼）：无 7 层，唯一标注层「8房间用途」内容是房间用途
    #   （实验室/会议室/教研室/办公室），默认 8→dept 会错放「单位」列，改为 8→purpose。
    "c114": {"8": "purpose"},
    # c031（芙蓉园3号公寓）：层名 7使用单位 / 8房间用途（与 c006 的 7用途/8单位 相反），
    #   默认 LAYER_ROLE 会把 单位↔用途 互换，须颠倒。楼层 5面积/6房间号 语义不变。
    "c031": {"7": "dept", "8": "purpose"},
    # ---- 层名撒谎：`7使用单位` 里装的其实是用途（2026-09-13 全库普查实测）----
    #
    # 上面那些楼（c006/c009/c022/c029/c031/c054…）**同时**有「用途层」和「使用单位层」，
    # 两层的文本确实是两种东西（c031：7使用单位=公寓 / 8房间用途=本科生公寓），
    # 按层名认角色是对的。
    #
    # 但下面这 8 栋**图上根本没有用途层**，唯一那层叫 `7使用单位`，装的却是用途 ——
    # 逐栋把该层最常见的文本打出来看过（`_scratch/_purpose_text_probe.py`，走的是
    # `mtext_center` 同一条清洗通道）：
    #
    #   c017 公寓×232 办公室 自习室 杂物间 洗衣房 配电房 收发室 值班室
    #   c018 公寓×169 杂物间 值班室 配电房 自习室
    #   c025 办公室×11 实验室×10 教师工作室×9 资料室 会议室 教研室
    #   c041 多媒体教室×19 教师工作室×16 实验室 研讨室 值班室
    #   c046 公寓×264（另有 49.00m 等面积串混入）
    #   c103 多媒体教室×135 教员休息室×67 智慧教室×29
    #   c104 多媒体教室×91 教员休息室×11 试卷保密室 值班室 消防控制室
    #   c116 教职工公寓×83 其他服务用房 其他仓库
    #
    # 全是**用途**没有一个单位名。`MARKERS` 的 ("使用单位","dept") 先于数字前缀命中，
    # 于是这 8 栋的用途被塞进 `dept`、`purpose` 恒为 null（c104 rooms.json 实测
    # `purpose:null / dept:"教员休息室"`，而同一栋的 floors 快照里 purpose 是对的 ——
    # 那是前缀口径时代的产物，后来才被覆盖坏）。
    #
    # 改成一栋一行的**具名口子**（不是放宽判据）：只把这 8 栋的该层判成 purpose。
    # `dept` 因此变 null —— 这是诚实的：这几张图上确实没有「使用单位」这一层的信息，
    # 把「实验室」同时抄进 `dept` 才是撒谎。
    "c017": {"7使用单位": "purpose"},
    "c018": {"7使用单位": "purpose"},
    "c025": {"7使用单位": "purpose"},
    "c041": {"7使用单位": "purpose"},
    "c046": {"7使用单位": "purpose"},
    "c103": {"7使用单位": "purpose"},
    "c104": {"7使用单位": "purpose"},
    "c116": {"7使用单位": "purpose"},
    # c026/c027：`7使用单位` 同样是用途（实验室/办公室/教师工作室/会议室/库房/教研室…），
    # 另有一层 `7.2名称` 装的是**房间名**（副院长 / 学生会 / 学术报告厅（二）/ 法学数据
    # 实验室）—— 它不是用途，只是被 PREFIX["7"] 的前缀兜底误判成了 purpose，于是
    # 「名称」抢走了用途的位置（c026 只有 33/46 间有用途、c027 只有 16/29）。
    # 显式给 None = 从 role_map 里剔掉它：`read_labels` 拿到 None 会 `continue`
    # （该层只被 read_labels 消费，剔除是安全的）。
    "c026": {"7使用单位": "purpose", "7.2名称": None},
    "c027": {"7使用单位": "purpose", "7.2名称": None},
}

# ---- 第二类「一层里混装两种东西」：这一层**确实**是用途层，但里面同时躺着面积串 ----
#
# c046 实测（2026-09-13）：`7使用单位` 层共 528 条 MTEXT = **264 条「公寓」+ 264 条面积串**
# （`49.00m`、`30.00m`…）。两组都落在**同一批房间**里（各命中 246 间）⇒ `assign_labels`
# 逐间房按**文档顺序**取第一个命中的标注，面积串排在前 ⇒ **全赢**。结果 c046 的 228 条
# purpose 全成了 `49.00m` 这种面积串，真用途 0 条，且已经写进了交付 rooms.json 与 floors。
#
# 为什么这**不是**归属规则（`assign_labels` 的排序键）能解的问题：`49.00m` 和 `公寓` 的
# 几何中心都在房间内部，任何纯几何或纯文本的排序键都要先知道"哪段文字是用途"——那是**语义**
# 判断，排序键做不了（体育馆里 `50m泳道`/`100m跑道` 既是面积形态又是真用途，排序键必判错一边），
# 而且改排序键会重排**所有**建筑的归属，违反「不许改好一栋、改坏一片」。
#
# 也别指望"撤下 LAYER_ROLE_OVERRIDE 就等于留空"：`7使用单位` 会先被子串规则
# `("使用单位","dept")` 命中 ⇒ 这 528 条整体落进 **dept** 桶，只是把污染从 purpose 挪到 dept。
#
# 所以修法是**具名到「楼 + 精确层名」**的层判据：明确声明"这一层里形如面积的文本不算用途"。
# 表里只列本次**实测量过**的层；加一栋必须先跑 `_scratch/_purpose_area_probe.py` 看形态命中面。
PURPOSE_DROP_AREA_LIKE = {
    "c046": {"7使用单位"},
}

# "这段文字是个面积数"的判据。写法上必须**全锚定**（`fullmatch` 语义），不能是前缀匹配：
# 前缀式 `^[\d.]+\s*m` 会连真用途 `50m泳道`/`100m跑道`/`12m跨` 一起吃掉。全锚定后，
# 整串必须恰好是"数字 + 单位"，单位后再有任何字符（含 CJK）都不算。
# 宁窄勿宽：判窄了只会漏修这一层（能被探测器的"残留条数"发现），判宽了会静默抹掉真用途。
AREA_LIKE_RE = re.compile(r"^\d{1,4}(?:\.\d{1,3})?\s*(?:m|M|m2|M2|m²|㎡|平方米)$")

MIN_ROOM_AREA = 1.0
DOOR_PLUG_DEPTH = 0.4
# 标注点→房间多边形的容差（米）。房号 MTEXT 的 attachment_point=1(左上)：insert 是文本
# 左上角、文字向右下延展；锚点落在墙带（被 carve 掉）上、悬在房间多边形外 ~150mm。现在
# 已改用文本几何中心（mtext_center）当标注点，中心在房间内部，故只需很小的兜底容差
# （覆盖字宽估算误差）。0.2m 大容差会在密集小房间楼（c104）误匹配相邻房间（实测歧义 9）。
LABEL_TOL = 0.1


# MTEXT 里的**按位记法**控制序列（`^J`=LF、`^M`=CR、`^I`=TAB）与裸 C0 控制字符。
# 实测（2026-09-13 全库扫交付 JSON）：整个库只有 1 条 —— c103 的 `'办公室^J（督导组）'`。
# 只替换这三个**明确写出来的**控制码，理由：
#   · 不许写成泛化的 `\^[A-Za-z]` 或"去掉所有 `^`" —— 那会连 `^2`（上标）这类**合法插入符**
#     一起杀掉，而且从一个具名缺陷扩成一条全局判据（铁律⑱：要放的宽必须是具名口子）；
#   · 不许顺手压 CJK 标点前的空格（`办公室 （督导组）`→`办公室（督导组）`）—— 那是第二处
#     **没量过**的字节改动，验不动就别做。
# 换成**一个空格**而不是删掉：与上面 `\P` 的处理口径一致（段内换行 → 空格），
# 且末尾的 `" ".join(s.split())` 会把连续空白收成一个。
CTRL_SEQ = {"^J": " ", "^M": " ", "^I": " "}
CTRL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 交付闸门用的第二条：**任何** `^` + 字母。注意它比 CTRL_SEQ 宽（`^2` 上标也会命中）——
# 这是故意的：`clean()` 里"洗哪些"必须窄（判据），闸门里"拦哪些"宁可宽（检查）。
# 拦错了只是响亮失败 + 列出原值，人工一眼可判；漏放了就是脏值进交付、下游渲染成换行/乱码。
CARET_RE = re.compile(r"\^[A-Za-z]")


def clean(s):
    s = re.sub(r"\\[A-Za-z][^;]*;", "", s)
    s = s.replace("{", "").replace("}", "")
    s = s.replace("\\P", " ")  # MTEXT 段内换行 → 空格（如「教师工作室\P实验准备室」）
    s = s.replace("\\", "")
    for seq, rep in CTRL_SEQ.items():
        s = s.replace(seq, rep)
    s = CTRL_CHAR_RE.sub(" ", s)
    return " ".join(s.split())


def mtext_center(e):
    """MTEXT 标注的几何中心（CAD 毫米）。attachment_point=1(左上) 时 insert 是文本左上角、
    文字向右下延展；房号锚点落在墙带（被 carve 掉）上、悬在房间多边形外 ~150mm。改用文本
    中心（锚点右移半宽、下移半高）→ 落点进入房间内部，无需大容差 buffer，避免密集小房间
    （c104）被大容差误匹配相邻房间。文本宽按可见字符数 × 字高 × 0.55 估算（CAD SHX 字宽
    高比 ≈ 0.55），高按行数 × 字高（房号单行，高 = char_height）。
    返回 (cx, cy, cleaned_text)。"""
    ap = e.dxf.attachment_point
    ch = e.dxf.char_height
    ins = e.dxf.insert
    lines = [clean(ln) for ln in (e.text or "").split("\\P")]
    n = max((len(ln) for ln in lines), default=0)
    W = n * ch * 0.55
    H = ch * max(len(lines), 1)
    x0, y0 = ins.x, ins.y
    # 水平：列 2/5/8 居中、3/6/9 右对齐、1/4/7 左对齐
    if ap in (2, 5, 8):
        cx = x0
    elif ap in (3, 6, 9):
        cx = x0 - W / 2
    else:
        cx = x0 + W / 2
    # 垂直：行 1/2/3 顶、4/5/6 中、7/8/9 底
    if ap in (1, 2, 3):
        cy = y0 - H / 2
    elif ap in (7, 8, 9):
        cy = y0 + H / 2
    else:
        cy = y0
    text = " ".join("".join(lines).split())
    return cx, cy, text


def read_labels(msp, role_map, drop_area_like=None):
    """收集各语义层标注。role_map 键 = 精确层名；值 = area/number/purpose/dept。
    精确层名优先，其次层名数字前缀（老楼约定 5/6/7/8）。

    `drop_area_like`（2026-09-13 新增，默认 None = 行为与从前逐字节相同）：一组**精确层名**，
    来自 `PURPOSE_DROP_AREA_LIKE[楼名]`。列进来的层里，role 判成 purpose 且文本**整串**形如
    面积数（`AREA_LIKE_RE`）的标注**不收集**。这是具名到层的口子（见该表上方注释：c046 的
    `7使用单位` 里 264 条「公寓」和 264 条面积串同层共存、同落一批房间，面积串按文档顺序全赢）。

    判据必须作用在 `clean()` **之后**的文本上（`mtext_center` 返回的已是清洗后的）——
    否则 `\\A1;…` 格式码和 `^J` 之类控制字符会挡住全锚定匹配。
    """
    labels = {"area": [], "number": [], "purpose": [], "dept": []}
    for e in msp:
        if e.dxftype() != "MTEXT":
            continue
        l = e.dxf.layer or ""
        role = None
        if l in role_map:
            role = role_map[l]
        elif l and l[:1] in role_map:
            role = role_map[l[:1]]
        if not role:
            continue
        cx, cy, text = mtext_center(e)
        if role == "purpose" and drop_area_like and l in drop_area_like \
                and AREA_LIKE_RE.match(text):
            continue
        labels[role].append((cx, cy, text))
    return labels


def layer_role_map(msp):
    """按层名语义解析每层标注角色，免疫「7↔8 语义随楼颠倒」「8.2/9/双 8 层」等变体。
    数字前缀只是兜底（老楼固定 5/6/7/8 布局）；真实语义在层名里：
      房间号→number  面积→area  用途/功能/类型→purpose  使用单位/单位→dept
    返回 {精确层名: role}，只含本楼实际出现的 MTEXT 层。
    c006 等老楼层名（7用途/8使用单位）与这些规则天然一致，不回归。"""
    MARKERS = (("房间号", "number"), ("面积", "area"),
               ("使用单位", "dept"), ("单位", "dept"),
               ("用途", "purpose"), ("功能", "purpose"), ("类型", "purpose"))
    PREFIX = {"5": "area", "6": "number", "7": "purpose", "8": "dept"}
    seen = set()
    for e in msp:
        if e.dxftype() != "MTEXT":
            continue
        l = e.dxf.layer or ""
        if not l or l in seen:
            continue
        seen.add(l)
    out = {}
    for l in seen:
        role = None
        for marker, r in MARKERS:
            if marker in l:
                role = r
                break
        if role is None and l[:1] in PREFIX:
            role = PREFIX[l[:1]]
        if role:
            out[l] = role
    return out


def door_box(d, depth):
    """detect_doors 返回的 {x,y,w,horiz}（本地米）→ 门盒补丁。"""
    half = d["w"] / 2
    if d["horiz"]:
        return box(d["x"] - half, d["y"] - depth / 2, d["x"] + half, d["y"] + depth / 2)
    return box(d["x"] - depth / 2, d["y"] - half, d["x"] + depth / 2, d["y"] + half)


def _opening_span(region, cx, cy, horiz, limit=3.5, step=0.02):
    """从门心沿**洞口方向**向两侧扫，返回最近墙体到门心的距离 (l, r)（米）。

    ★ 2026-09-14 加（c006 塔楼判例）：补丁按 **profile 标称门宽**（单扇 1.0 / 双扇 1.5）
    定尺寸，**洞口只要比它宽一点就补不满** —— 实测 F7：走廊南墙在
    `x 5.79..17.40` 有墙、`17.40..19.47` 是 1.5m 门 + 0.33m 墙垛，而门盒只补
    1.5m ⇒ 剩 0.24m 缝隙 ⇒ 走廊与右下角那间房**连通成一片**，被当成一间
    `6-C-08-01`（343.25 ㎡ vs 图纸声明 145.46 ㎡，+136%），F7–F10 四层同型。
    两侧都在 limit 内撞到墙 ⇒ 这是真洞口，按实测跨度补。
    """
    def hit(sign):
        t = step
        while t <= limit:
            x, y = (cx + sign * t, cy) if horiz else (cx, cy + sign * t)
            if region.covers(Point(x, y)):
                return t
            t += step
        return None
    return hit(-1.0), hit(1.0)


def door_plugs_insert(doors, F, p, region=None):
    """classify_line 的 INSERT 门点列（CAD 毫米）→ 本层门盒补丁（本地米）。

    region 非空 ⇒ 补丁宽度按**实测洞口跨度**（见 `_opening_span`）；扫不到墙则退回标称门宽。
    """
    plugs = []
    for pts in doors:
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        if floor_of(p, cx, cy) != F:
            continue
        local = [to_local(p, x, y, F) for x, y in pts]
        xs = [q[0] for q in local]; ys = [q[1] for q in local]
        horiz = (max(xs) - min(xs)) >= (max(ys) - min(ys))
        is_double = len(local) > 2
        w = p.door_w_double if is_double else p.door_w_single
        cxx = sum(xs) / len(xs); cyy = sum(ys) / len(ys)
        d = DOOR_PLUG_DEPTH
        off = 0.0
        if region is not None and not region.is_empty:
            l, r = _opening_span(region, cxx, cyy, horiz)
            if l is not None and r is not None and (l + r) <= 3.5:
                w = (l + r) + 0.30          # 两侧各留 15cm，确保把缝封死
                off = (r - l) / 2.0         # 洞口未必以门心对称
        if horiz:
            plugs.append(box(cxx + off - w / 2, cyy - d / 2,
                             cxx + off + w / 2, cyy + d / 2))
        else:
            plugs.append(box(cxx - d / 2, cyy + off - w / 2,
                             cxx + d / 2, cyy + off + w / 2))
    return plugs


def floor_walls(F, walls, p):
    """第 F 层墙折线（CAD 毫米，含过渡层 wall_x 过滤）→ 本地米坐标列表。"""
    wall_x = None
    tr = (p.transition or {}).get(F)
    if tr:
        wall_x = tr.get("wall_x")
    out = []
    for pts in walls:
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        _f = floor_of(p, cx, cy)
        if _f is not None and abs(_f - F) < 0.5:
            if wall_x is not None and not (wall_x[0] <= cx <= wall_x[1]):
                continue
            out.append([to_local(p, x, y, F) for x, y in pts])
    return out


def floor_rooms(F, walls, insert_doors, p, outline_override=None):
    wall_local = floor_walls(F, walls, p)
    outline, wall_geoms, _ = derive_walls_and_outline(wall_local, p)
    # outline_unify：多翼楼低层墙 union 碎片化 → 每层 max(area) 塌成小片，房间全丢。
    # 用全楼统一基准轮廓替代（与 recognize.py 同源），墙几何仍按本层算。
    if outline_override is not None:
        outline = outline_override
    if outline.is_empty:
        return []
    region = unary_union(wall_geoms) if wall_geoms else Polygon()
    if insert_doors is not None:
        # region 传进去 ⇒ 补丁按**实测洞口跨度**定宽（不然标称 1.5m 门补不满 1.74m 的洞）
        for plug in door_plugs_insert(insert_doors, F, p, region):
            region = region.union(plug)
    else:
        for d in detect_doors(wall_local, outline, p):
            region = region.union(door_box(d, DOOR_PLUG_DEPTH))
    interior = outline.difference(region)
    polys = [interior] if interior.geom_type == "Polygon" else list(interior.geoms)
    return [g for g in polys if g.area >= MIN_ROOM_AREA]


def _load_floor_json(p, F):
    """读交付楼层 JSON；不存在返回 None（由调用方决定跳过还是报错）。"""
    path = os.path.join(p.out_dir, "floor%d.json" % F)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as ex:                                # noqa: BLE001
        print("  读 %s 失败: %s" % (path, ex))
        return None


def _floors_wall_region(fl):
    """交付楼层 JSON 的墙身并集（inner + outer）—— 唯一墙源。"""
    geoms = []
    for w in fl.get("walls") or []:
        poly = w.get("poly")
        if not poly or len(poly) < 3:
            continue
        holes = [h for h in (w.get("holes") or []) if len(h) >= 4]
        try:
            q = Polygon(poly, holes) if holes else Polygon(poly)
        except Exception:                                  # noqa: BLE001
            continue
        if not q.is_valid:
            q = q.buffer(0)
        if not q.is_empty:
            geoms.append(q)
    return unary_union(geoms) if geoms else Polygon()


def floor_rooms_from_floors(fl, p):
    """单源墙：房间只读交付的 `floors/floorN.json`。

    **为什么**（2026-09-11 ny27 复盘）：同一栋楼曾有三套墙几何 —— ①`recognize()` 的粗环
    blob、②`_wall_thin_batch` 重建的交付内墙、③本模块自己又调一次的
    `derive_walls_and_outline`。③ 对「3+ 点、跨度 < 3m 的不闭合折线」直接 `continue`
    （当门符号丢），② 却保留 —— 于是每个公寓单元内部的短隔墙只存在于②。
    谁去按②修房间边界，房间就被那些隔墙切成碎块（56㎡ → 34.2+13.4+17.6，房号只落在
    一块上 → 房间反而变小）。**根治办法是让房间读②，不再自推。**

    墙、轮廓、门洞盒三样全部取自交付 JSON：与 GLB 同一份几何，门洞也天然对得上
    （挖穿墙的那几个盒子，就是这里用来隔开房间的盒子）。

    `p.room_grow_to_wall` > 0 时把房间边界贴回墙内皮：候选房间外扩该值，再裁到
    「轮廓 − 交付墙身」。只朝墙侧长、被真墙身挡住，不越过任何图纸墙线、不新增墙。
    """
    try:
        oline = OUT.floor_outline(fl)      # 多块楼层取 outline_parts 精确块，不碰钥匙孔窄桥
    except Exception:                                      # noqa: BLE001
        return [], 0, 0
    if not oline.is_valid:
        oline = oline.buffer(0)
    if oline.is_empty:
        return [], 0, 0
    walls = _floors_wall_region(fl)
    n_plug = 0
    plugs = []
    for d in fl.get("doors") or []:
        if not all(k in d for k in ("bx0", "by0", "bx1", "by1")):
            continue
        b = box(float(d["bx0"]), float(d["by0"]), float(d["bx1"]), float(d["by1"]))
        if b.is_valid and not b.is_empty:
            plugs.append(b)
            n_plug += 1
    # 定连通性用的「种子」= 墙 ∪ 门洞盒，可选再膨胀 room_seal 封接头缝。
    # 膨胀**只**用来切连通分量；下面贴边时裁的是未膨胀的 `walls`，不新增任何墙。
    seed = unary_union([walls] + plugs) if plugs else walls
    seal = float(getattr(p, "room_seal", 0.0) or 0.0)
    if seal > 0:
        seed = seed.buffer(seal)
    interior = oline.difference(seed)
    polys = [interior] if interior.geom_type == "Polygon" else list(interior.geoms)
    polys = [g for g in polys if g.area >= MIN_ROOM_AREA]
    n_cand = len(polys)
    grow = float(getattr(p, "room_grow_to_wall", 0.0) or 0.0)
    if grow > 0 and polys:
        if grow < seal:
            # 贴回量小于封缝量 → 房间比真墙内表面还小，等于没修。
            print("    [警告] room_grow_to_wall(%.2f) < room_seal(%.2f)，房间仍会被削"
                  % (grow, seal))
        allowed = oline if walls.is_empty else oline.difference(walls)
        grown = []
        for g in polys:
            q = g.buffer(grow).intersection(allowed).buffer(0)
            for sub in ([q] if q.geom_type == "Polygon"
                        else list(getattr(q, "geoms", []))):
                if sub.area >= MIN_ROOM_AREA:
                    grown.append(sub)
        polys = grown
    return polys, n_plug, n_cand


def label_in(poly, entries, F, p):
    for x, y, t in entries:
        if floor_of(p, x, y) != F:
            continue
        lx, ly = to_local(p, x, y, F)
        if poly.buffer(LABEL_TOL).covers(Point(lx, ly)):
            return t
    return None


def _label_hit(poly, x, y, F, p):
    """标注点是否落在该区域内（转本地坐标后按 LABEL_TOL 缓冲）。"""
    return poly.buffer(LABEL_TOL).covers(Point(*to_local(p, x, y, F)))


def assign_labels(polys, entries, F, p):
    """(区域, 标注) 归属，返回 {区域下标: 标注文本}。

    ① 严格包含：标注点落在区域内 → 采用。这是主判据，c029/c031 等把标注画在房间
       正中的图靠它就够（LABEL_TOL=0.1 仅抵浮点误差）。
    ② 最近兜底：**仅当 profile 开了 label_nearest_max>0** 且该区域①未命中时启用 ——
       取「距离 <= label_nearest_max」的最近**未被占用**标注，按距离升序贪心。
       一对一：一个标注至多配一个区域，否则相邻两间房会挂同一个房号。

    为什么兜底必须封顶、且默认关：ny27 的 6 个房号画在楼南墙外约 1.4m，严格包含恒败
    → 整栋 0 房间，必须兜底；而 c029 里有一个 422m 外的野标注（29-01-X），不封顶的
    最近归属会把它硬配到真房间上 —— 那是给健康楼引入新错。
    """
    out = {}
    used = set()          # 已占用的标注下标（按 entries 下标，防同文本互抢）
    for i, poly in enumerate(polys):
        for j, (x, y, t) in enumerate(entries):
            if j in used or floor_of(p, x, y) != F:
                continue
            if _label_hit(poly, x, y, F, p):
                out[i] = t
                used.add(j)
                break

    cap = float(getattr(p, "label_nearest_max", 0.0) or 0.0)
    if cap <= 0:
        return out
    cand = []
    for i, poly in enumerate(polys):
        if i in out:
            continue
        for j, (x, y, t) in enumerate(entries):
            if j in used or floor_of(p, x, y) != F:
                continue
            d = poly.distance(Point(*to_local(p, x, y, F)))
            if d <= cap:
                cand.append((d, i, j, t))
    for _d, i, j, t in sorted(cand):
        if i in out or j in used:
            continue
        out[i] = t
        used.add(j)
    return out


def assert_deliverable_text(rooms, name):
    """交付闸门：写 rooms.json 前断言字符串字段里没有控制字符 / `^X` 记法。

    **这是检查，不是判据放宽**：命中就响亮失败并列出 (id, 字段, 值)，绝不静默替换。
    为什么不能只靠 `clean()` 里那三条替换：那只覆盖"从图里读标注"这一条路；
    凡是别处拼进来、或将来新加的字段，都绕不过这道门。

    影响面已量（2026-09-13 全库扫 `data/buildings/*/rooms.json` 与 `floors/*.json` 的
    **全部字符串值**）：caret 记法 1 条（c103 的 `办公室^J（督导组）`）、裸 C0 字符 0 条。
    源头修好后本闸门应恒 0 命中；它一旦响，就是把脏值往交付里写，必须人工看清楚再放行。
    """
    bad = []
    for r in rooms:
        for k, v in r.items():
            if not isinstance(v, str):
                continue
            m = CARET_RE.search(v) or CTRL_CHAR_RE.search(v)
            if m:
                bad.append("  房间 %s 的 %s = %r（命中 %r）"
                           % (r.get("id"), k, v, m.group(0)))
    if bad:
        raise SystemExit("[%s] 交付闸门拦下 %d 条含控制字符的字符串 —— 不写盘：\n%s"
                         % (name, len(bad), "\n".join(bad[:20])))


def relabel(name, dry):
    """只重算既有 rooms.json 的 **用途/单位**，房间集合与多边形一个字都不动。

    为什么不能直接重跑 `run()` 来刷用途：实测（`--dry` 逐栋跑过）重抽会改变房间集合 ——
    c046 294→138、c103 172→60、c026 46→37、c018 179→161、c041 34→42、c027 29→53……
    而 `id` 是 `run()` 末尾按 (floor, number) 排序后**顺序编号**的（`base + i + 1`），
    房间集合一变 ID 全体错位 ⇒ floors/floorN.json 的 rooms[] 与 DB 主键同时失效。
    这 10 栋里只有 c017/c104 两栋重抽能复现同样的集合，其余八栋都不能碰。
    （某栋房间集合本身就错，那是"重识别"的活，不在本模式职责内。）

    做法：把**既有边界**当多边形喂回产品自己的 `assign_labels` —— 不另写一套匹配逻辑，
    免得出现"两套归属规则慢慢漂开"。只覆写 `purpose`/`dept`，其余字段逐字保留，
    写盘走 tmp+os.replace（直写 json.dump 会把交付文件截成 0 字节）。

    用法：python backend/extract/extract_rooms_generic.py c104 --relabel [--dry]
    """
    p = load_profile(name)
    if not os.path.exists(p.rooms):
        print("[%s] 没有 rooms.json，--relabel 无从下手（那是 run() 的活）" % name)
        return None
    with open(p.rooms, encoding="utf-8") as f:
        rooms = json.load(f)
    if not rooms:
        print("[%s] rooms.json 是空的 —— 请先跑 run()" % name)
        return None

    msp = ezdxf.readfile(p.dxf, encoding=ENCODING).modelspace()
    role_map = layer_role_map(msp)
    role_map.update(LAYER_ROLE_OVERRIDE.get(name, {}))
    labels = read_labels(msp, role_map, PURPOSE_DROP_AREA_LIKE.get(name))
    print("[%s] 标注：用途 %d 条、单位 %d 条（role_map=%s）"
          % (name, len(labels["purpose"]), len(labels["dept"]),
             json.dumps({k: v for k, v in sorted(role_map.items())}, ensure_ascii=False)))

    # 身份指纹：写盘前后必须完全相同（本模式唯一的硬不变量）。
    ident = [(r.get("id"), r.get("floor"), r.get("number")) for r in rooms]

    n_pur = n_dep = 0
    samples = []
    for F in sorted({r.get("floor") for r in rooms}):
        idx = [i for i, r in enumerate(rooms) if r.get("floor") == F]
        polys = [Polygon(rooms[i]["boundary"]).buffer(0) for i in idx]
        purpos = assign_labels(polys, labels["purpose"], F, p)
        depts = assign_labels(polys, labels["dept"], F, p)
        for gi, i in enumerate(idx):
            old_p, new_p = rooms[i].get("purpose"), purpos.get(gi)
            old_d, new_d = rooms[i].get("dept"), depts.get(gi)
            if old_p != new_p:
                n_pur += 1
                if len(samples) < 8:
                    samples.append("F%d %s: %r → %r"
                                   % (F, rooms[i].get("number"), old_p, new_p))
            if old_d != new_d:
                n_dep += 1
            rooms[i]["purpose"] = new_p
            rooms[i]["dept"] = new_d
        print("  第%d层 %d 间：用途命中 %d，单位命中 %d"
              % (F, len(idx), len(purpos), len(depts)))

    after = [(r.get("id"), r.get("floor"), r.get("number")) for r in rooms]
    if after != ident:
        raise SystemExit("[%s] 身份指纹变了 —— 中止，不写盘" % name)
    print("[%s] 房间 %d 间、id/floor/number 指纹不变 ✓；用途改 %d 处、单位改 %d 处"
          % (name, len(rooms), n_pur, n_dep))
    for s in samples:
        print("      %s" % s)

    # 闸门放在 `if dry` **之前**：dry 必须真的走一遍写盘那条路（铁律⑯），
    # 否则"dry 过了、真写被拦"这种落差要等真写才发现。
    assert_deliverable_text(rooms, name)
    if dry:
        print("  （--dry，未写盘）")
        return rooms
    tmp = p.rooms + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rooms, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p.rooms)
    print("  已写 %s" % p.rooms)
    return rooms


def run(name, dry):
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf, encoding=ENCODING)
    msp = doc.modelspace()

    is_line = getattr(p, "classifier", "lwpolyline") == "line"
    if is_line:
        from recognizer.classify_line import classify_line
        walls, insert_doors, _, _ = classify_line(msp, p)
    else:
        from recognizer.classify import classify
        walls, _, _, _ = classify(msp, p)
        insert_doors = None

    # 层名语义解析（标记词优先，覆盖 7↔8 颠倒/双 8 层/8.2 变体）；旧按数字前缀的口径仍作
    # 兜底（老楼 5/6/7/8 布局）。LAYER_ROLE_OVERRIDE 保留手工纠正位；
    # PURPOSE_DROP_AREA_LIKE 是「同一层里混装用途与面积串」的具名口子（见该表上方注释）。
    role_map = layer_role_map(msp)
    role_map.update(LAYER_ROLE_OVERRIDE.get(name, {}))
    labels = read_labels(msp, role_map, PURPOSE_DROP_AREA_LIKE.get(name))

    floors = sorted({floor_of(p, sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))
                     for pts in walls})

    ref_F, reference_outline = reference_outline_for(p, walls, floors)
    unify_set = unify_floor_set(p, floors)

    rooms = []
    n_fixed = 0                      # 自交房间边界被自愈的条数（交付前修形，见下）
    n_dropped = 0                    # 自愈也救不回来、只好丢弃的条数（会打印出来）
    floor_polys = {}   # F -> [房间多边形]（含无房号者，供歧义诊断）
    # 单源墙（profile.rooms_from_floors）：房间读交付的 floors/floorN.json。
    # ⚠️ 顺序铁律：必须排在内墙重建（_wall_thin_batch）之后，否则读到的是粗环 blob。
    # 通路分派（见 extract/room_route.py）：老写法 rooms_from_floors 仍认，
    # 新写法 room_route 支持 "auto"（逐层按图择优）/"single"/"regen"。
    # 两者都没有 ⇒ 走主线，行为与加本功能之前**逐字节相同**（老楼零影响）。
    route = str(getattr(p, "room_route", "") or "").strip().lower()
    auto = route == "auto"
    single_src = bool(getattr(p, "rooms_from_floors", False)) or route == "single"
    if auto:
        print("[%s] 自动分派：逐层在「主线=现推墙」与「支线=读交付墙」之间择优"
              "（判据=图上房号命中数）" % name)
    elif single_src:
        print("[%s] 单源墙：房间的墙/轮廓/门洞盒读自 %s（不再自推墙几何）" % (name, p.out_dir))
    # 自动分派的裁判是图纸自己的房号；只在这条路上算，老楼一分开销都不加。
    truth_F = RR.truth_by_floor(labels["number"], floor_of, p) if auto else {}
    for F in floors:
        override = outline_for_floor(p, ref_F, reference_outline, F) if F in unify_set else None
        fl = _load_floor_json(p, F) if (single_src or auto) else None
        if single_src and fl is None:
            print("  第%d层 缺 floors/floor%d.json —— 跳过（单源墙要求先跑完内墙重建）"
                  % (F, F))
            floor_polys[F] = []
            continue
        if auto:
            cands = {RR.ROUTE_REGEN: floor_rooms(F, walls, insert_doors, p,
                                                 outline_override=override)}
            if fl is None:
                print("  第%d层 缺 floors/floor%d.json —— 自动分派只剩主线" % (F, F))
            else:
                cands[RR.ROUTE_SINGLE] = floor_rooms_from_floors(fl, p)[0]
            try:
                oline = OUT.floor_outline(fl) if fl is not None else None
                o_area = 0.0 if (oline is None or oline.is_empty) else float(oline.area)
            except Exception:                                   # noqa: BLE001
                o_area = 0.0
            scored = {rn: (pl, assign_labels(pl, labels["number"], F, p))
                      for rn, pl in cands.items()}
            best, table = RR.pick(scored, truth_F.get(F, set()), o_area)
            polys = best["polys"]
            print("  第%d层 自动分派 %s" % (F, RR.why(best, table, len(truth_F.get(F, ())))))
        elif single_src:
            polys, n_plug, n_cand = floor_rooms_from_floors(fl, p)
            print("  第%d层 单源墙：墙 %d 段、门洞盒 %d 个、封缝 %.2f、"
                  "候选 %d → 贴边后 %d 个"
                  % (F, len(fl.get("walls") or []), n_plug,
                     float(getattr(p, "room_seal", 0.0) or 0.0), n_cand, len(polys)))
        else:
            polys = floor_rooms(F, walls, insert_doors, p, outline_override=override)
        floor_polys[F] = polys
        # 四个角色一次算齐：房号（决定这间房存不存在）+ 面积/用途/单位（属性）。
        # 同一个归属规则，免得出现「房号兜底到了、面积却没跟上」的半残状态。
        nums = assign_labels(polys, labels["number"], F, p)
        areas = assign_labels(polys, labels["area"], F, p)
        purpos = assign_labels(polys, labels["purpose"], F, p)
        depts = assign_labels(polys, labels["dept"], F, p)
        for gi, g in enumerate(polys):
            number = nums.get(gi)
            if not number:
                continue
            # ★ 交付前**修形**：房间边界可能自交，GEOS 一到下游（SU 规格的包含判定）
            #   就抛 TopologyException —— 实测 c041「41-01-05」、c104「104-C-02-02」。
            #   两个来源都要管：①图纸本身就是自触多边形；②**我们写盘时 round(…, 2)**
            #   把 900+ 个近重合顶点压成同一点，几何被自己改坏（c041 实测：
            #   源多边形 is_valid=True，落盘后 987 点 → is_valid=False）。
            #   修法：先按 2 位小数落盘，**以落盘结果为准**再验一次；不合法就 buffer(0)
            #   自愈（多块取最大块），仍不合法就把小数位放宽到 3、4 位；都不行才丢这一间
            #   （并计数上报，绝不静默）。
            bnd = [[round(x, 2), round(y, 2)] for x, y in g.exterior.coords]
            for prec in (2, 3, 4):
                bnd = [[round(x, prec), round(y, prec)] for x, y in g.exterior.coords]
                try:
                    q = Polygon(bnd)
                except Exception:                                  # noqa: BLE001
                    continue
                if q.is_valid and q.exterior.is_simple:
                    break
                fixed = q.buffer(0)
                if fixed.geom_type == "MultiPolygon":
                    fixed = max(fixed.geoms, key=lambda z: z.area)
                if fixed.is_empty or fixed.geom_type != "Polygon":
                    continue
                g = fixed
                n_fixed += 1
            else:
                n_dropped += 1
                continue
            cx, cy = g.centroid.x, g.centroid.y
            rooms.append({
                "building": name,
                "floor": F,
                "number": number,
                "name": None,
                "area": areas.get(gi),
                "area_m2": round(g.area, 2),
                "purpose": purpos.get(gi),
                "dept": depts.get(gi),
                "centroid": [round(cx, 2), round(cy, 2)],
                "boundary": bnd,
            })

    # 歧义诊断（不写文件，只打印）：标注点被 ≥2 个房间覆盖会误配房号，应恒为 0。
    # 房间吃多标注 = 一个房间覆盖多个不同房号，多为内墙缺失致房间合并（几何问题，非标注问题）。
    buffered = {F: [g.buffer(LABEL_TOL) for g in polys] for F, polys in floor_polys.items()}
    ambig = 0
    for F in floors:
        for (x, y, t) in labels["number"]:
            if floor_of(p, x, y) != F:
                continue
            lx, ly = to_local(p, x, y, F)
            if sum(1 for g in buffered[F] if g.covers(Point(lx, ly))) > 1:
                ambig += 1
    room_eat = 0
    for F, polys in floor_polys.items():
        for gi, g in enumerate(polys):
            hits = set()
            for (x, y, t) in labels["number"]:
                if floor_of(p, x, y) != F:
                    continue
                lx, ly = to_local(p, x, y, F)
                if buffered[F][gi].covers(Point(lx, ly)):
                    hits.add(t)
            if len(hits) > 1:
                room_eat += 1
    if ambig or room_eat:
        print(f"  [歧义] 标注命中多房间={ambig} 房间吃多标注={room_eat}")

    rooms.sort(key=lambda r: (r["floor"], r["number"]))
    base = ID_BASE.get(name, 1000000)
    for i, r in enumerate(rooms):
        r["id"] = base + i + 1

    print(f"[{name}] 共提取 {len(rooms)} 间房（有房号）")
    if n_fixed:
        print(f"  [修形] 自交/坏形房间边界自愈 {n_fixed} 次（buffer(0)，多块取最大块）")
    if n_dropped:
        print(f"  [修形] 自愈失败、已丢弃 {n_dropped} 间（房号保留在图上，几何不入库）")
    per = {}
    for r in rooms:
        per[r["floor"]] = per.get(r["floor"], 0) + 1
    for F in sorted(per):
        print(f"  第{F}层 {per[F]} 间")

    # 交付闸门：dry 也要走一遍（铁律⑯），否则"dry 过了、真写才被拦"的落差要等真写才暴露。
    if rooms:
        assert_deliverable_text(rooms, name)
    if not dry and rooms:
        os.makedirs(os.path.dirname(p.rooms), exist_ok=True)
        # 原子写（[[atomic-artifact-write]]）：rooms.json 是**交付件**，直写时中途挂掉
        # 会把它截成 0 字节，而下游 floors/GLB/SU 全部读它。本文件里 --relabel 那条
        # 分支一直是 tmp+os.replace，只有这里漏了 —— 两处必须同口径。
        tmp = p.rooms + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rooms, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p.rooms)
        print(f"已写 {p.rooms}")
    return rooms


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    relabel_mode = "--relabel" in sys.argv
    if "--all" in sys.argv:
        names = sorted(ID_BASE)
    else:
        names = argv or list(ID_BASE)
    for name in names:
        if name not in ID_BASE:
            print(f"未知建筑 {name}（跳过），可用：{sorted(ID_BASE)}")
            continue
        if relabel_mode:
            relabel(name, dry)
        else:
            run(name, dry)
        print()


if __name__ == "__main__":
    main()
