# -*- coding: utf-8 -*-
# SU 无人值守 · 第二步：**判断好之后再进 SU** —— 把 export_contours.py 出的闭合轮廓
# 变成面、按层高拉伸，SU 自己出正式件的三维。
#
# 跑法（必须给一个「已存在的文档」参数，否则欢迎屏挡启动 —— 见 README.md §5）：
#   "C:\Program Files\SketchUp\SketchUp 2023\SketchUp.exe" "D:\项目\cdut3d\rebuild\06_su\c006_su_1f.skp" ^
#       -RubyStartup "D:\项目\cdut3d\rebuild\06_su\su_step2_build.rb"
#   ★ 启动前先杀掉所有 SketchUp 并**无条件等 ≥5 s**（单实例会静默接手：脚本一行不跑、零报错）。
#
# 为什么要绕这一道：底图是双线墙，SU 导进去只是照画两根线，围不成环 ⇒ 不成面 ⇒
# 导 OBJ 是 147 字节空件（实测）。**判断（哪两根线是一堵墙）在本仓做完**，
# 这里拿到的已经是闭合环，SU 只需要「成面 + 拉伸」这一件它擅长的事。
#
# 单位：JSON 里是 **mm**，SU 的 Ruby API 裸数字是 **英寸** ⇒ 一律 .mm 换算。
#
# ★★ 2026-10-14 重做（本轮交付件缺陷的根因，已修）：**洞现在在 Python 侧就切掉了**
#    （`export_contours.py::_cut_holes`）。为什么挪走 —— SU 的三条抠洞路**全实测、全不通**：
#      · `add_face(外环, 洞1, 洞2…)` 多环 ⇒ 抛 `Not enough edges` / `wrong number of values`；
#      · `add_edges(洞环, true)` ⇒ 抛 `ArgumentError`（旧代码靠 rescue 回落到不带 weld 那次）；
#      · `add_face(外环)` **不会**把已存在的闭合洞边当洞抠掉（3 轮实测：先画洞边再成面 =
#        实心 4.00 m²；先成面再 add_edges(洞环) 也不劈面）。
#      · 旧注释「SU 成面时会自动把内部已有的闭合边当洞抠掉」**是错的**，已删。
#    实测凭据（`_scratch/_wall_compare.py`）：包内件逐层逐类足迹**逐位等于 gross** ——
#      1层 WALL gross 5762.8 / net 5652.5 / 包内 5762.8；3层 LIFT 5.9 / 2.3 / 5.9；
#      3层 COL 无洞 69.0 / 69.0 / 69.0（**COL 是唯一无洞的类，也唯一本来就对**，正是反证）。
#      ★ 旧版的 `holes_cut=147` 数的是 `add_edges` 成功次数、**不是抠成的洞** ——
#        判词必须声明量具对什么盲（铁律 158），那个计数已不再出现、也不再当判据。
#
# 自检（都写进 build_log.txt，不猜）：
#   1. FACE_FAIL —— 成不了面/拉不出的条数；多了就是这次白跑
#   2. BBOX_mm —— 建完量总包围盒（mm）；单位错会量出 129300 × 25.4 倍
#   3. 逐层逐类面数 —— 与 contours/index.json 的条数对账（对不上就是漏建）

require 'json'

DIR   = "D:/项目/cdut3d/rebuild/06_su"
CONT  = "#{DIR}/contours"
LOG   = "#{DIR}/build_log.txt"
# ★★ 2026-10-15：`ALL_FLOORS` **不再写死**（原来是 `(i-1)*4.0`）。层高是**口径决定**
#   （真源 = `rebuild/构件库/参数.json::构件.共用/层高`），用户 2026-10-15 把它从 4.0 改成 3.5。
#   写死在这里的后果不是「慢」，是**静默**：contours 里的环是 3.5 m 一条条出的，
#   而本行还按 4.0 摆层 ⇒ 每层错 0.5·k 米、顶层错 5 m，SU 照样建、面数照样对得上，
#   没有任何一条判据看得出来（铁律 018/174：两个估计器）。
#   改成**从 contours/index.json 现读**（那正是本脚本要吃的那份数据，`floor`/`z0_m`/`h_m`）——
#   件与它自己的输入从此是同一个口径，不可能再漂。
IDX = "#{CONT}/index.json"
ALL_FLOORS =
  if File.exist?(IDX)
    JSON.parse(File.read(IDX)).map { |r| [r["floor"], r["z0_m"].to_f, r["h_m"].to_f] }
  else
    # 读不到就**明说**并停：绝不用一个猜的层高把件建歪（「没量到」≠「按默认建」）
    raise "缺 #{IDX} —— 先跑 rebuild/tools/export_contours.py；本脚本不在没有 contours 的情况下猜层高"
  end

