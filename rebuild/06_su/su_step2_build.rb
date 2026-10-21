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

# ★ 2026-10-17：目录与出件名随楼栋走（c006 默认值一字不动）。
#   **不走环境变量**：本机 Ruby 把 ENV 读成 GBK，路径里又带中文「项目」⇒
#   ① 直接插值 `Encoding::CompatibilityError: GBK and UTF-8`（实测把整趟打崩、SU 弹框挂 600 s）；
#   ② 强行转码又可能解成乱码 ⇒ `contours/index.json` 找不到、连 SCRIPT_ENTERED 都打不出来。
#   ⇒ 改由 `_run_su_step2.ps1` 在**本文件旁边**写 `_su_target.txt`（UTF-8 两行：目录 / 名前缀），
#     这里按 `__FILE__` 的位置读它。没有这份文件 ⇒ 退回 c006 默认值。
_HERE = File.dirname(File.expand_path(__FILE__))
_TG   = File.join(_HERE, "_su_target.txt")
DIR   = "D:/项目/cdut3d/rebuild/06_su"
NAME  = "c006"
if File.exist?(_TG)
  _ls = File.readlines(_TG, encoding: "UTF-8").map { |l| l.sub(/^\uFEFF/, "").strip }
  DIR  = _ls[0] unless _ls[0].to_s.empty?
  NAME = _ls[1] unless _ls[1].to_s.empty?
end
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
  # ★★ 2026-10-19 加 `ROOF_ROOM`（出屋面楼梯间+电梯机房，`export_contours.py` 2026-10-18
  #   起就在发）。这张表漏了它 ⇒ **静默不建**、面数照样「正常」、rc=0 ——
  #   `gates/J-10.9-07` ③ 的「每一类都要到件」正是为这件事设的。
  ["批2 主体(墙/柱/井/板/门头墙 + 顶部五件)",
   %w[WALL COL LIFT SLAB LINTEL PARAPET ROOF_STAIR ROOF_STEP ROOF ROOF_ROOM]],
  ["批3 梯",                          %w[STAIR]]
]

# ★★ 2026-10-17：**除 COL 外一律块级隔离**。
#   第一版只隔离「成链」的类（WALL/STAIR/SLAB/PARAPET/ROOF*），把 DOOR 留在共用组里
#   ⇒ c006 实测开口边从 6 反弹到 **132**，且 132 条**全在 G_*__DOOR**（12 层门洞互相吃面）。
#   ⇒ 判据不是「这个类像不像链」，而是「这个类里有没有相邻共面的块」；实测只有 COL
#   不能拆：`gates/J-10.8-02` ⑤⑪ 拿**每层 COL 组数**当分母（柱块数），
#   改成每块一组会把分母换成多边形数，闸立刻 22 条红（实测）。
#   所以：**COL 保持每层一组，其余全部每块一组**（白名单反转成排除名单，
#   将来新增的类默认隔离 —— 默认安全的那个方向）。
ISOLATE_EXCEPT = %w[COL].freeze

def isolated?(lay)
  !ISOLATE_EXCEPT.include?(lay)
end

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

