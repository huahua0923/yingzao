# _scratch —— 归档区

**还原入口（读全部 4 份清单）**：`python _scratch/_unarchive.py --apply`（默认干跑）
**当前归档：340 项**，全部哈希入清单，可逆。

## 为什么归档

根目录只留**管线/生产/门禁/回归资产**。其余都是跑过一次、结论已固化进数据或记忆的
一次性产物。它们仍然**有用**——出问题时是最快的取证入口——所以**只归档不删除**。

## 四批归档

| 批次 | 清单 | 项数 | 内容 |
|---|---|---|---|
| ① | `_MANIFEST.json` | 107 | 根目录一次性 `.py`（探针/补丁/单栋修复/建档期工具） |
| ② | `_MANIFEST_DEBRIS.json` | 44+6 | 根目录运行噪音（日志/探针输出/调试图/代码备份）+ blender 一次性诊断 |
| ③ | `_MANIFEST_DEBRIS2.json` | 40 | `data/`、`backend/` 的调试碎片与临时目录 |
| ④ | `_MANIFEST_DEBRIS3.json` | 143 | 历史遗留整目录与死代码（见下 `legacy/`） |

## 目录导航

### ① 根脚本分组（107）

- **probe/** 探针（只读诊断，37）
- **patch/** 补丁与试点（已应用，10）· **bybuilding/** 单栋专项修复（9）
- **onetime/** 一次性数据修复（8）· **census/** 普查与审计（只读，11）
- **render/** 被取代的渲染（5）· **profiling/** 建档期工具（13）· 其他（14）

### ② / ③ 运行噪音与碎片

- `logs/` `probe-out/`（含 `root/` `data/` `backend/` `blender/`）`backups/` `tmp/`
  按**来源**分目录，避免同名碰撞
- ⚠️ 明确**不碰** `data/buildings/*/.orig` —— 那是数据回滚备份，不是噪音

### ④ `legacy/` 历史遗留

| 归档项 | 原位置 | 为什么 |
|---|---|---|
| `legacy/archive/` | `archive/` | 自述「不再维护」的早期脚本/页面/截图 |
| `legacy/render_c103/` `legacy/_al_check/` | 同左 | 一次性对齐校验渲染 |
| `legacy/extract/` | `backend/extract/` | 旧提取管道（已被 recognizer + `extract_rooms_generic` 取代） |
| `legacy/modeling/` | `backend/modeling/` | 理化楼/六教时代一次性建模器 |
| `legacy/data/` | `data/` | 理化楼时代 GLB/几何/路径产物 |
| `PLAN.md` `spec.json` | 根目录 | 过期文档 / 死配置（活的是 `data/spec.json`） |

> `backend/extract/` 与 `backend/modeling/` 里**存活**的文件留在原地未动：
> `extract_rooms_generic.py`、`extract_rooms_c006.py`、`backfill_floor_rooms.py`、
> `build_standard_glb.py`、`glb_common.py`。

## 归档前的安全闸（三闸）

归档脚本在移动前会跑：

1. **真实 import 检查** —— 待归档 `.py` 被 `backend/` 或根保留脚本真实 `import` 的不动
2. **按名引用检查** —— `.glb/.json/.html` 被存活代码引用的不动
   （存活源 = `frontend/*.html` + `backend/{web,db,recognizer,nav}/` + 保留的根脚本；
   **legacy 建模器不算存活源**，它们自己就是被归档对象）
3. **明确不碰** —— `data/buildings/`、`data/{floors,rooms.json,spec.json,adjacency.json,j6-walls.glb}`、
   `data/lihua-building.glb`（理化楼注册表分支的活产物）、`_qa/`（体检基线）、`blender/render_views.py`

闸门实际拦下并保留的例子：`data/_verify_floors`（被 `backend/verify_recognizer.py` 读）、
`_tmp_c019_door`（被 `_run_c019_tmp.py` 用）。

## 相关脚本

| 脚本 | 用途 |
|---|---|
| `_unarchive.py` | ★ 一键还原（读全部 `_MANIFEST*.json`） |
| `_archive_root.py` | 第①批：根 `.py` 分类归档 |
| `_archive_debris.py` | 第②批：根噪音 |
| `_archive_debris2.py` | 第③批：data/backend 碎片 |
| `_archive_debris3.py` | 第④批：历史遗留 |
| `_reconcile_legacy.py` | 对账：把崩溃中断时已移走但漏记清单的文件补回清单 |