# ★★ 分批建（2026-10-13 实测：**一个操作里**一次塞 8570 张面 ⇒ SU 中途异常终止 rc=127，
#    两次死在**不同位置** ⇒ 不是某条多边形有毒，是规模性问题）。
#    这里改成：**每个 (批, 层) 一个 `start_operation`/`commit_operation`**，
#    原子操作最大只有一层的量（1层 1035 条），并在每批之间存一次盘。
# ★★★ 2026-10-14 **门批挪到第一个**（缓解，不是定论）：墙修好之后（1层 WALL 78 → 96，
#    批1 存档 3,942,015 → 4,318,494 字节）门批**连挂两趟**，两趟都停在同一形状的
#    `??层_DOOR 60/3xx` 处：CPU 满转、窗口不响应（cpu_delta_6s=6.44 / resp=False /
#    ws=643.6MB）—— 是**在算**，不是死锁，也不是脚本异常（异常日志会停但 CPU 会掉）。
#    而门**本身一字未改**：2层 312/312、4层 304/304 环与上一趟成功件逐字节相同，
#    z 集合、键集合、push_mm 全同 ⇒ 变量只有一个：**建门时文档里已经躺着四千多张墙面**。
#    所以把门放到文档还空的时候建。★ 同层同类各占一个组 ⇒ **批次次序不改变成品形状**，
#    只改变建门时文档里有几张面。真因尚未量到，故下面门批另留逐块点名日志。
BATCHES = [
  ["批1 门",                          %w[DOOR]],
  # ★ 2026-10-15 加 `LINTEL`（门头墙）：它与门**同层、同在门洞正上方**，但自成一组，
  #   批次次序不改变成品形状（同层同类各占一个组）。放批2 是因为它跟
  #   「墙/柱/井/板」一样是**通层高的主体件**，且量小（逐层与门扇同量级）。
  # ★ 2026-10-15 同日再加 `ROOF`（塔楼屋面板，第 11 类，用户「楼板要画」）。
  #   ★★ 这张表是**硬编码的类名表**：`contours` 里发了、这里没列 ⇒ **静默不建**、
  #      面数照样「正常」、rc=0（铁律 158：判词不声明量具对什么盲就是恒绿）。
  #      只 11 层有它（其余 11 层的 JSON 里 `ROOF` 恒 0 条，循环直接跳过）。
  ["批2 主体(墙/柱/井/板/门头墙 + 顶部四件)",
   %w[WALL COL LIFT SLAB LINTEL PARAPET ROOF_STAIR ROOF_STEP ROOF]],
  ["批3 梯",                          %w[STAIR]]
]

def say(s)
  # ★ 每行都带 pid：日志**不在开头 File.delete**（删了就看不出有几个进程/几趟在写）
  File.open(LOG, "a") { |f| f.puts("[#{Process.pid}] #{s}") }
end

say "SCRIPT_ENTERED ruby=#{RUBY_VERSION} at=#{Time.now.strftime('%H:%M:%S')}"

SU = if defined?(SketchUp) then SketchUp
     elsif defined?(Sketchup) then Sketchup
     end
say "SU=#{SU.inspect}"

def pts(ring, zmm)
  ring.map { |x, y| Geom::Point3d.new(x.to_f.mm, y.to_f.mm, zmm.mm) }
end

# ★★ 2026-10-14：**成面之前先洗环**。contours 里的 ring 是 shapely 的闭合坐标串，
#    首点被原样又写了一遍（`[[x,y],…,[x,y]]`）—— 直接喂 `add_face` 会造一条**零长边**，
#    SU 在 pushpull 对零长边做愈合时会**自旋**（实测：6层 DOOR 第 6 个组把 SU 转死、
#    CPU 持续 ~93%、窗口无响应、日志停在那一行；5层 DOOR 数据形状与之几乎相同却过了 ⇒
#    不是数据独有，是零长边 + 规模凑巧）。同一环里的连续重复点一并去掉。
def clean_ring(ring)
  rr = []
  ring.each do |p|
    next if !rr.empty? && rr.last == p
    rr << p
  end
  rr.pop while rr.length > 1 && rr.first == rr.last
  rr
end

# 一个闭合环 → 一张面。**这里不再有洞**（洞已在 Python 侧切掉）——
# 旧版那段「先 add_edges(洞环) 再 add_face」既不抠洞、还白建一堆孤边，已删。
def face_of(ge, ring, zmm, c)
  rr = clean_ring(ring)
  if rr.length < 3
    c[:fail] += 1
    c[:degen] += 1
    return nil
  end
  f = begin
    ge.add_face(pts(rr, zmm))
  rescue StandardError
    nil
  end
  f = f.max_by(&:area) if f.is_a?(Array)
  unless f.is_a?(Sketchup::Face)
    c[:fail] += 1
    return nil
  end
  f
end