def guarded(su)
  raise "no API module" if su.nil?
  model = su.active_model
  raise "no model" if model.nil?
  model.options["UnitsOptions"]["LengthUnit"] = 2   # 2=毫米（只管显示）

  # ★ 每次都是**重来**（洞的修法变了 ⇒ 旧件里的实心墙必须全部丢掉，不能续跑）
  model.start_operation("c006_clear", true)
  model.entities.erase_entities(model.entities.to_a)
  model.commit_operation
  say "CLEARED entities=#{model.entities.length}"

  c = { face: 0, fail: 0, skip: 0, degen: 0 }
  skp = "#{DIR}/#{NAME}_su.skp"
  t_all = Time.now

  BATCHES.each_with_index do |(bname, layers), bi|
    say "BATCH #{bi + 1}/#{BATCHES.length} #{bname} layers=#{layers.join(',')}"
    ALL_FLOORS.each do |name, z0, _h|
      jp = "#{CONT}/#{name}.json"
      unless File.exist?(jp)
        say "  MISSING #{jp}"
        c[:skip] += 1
        next
      end
      d = JSON.parse(File.read(jp))
      push = d["push_mm"]
      zbase = z0 * 1000.0
      by = Hash.new(0)
      n0 = c[:face]
      t0 = Time.now
      model.start_operation("c006_#{bi}_#{name}", true)
      d["polys"].group_by { |p| p["layer"] }.each do |lay, arr|
        next unless layers.include?(lay)
        key = "#{name}_#{lay}"
        # ★ 组名会被 SU 剥掉非 ASCII ⇒ 楼上成 `G_5__WALL`、地下室成 `__1__WALL`
        #   （`su_obj_to_glb.py` 的两条正则就是按这个反推的）。
        # ★★ 2026-10-17 起是**每块一个组**（见下），不再是「每层每类一个组」。
        say format("    > %s n=%d z=%.1f", key, arr.length, zbase + arr[0]["z"].to_f)
        # 非隔离类（COL/LIFT/LINTEL/DOOR）共用一个组，先建出来
        g_cls = nil
        unless isolated?(lay)
          g_cls = model.entities.add_group
          g_cls.name = key
        end
        arr.each_with_index do |pr, i|
          # ★ 每 20 块打一行：SU 万一把自己转死，日志能指到**哪一块**（不猜）
          if (i % 20).zero?
            say format("      .. %s %d/%d faces=%d", key, i, arr.length, c[:face])
          end
          # ★★ 门**逐块点名**：每 20 块一行只指得到「60~79 之间」，指不到人。
          #    日志最后一行就是转死时正在处理的那一块：`add` = 还没成面，`push` = 面成了、正拉伸。
          say format("        > add  %s", pr["id"]) if lay == "DOOR"
          next if pr["ring"].length < 3
          # ★★ 2026-10-17 块级隔离（用户拍板「全面改并重算两栋」）：
          #    同一组里**相邻共面的底块**在建面/拉伸时会互相吃面 —— c005 实测 575 条开口边
          #    全落在块底面，且孤立类（COL/LIFT/LINTEL）为 0、成链的类（WALL/STAIR/SLAB/
          #    PARAPET）才有。成链的类每块单独成组 ⇒ 组内只有一张面，没有别的块可吃。
          #    **孤立类不动**（它们本来就闭合，而且 COL 的组数是 J-10.8-02 ⑤⑪ 的分母）。
          #    组名仍用同一个 key：SU 的 OBJ 导出本来就按网格拆成多条 `g` 行
          #    （实测一个组导出 Mesh1..Mesh5 五行同名），`su_obj_to_glb.py` 按名归并
          #    ⇒ 下游 (层,类) 节点结构一字不变。
          if isolated?(lay)
            g = model.entities.add_group
            g.name = key
            ge = g.entities
          else
            g = nil
            ge = g_cls.entities
          end
          f = face_of(ge, pr["ring"], zbase + pr["z"].to_f, c)
          if f.nil?
            g.erase! if g && g.valid?
            next
          end
          say format("        > push %s", pr["id"]) if lay == "DOOR"
          # ★ 逐块的拉伸高度优先（2026-10-14「楼梯直接建模块替换」）：楼梯每一级要
          #   从自己的底标高**长到自己那一级**，若还按「一层的 STAIR 一个常数 50 mm」拉，
          #   就仍是薄板而不是踏步。其余各类**不带 `h`** ⇒ 一字未变，退回按层常数。
          hh = (pr["h"] || push[lay]).to_f
          amt = (f.normal.z >= 0 ? hh : -hh).mm
          begin
            f.pushpull(amt)
            c[:face] += 1
            by[lay] += 1
          rescue StandardError
            c[:fail] += 1
          end
        end
        say format("      . %s 完 faces=%d", key, c[:face])
      end
      model.commit_operation
      say format("  %-8s 面 %4d 用时 %.1fs 逐类=%s", name, c[:face] - n0,
                 Time.now - t0, by.sort.map { |k, v| "#{k}:#{v}" }.join(" "))
    end
    # ★ 每批存一次：万一后面某批把 SU 弄崩了，前面几批不用重跑
    model.save(skp)
    say "SAVED 批#{bi + 1} #{skp} bytes=#{File.exist?(skp) ? File.size(skp) : 0}"
  end

  bb = model.bounds
  say format("BBOX_mm size=[%.1f, %.1f, %.1f] min=[%.1f, %.1f, %.1f]",
             bb.width.to_mm, bb.height.to_mm, bb.depth.to_mm,
             bb.min.x.to_mm, bb.min.y.to_mm, bb.min.z.to_mm)
  say "FACES built=#{c[:face]} fail=#{c[:fail]} 退化环=#{c[:degen]} floor_skipped=#{c[:skip]} " \
      "用时=#{(Time.now - t_all).round(1)}s 组=#{model.entities.grep(Sketchup::Group).length}"

  say "COMMITTED entities=#{model.entities.length}"

  model.save(skp)
  say "SAVED #{skp} bytes=#{File.exist?(skp) ? File.size(skp) : 0}"
  # ★ 2026-10-15：**不再导 `.dae`**（原为 `[["obj", …], ["dae", …]]` 两条）。
  #   依据：实测**全仓无人读 `.dae`** —— `grep -rn "\.dae"` 的命中只剩
  #   `daemon_threads` 这类假命中（`gates/J-09.1.1-viewer.py:267`、`_scratch/probe_*.py`）
  #   与一句注释（`gates/J-10.8-02_su.py:562`）；包的真源是 `.obj`，
  #   glb 由 `rebuild/tools/su_obj_to_glb.py` 从 obj 转（`demo/build_pack.py:137,185`）。
  #   代价（铁律 28：处置是个决定）：**32.5 MB/趟 的写盘省了，但哪天要用 DAE 交换格式，
  #   得把这一行加回来** —— 这份代价就是「不再有现成 .dae」。
  [["obj", "#{DIR}/#{NAME}_su.obj"]].each do |tag, p|
    ok = begin
      model.export(p)
    rescue StandardError => e
      say "EXPORT_RAISED #{tag} #{e.class}: #{e.message}"
      false
    end
    say "EXPORT #{tag} ok=#{ok.inspect} bytes=#{File.exist?(p) ? File.size(p) : 0}"
  end
  say "DONE"
rescue StandardError => e
  say "FATAL #{e.class}: #{e.message}"
  say((e.backtrace || []).first(8).join(" | "))
  # ★ 2026-10-17：崩了**必须自己退**。上一版只在成功路径排了退出，实测崩溃后 SU 窗口
  #   干挂满 600 s 才被 ps1 掐掉（`timeout-killed`），下一趟又被单实例挡住。
  UI.start_timer(3.0, false) { SU.quit rescue nil }
end

# ★★ 2026-10-13 实测：原先写 `UI.start_timer(5.0, false)` 期望「只跑一次」，实际**重复触发** ——
#    一个进程里 guarded() 连跑 4~7 遍，内存涨到 1.26 GB、存盘存了两次、导出的 obj 是 0 字节。
#    ⇒ 不去猜这个 API 的语义，直接**让重入不可能**：一个标志位，进过就不许再进。
$guarded_runs = 0
UI.start_timer(5.0, false) do
  $guarded_runs += 1
  if $guarded_runs == 1
    guarded(SU)
    UI.start_timer(3.0, false) do
      SU.quit rescue nil
    end
  else
    say "REENTRY_BLOCKED run=#{$guarded_runs} ★ 计时器在重复触发"
  end
end
say "TIMER_ARMED"
