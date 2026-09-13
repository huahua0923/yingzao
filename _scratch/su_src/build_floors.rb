# -*- coding: utf-8 -*-
# 理化楼：在 SU 里**分层**盖出来 + 每间房一条用途注释。
#
# 与 `build_model.rb` 同源：读同一套 spec（`su_spec_floors.py` 出的，与交付 GLB 逐构件同源），
# 挤出 / 逐面双面配色 / 当场量体积对账三条铁律原样保留。差异只有三处：
#   ① 不并进一个 root，而是每层一个**顶层组** `yingzao-F0…F4` + `yingzao-屋顶`，
#      每个组挂同名 Tag ⇒ 关 Tag 即整层消失（「每层能解开」就是这么实现的）。
#   ② 房间地垫的材质名用 `yz用途-<用途>`（颜色 = 用途色）⇒ SU 材质面板直接当图例。
#   ③ 每间房一条 SU Text（`房间号  用途`），挂 Tag `yingzao-用途标注`；
#      再出「总览 + 每层一张」场景，逐页预置好该层可见性。
#
# ★ 本文件的 SU API 全部是**探针实测**过的，不照记忆写（三份探针见 su_src/probe_*.rb）：
#   · Tag 集合是 `m.layers`（`m.tags` 是 String，会静默降级）；`Layer` 只有 `visible=`/`visible?`，
#     没有 reader `visible`（写成 `tag.visible` 直接 NoMethodError）。
#   · `Page#camera=` **不存在**；相机只能「选中该页 → 设视口相机 → use_camera → update」捕获。
#   · 逐页可见性用 `page.set_visibility(layer, bool)`；`page.layers` 是**被关掉的层名数组**（可验）。
#   · `m.textoptions` / `Sketchup::Text.constants` 在 2023 里不存在 ⇒ 中文字体**没有 API 可设**，
#     只能靠 SU 默认字体渲染，建完用截图验字形（不静默，见 .out 的 font_api 字段）。
#   · `View#camera` 返回**活引用不是副本**：读相机必须立刻 `to_a` 抄成数值，否则后面对
#     `av.camera = x` 的改动会把「原值」一起改掉（上一版探针就是这么把用户视口挪走的）。
#
# 安全：只认领**我自己命名的组**（`yingzao-F*`/`yingzao-屋顶`）与我的 Tag，**绝不**按 `yz*` 材质
# 认领（那样会把用户文档里 `build_model.rb` 建的整栋 `yingzao-build` 一起吃掉）。
# 另外：文档顶层还有**任何不属于我的实体**（= 没开新文档，坐标与理化楼几乎重合）就**什么都不做**
# 并在 .out 里拒绝，不撞不删。判据是「顶层实体清单」而不是组名 —— 组会被 explode 掉，
# 散面不会（实测踩过，见下面 0) 段的注释）。
require 'json'

SPEC = ENV['YZ_SPEC'] || 'D:/gym3d/_scratch/su_jobs/_lihua_floors_spec.json'
BAND = -1                            # -1 = 全部；>=0 只建该层带（冒烟档，先在一层上验全链）
PROG = 'D:/gym3d/_scratch/su_jobs/_progress_floors.txt'
VOL_TOL = 0.002                      # m³ 允许误差
LABEL_Z = 1.5                        # 注释锚点离本层地面 1.5 m（站在房间里看得见）
NOTE_TAG = 'yingzao-用途标注'
# 构件类别 Tag（`yz构件-墙` …）：一类一个 Tag ⇒ 关掉「墙」「窗」两个 Tag 就是
# 「墙体隐藏、窗户隐形」的每层平面。类别由 spec 端定（`p['cat']`），Ruby 侧不认识颜色。
CAT_PREFIX = 'yz构件-'
CAT_ORDER = %w[墙 窗 门 楼梯 柱 楼板 地垫 屋顶 场地 其他].freeze
HIDE_IN_PLAN = %w[墙 窗].freeze     # 平面页关掉这两类（用户点名的「墙体隐藏、窗户隐形」）
LEN_TO_M = { 0 => 0.0254, 1 => 0.3048, 2 => 0.001, 3 => 0.01, 4 => 1.0 }.freeze

def prog(s)
  File.open(PROG, 'a') { |f| f.puts("#{Time.now.strftime('%H:%M:%S')} #{s}") }
rescue StandardError
  nil
end

# 带洞的棱柱：外环 add_face → 内环各 add_face 后抹掉（留洞）→ pushpull。照抄 build_model.rb。
def prism(ents, ext, holes, z0, z1)
  f = ents.add_face(ext.map { |x, y| Geom::Point3d.new(x.m, y.m, z0.m) })
  return false if f.nil?

  holes.each do |h|
    hf = ents.add_face(h.map { |x, y| Geom::Point3d.new(x.m, y.m, z0.m) })
    hf.erase! if hf && !hf.deleted?
  end
  f.reverse! if f.normal.z < 0
  f.pushpull((z1 - z0).m)
  true
rescue StandardError
  false
end

# 侧壁配对按**边中点**（端点会栽在毫米半格上，见 build_model.rb 的长注释）。
GRID = 20.0
TOL_MM = 5.0

def mid_mm(x1, y1, x2, y2)
  [(x1 + x2) * 500.0, (y1 + y2) * 500.0]
end

def cnv(hex)
  Sketchup::Color.new(hex[1, 2].to_i(16), hex[3, 2].to_i(16), hex[5, 2].to_i(16))
end

# 递归收集面/边 —— 有了**二级组**之后，面不再直接挂在本层组上（关「墙」关不干净的检查、
# 材质回填、面数对账都必须能看进去）。只认 Group（不用 ComponentInstance）。
def all_faces(ents)
  fs = ents.grep(Sketchup::Face)
  ents.grep(Sketchup::Group).each { |g| fs.concat(all_faces(g.entities)) }
  fs
end

def all_edges(ents)
  es = ents.grep(Sketchup::Edge)
  ents.grep(Sketchup::Group).each { |g| es.concat(all_edges(g.entities)) }
  es
end

spec = JSON.parse(File.read(SPEC, mode: 'rb').force_encoding('UTF-8'))
m = Sketchup.active_model
File.delete(PROG) if File.exist?(PROG)

u = m.options['UnitsOptions']['LengthUnit']
LEN2M = LEN_TO_M[u] || 1.0
meta = spec['meta'] || {}
fh = meta['floorH'] || meta['floor_h'] || 4.2
labels = meta['rooms_label'] || []
gmeta = meta['groups'] || {}
all = spec['parts']
nf = gmeta.keys.count { |k| k =~ /\AF\d+\z/ }        # 楼层数（屋顶带的键 = nf）

def bname(b, nf)
  b >= nf ? '屋顶' : "F#{b}"
end

bands = all.map { |p| p['band'] }.uniq.select { |b| b >= 0 }.sort   # 场地带 -1 不参与楼层页
# 顶层组清单：楼层 + 屋顶 + 场地（场地只在新 spec 里有）。组名由 spec 的 `groupOrder` 给定，
# 缺这节的老 spec 就按 band 现算（向后兼容，但那样没有场地组）。
group_order = meta['groupOrder'] || ((0...nf).map { |b| "F#{b}" } + ['屋顶'])
my_names = group_order.map { |x| "yingzao-#{x}" }
PAIR = meta['pair'] || []
# 冒烟档：BAND>=0 只建该层带（组/Tag/场景照样全建，用来在一层上验整条链）
sel = BAND >= 0 ? (0...all.length).select { |i| all[i]['band'] == BAND } : (0...all.length).to_a
labels_sel = BAND >= 0 ? labels.select { |lab| lab['floor'] == BAND } : labels

R = {
  'spec' => spec['name'], 'src' => spec['src'], 'unit' => u, 'len2m' => LEN2M,
  'floor_h' => fh, 'floors' => nf, 'parts_spec' => all.length,
  'band_filter' => BAND, 'parts_this_run' => sel.length,
  'bands' => bands, 'group_names' => my_names,
  'spec_groups' => gmeta, 'pair' => PAIR,
  'labels_spec' => labels_sel.length, 'pad_thickness' => meta['padThickness'],
  'windows_included' => meta['windowsIncluded'],
  # 探针结论写进结果里：字体这一格没 API，只能靠 SU 默认 + 截图验
  'font_api' => { 'model.textoptions' => m.respond_to?(:textoptions),
                  'Sketchup::Text.constants' => (Sketchup::Text.constants.length rescue -1),
                  'note' => '2023 无 TextOptions ⇒ 中文字体不可程序设置，字形靠截图验收' }
}

# ---------- 0) 防撞：文档顶层只要还有**不属于我的实体**，一根手指都不动 ----------
# 只按组名认（`yingzao-build*`）不够 —— 实测踩过：那栋楼被 explode 之后顶层一个组都没有，
# 只剩三万个散面，按组名认就完全看不见它，理化楼会直接盖在它身上。改成「顶层实体清单」判据：
# 新文档顶层实体数 = 0，所以只要 `m.entities` 里还有非我所有的东西，就是没开新文档。
mine_top = m.entities.grep(Sketchup::Group).select { |g| my_names.include?(g.name.to_s) }
foreign = m.entities.to_a - mine_top
fk = Hash.new(0)
foreign.each { |e| fk[e.class.name.split('::').last] += 1 }
conflict = foreign.first(8).map { |e| "#{e.class.name.split('::').last}:#{(e.respond_to?(:name) ? e.name : '').to_s}" }
R['conflict_groups'] = m.entities.grep(Sketchup::Group).map { |g| g.name.to_s }.select { |n| n.start_with?('yingzao-build') }
R['conflict_any'] = foreign.any?
R['conflict_kinds'] = fk
R['conflict_sample'] = conflict
# 顶层实体可能上万个（散面）：只报前 40 个 + 总数，别让 .out 变成几十万字符
R['top_entities'] = { 'total' => m.entities.length, 'sample' => m.entities.first(40).map { |e|
  "#{e.class.name.split('::').last}:#{(e.respond_to?(:name) ? e.name : '').to_s}"
} }
if foreign.any? && BAND < 0
  R['aborted'] = "文档顶层还有 #{foreign.length} 个不属于我的实体（#{fk.map { |k, v| "#{k}×#{v}" }.join('、')}）" \
                 ' —— 说明没开新文档。理化楼与它平面坐标几乎重合，不撞也不删。' \
                 '请先 File → New（或清空文档）再投递。'
  prog "拒绝：#{R['aborted']}"
  R
else
  # 冒烟档（BAND>=0）是例外：它建的是**临时**几何，用完按精确组名清掉（下一次运行会先扫），
  # 只认领 yingzao-F*/yingzao-屋顶，永远不动 yingzao-build。代价是坐标与已有楼重叠 —— 属预期。
  R['conflict_note'] = foreign.any? ? "冒烟档在已有 #{foreign.length} 个顶层实体的文档里建临时几何（重叠属预期）" : nil
  # ---------- 1) 只扫我自己的：组名精确匹配（不按材质认领，见文件头）----------
  t0 = Time.now
  m.start_operation("yingzao: build #{spec['name']} floors", true)
  swept = []
  begin
    m.entities.grep(Sketchup::Group).each do |g|
      n = g.name.to_s
      next unless my_names.include?(n)

      swept << n
      g.erase!
    end
    gone = []
    old_cat_tags = m.layers.map(&:name).select { |x| x.start_with?(CAT_PREFIX) }
    (my_names + [NOTE_TAG] + old_cat_tags).each do |nm|
      t = m.layers[nm]
      next unless t

      t.visible = true
      m.layers.remove(t)
      gone << nm
    end
    m.materials.purge_unused

    # 我自己的页也要清（否则冒烟档跑完再跑全量会出现两套同名页）。
    # `pages.erase` 与 `page.erase!` 哪个在 2023 上可用探针没定 ⇒ 两条都试，把走了哪条报出去。
    pg_gone = []
    pg_api = nil
    mine_pages = m.pages.select do |pg|
      n = pg.name.to_s
      n == '总览' || n =~ /\A(F\d+|屋顶) (本层|平面)\z/
    end
    mine_pages.each do |pg|
      nm = pg.name.to_s          # ★ 名字必须先抄下来：erase 之后 pg 是死引用，再 .name 直接
      begin                      #   TypeError: reference to deleted Page（这个坑踩过一次）
        m.pages.erase(pg)
        pg_api = 'pages.erase'
      rescue StandardError
        begin
          pg.erase!
          pg_api = 'page.erase!'
        rescue StandardError => e2
          pg_api = "#{e2.class}: #{e2.message}"
        end
      end
      pg_gone << nm
    end
    R['swept_groups'] = swept
    R['dropped_tags'] = gone
    R['swept_pages'] = pg_gone
    R['page_erase_api'] = pg_api

    # ---------- 2) 每层一个顶层组 + 同名 Tag ----------
    groups = {}
    tags = {}
    my_names.each do |n|
      g = m.entities.add_group
      g.name = n
      groups[n] = g
      tags[n] = m.layers.add(n)
      g.layer = tags[n]
    end
    note_tag = m.layers.add(NOTE_TAG)
    # 构件类别 Tag：只建**这次真的会出现**的类（空 Tag 只会碍眼）
    cats = sel.map { |i| all[i]['cat'] || '其他' }.uniq
    cats = CAT_ORDER.select { |c| cats.include?(c) } + (cats - CAT_ORDER)
    cat_tags = {}
    cats.each { |c| cat_tags[c] = m.layers.add(CAT_PREFIX + c) }
    R['tags_made'] = my_names + [NOTE_TAG] + cats.map { |c| CAT_PREFIX + c }

    # ---------- 2b) 二级组：一个 `sub` 名一个**容器** ----------
    # 为什么非分不可（实测，不是理论）：SU 只在**同一个容器内**才把共面/贴面的面合并，
    # 而合并会把「被后来的面盖住的那块」**整个删掉** —— 屋面板下盖面 921.3 m²、每层楼板
    # 下盖面就是这么没的（墙脚扎进楼板 0.2 m、女儿墙脚扎进屋面板 0.2 m，共面处被并成一份）。
    # 二级组名由 spec 端给（`p['sub']`，同类别内按颜色细分：外墙/内墙、玻璃/窗框、
    # 屋面/女儿墙、楼板、地垫-<用途>…），Ruby 侧不认颜色也不猜名字。
    # 容器自己也挂类别 Tag ⇒ 关「窗」时整个「玻璃」容器一起消失，不会剩一堆线框。
    sub_groups = Hash.new { |h, k| h[k] = {} }
    subg_of = lambda do |gn, sub, cat|
      sub_groups[gn][sub] ||= begin
        sg = groups[gn].entities.add_group
        sg.name = sub
        ct = cat_tags[cat]
        sg.layer = ct if ct
        sg
      end
    end

    # 材质：整栋色 `yz<hex>`；带 purpose 的地垫用 `yz用途-<用途>`（材质面板即图例）
    mats = {}
    mat_hex = lambda do |hex|
      mats[hex] ||= begin
        mt = m.materials["yz#{hex.delete('#')}"] || m.materials.add("yz#{hex.delete('#')}")
        mt.color = cnv(hex)
        mt
      end
    end
    mats_p = {}
    mat_purpose = lambda do |pu, hex|
      key = "yz用途-#{pu}"
      mats_p[key] ||= begin
        mt = m.materials[key] || m.materials.add(key)
        mt.color = cnv(hex)
        mt
      end
    end
    other_color = lambda do |hex|
      next hex unless PAIR.length == 2
      next PAIR[1] if hex == PAIR[0]
      next PAIR[0] if hex == PAIR[1]

      hex
    end

    built = noface = bad_v = bad_f = miss = painted = nlab = 0
    missed = []
    verr = []
    maxd = 0.0
    hist = Hash.new(0)
    exp_vol = Hash.new(0.0)
    act_vol = Hash.new(0.0)
    g_built = Hash.new(0)
    g_noface = Hash.new(0)
    g_vol_bad = Hash.new(0)
    g_faces_bad = Hash.new(0)
    g_miss = Hash.new(0)
    g_cat = Hash.new(0)
    sel.each_with_index do |pi, k|
      p = all[pi]
      # 组名**优先读 spec 给的 `group`**：场地带是 -1，用 bname 会算出「F-1」这个不存在的组，
      # 部件就被静默跳过（`fg` 为 nil ⇒ 只加全局 noface，逐组台账里什么都看不到）。
      # 与 Python 验证器 `floor_tags` 那个坑同源。老 spec 没有 `group` 才现算。
      gn = "yingzao-#{p['group'] || bname(p['band'], nf)}"
      fg = groups[gn]
      unless fg
        noface += 1
        R['skip_unknown_group'] ||= []
        R['skip_unknown_group'] << [gn, p['kind'], p['cat']] if R['skip_unknown_group'].length < 10
        next
      end
      exp_vol[gn] += p['vol']
      # 建在**二级组**里（同 sub 的部件才同容器；见 2b 段的长注释）
      g = subg_of.call(gn, p['sub'] || p['cat'] || '其他', p['cat'] || '其他').entities.add_group
      unless prism(g.entities, p['ext'], p['holes'] || [], p['z0'], p['z1'])
        noface += 1
        g_noface[gn] += 1
        g.erase! if g.valid?
        next
      end
      built += 1
      g_built[gn] += 1

      vol = (begin
        g.volume * (LEN2M**3)
      rescue StandardError
        nil
      end)
      act_vol[gn] += vol if vol
      if vol.nil? || (vol - p['vol']).abs > VOL_TOL
        bad_v += 1
        g_vol_bad[gn] += 1
        verr << [gn, p['kind'], pi, vol && vol.round(4), p['vol']] if verr.length < 10
      end

      faces = g.entities.grep(Sketchup::Face)
      unless faces.length == p['nf']
        bad_f += 1
        g_faces_bad[gn] += 1
      end

      capm = p['purpose'] ? mat_purpose.call(p['purpose'], p['cap']) : mat_hex.call(p['cap'])
      caps = faces.select { |f| f.normal.z.abs > 0.99 }
      caps.each do |f|                     # 盖面：整块一个色
        f.material = capm
        f.back_material = capm
      end

      if (p['edgeN'] || []).empty?         # 整件单色（盒/玻璃/楼板/房间地垫）
        faces.each do |f|
          next if f.normal.z.abs > 0.99

          f.material = capm
          f.back_material = capm
        end
      else
        buckets = Hash.new { |h, kk| h[kk] = [] }
        rings = [[p['ext'], p['edgeCols'], p['edgeN']]]
        (p['holes'] || []).each_with_index do |ring, hi|
          rings << [ring, p['holeEdgeCols'][hi], p['holeEdgeN'][hi]]
        end
        rings.each do |pts, cols, norms|
          nn = pts.length
          nn.times do |i|
            a = pts[i]
            b = pts[(i + 1) % nn]
            mx, my = mid_mm(a[0], a[1], b[0], b[1])
            buckets[[(mx / GRID).floor, (my / GRID).floor]] << [mx, my, cols[i], norms[i]]
          end
        end
        bot = caps.min_by { |f| f.bounds.center.z }
        if bot
          bot.loops.each do |lp|
            lp.edges.each do |e|
              sp = e.start.position
              ep = e.end.position
              mx, my = mid_mm(sp.x.to_m, sp.y.to_m, ep.x.to_m, ep.y.to_m)
              info = nil
              bd = TOL_MM
              [-1, 0, 1].product([-1, 0, 1]).each do |gx, gy|
                buckets[[(mx / GRID).floor + gx, (my / GRID).floor + gy]].each do |ex, ey, c, nr|
                  d = Math.hypot(ex - mx, ey - my)
                  if d < bd
                    bd = d
                    info = [c, nr]
                  end
                end
              end
              if info.nil?
                miss += 1
                g_miss[gn] += 1
                missed << [gn, p['kind'], [mx.round(2), my.round(2)]] if missed.length < 12
                next
              end
              maxd = bd if bd > maxd
              sf = e.faces.find { |x| x != bot && x.normal.z.abs <= 0.99 }
              next unless sf

              hex, nr = info
              front = hex
              back = other_color.call(hex)
              if sf.normal.x * nr[0] + sf.normal.y * nr[1] < 0
                front, back = back, front
              end
              sf.material = mat_hex.call(front)
              sf.back_material = mat_hex.call(back)
              painted += 1
              hist[front] += 1
            end
          end
        end
      end

      # 构件类别落到**实体**上（不是落在子组上）：explode 会把子组的实体搬进本层组，
      # 实体自己的 Tag 跟着走。是否真跟过去了由 .out 的 cat_faces / faces_off_cat 实测
      # （faces_off_cat 必须为 0，否则「关墙」会关不干净）。
      ct = cat_tags[p['cat'] || '其他']
      if ct
        g.entities.each { |e| e.layer = ct }
        g_cat[p['cat'] || '其他'] += 1
      end

      (g.explode rescue nil)               # 立刻并进本层组：别让几千个组拖住 UI
      if ((k + 1) % 200).zero?
        el = Time.now - t0
        prog "  #{k + 1}/#{sel.length} 用时#{el.round(1)}s 预计#{(el / (k + 1) * sel.length).round}s"
      end
    end

    # ---------- 3) 每间房一条注释（不是几何，不污染体积/面数对账）----------
    lab_err = []
    labels_sel.each do |lab|
      gn = "yingzao-#{bname(lab['floor'], nf)}"
      fg = groups[gn]
      unless fg
        lab_err << [lab['number'], gn]
        next
      end
      x, y = lab['cent']
      z = lab['floor'] * fh + LABEL_Z
      t = fg.entities.add_text("#{lab['number']}  #{lab['purpose']}",
                               Geom::Point3d.new(x.m, y.m, z.m),
                               Geom::Vector3d.new(0, 0, 1))
      unless t
        lab_err << [lab['number'], 'add_text 返回 nil']
        next
      end
      (t.layer = note_tag) rescue nil
      (t.display_leader = true) rescue nil
      R['label_readback'] ||= t.text        # 建完读回一条，验中文没坏
      nlab += 1
    end

    # ---------- 4) 场景：总览 + 每层「只显本层」+ 每层竖直错开的轴测 ----------
    pages = []
    pgs = []
    begin
      av = m.active_view
      av.zoom_extents
      # ★ 相机是**活引用**：要立刻抄成数值，否则后面 av.camera= 会把「原值」一起改掉
      c0 = av.camera
      ov = [c0.eye.to_a, c0.target.to_a, c0.up.to_a, (c0.perspective? rescue true)]
      # 全模型包围盒 = 6 个组包围盒的并集（单位：模型单位，最后再折成米）
      bb = nil
      groups.each_value do |g|
        b = g.bounds
        lo = [b.min.x.to_f, b.min.y.to_f, b.min.z.to_f]
        hi = [b.max.x.to_f, b.max.y.to_f, b.max.z.to_f]
        if bb.nil?
          bb = [lo, hi]
        else
          3.times do |i|
            bb[0][i] = lo[i] if lo[i] < bb[0][i]
            bb[1][i] = hi[i] if hi[i] > bb[1][i]
          end
        end
      end
      bb = bb[0] + bb[1] if bb          # 展平成 [x0,y0,z0,x1,y1,z1]，与 build_model.rb 同序

      ov_pg = m.pages.add('总览')
      m.pages.selected_page = ov_pg
      (ov_pg.use_camera = true) rescue nil
      (ov_pg.use_hidden_layers = true) rescue nil
      ov_pg.update
      pgs << ov_pg
      # page.layers 的元素是「层名」还是 Layer 对象，探针没断定 ⇒ 两种都接住（只报不猜）
      lay_names = lambda do |pg|
        (pg.layers.map { |x| x.respond_to?(:name) ? x.name : x.to_s } rescue ['ERR'])
      end
      pages << { 'name' => '总览', 'hidden' => lay_names.call(ov_pg) }

      cx = (bb[0].to_f + bb[3].to_f) / 2
      cy = (bb[1].to_f + bb[4].to_f) / 2
      span = [bb[3].to_f - bb[0].to_f, bb[4].to_f - bb[1].to_f].max
      # 正射俯视相机（**北朝上**，与工程平面图一致）：平面页要的是房间分布，不是透视。
      # 正射相机的视野高 `height` 是模型单位；视口不是横的就得按宽高比放大，否则两侧被裁。
      top_cam = lambda do |zx, zy, zz|
        asp = av.vpwidth.to_f / [av.vpheight, 1].max
        h = span * 1.05
        h = span * 1.05 / asp if asp < 1.0
        c = Sketchup::Camera.new(Geom::Point3d.new(zx, zy, zz + span),
                                 Geom::Point3d.new(zx, zy, zz),
                                 Geom::Vector3d.new(0, 1, 0))
        c.perspective = false
        begin
          c.height = h
        rescue StandardError
          nil
        end
        c
      end
      bands.each do |b|
        gn = "yingzao-#{bname(b, nf)}"
        pn = b >= nf ? '屋顶' : "F#{b}"
        pg = m.pages.add("#{pn} 本层")
        m.pages.selected_page = pg
        tags.each { |n2, t| pg.set_visibility(t, n2 == gn) }   # 只留本层
        # 构件类别必须**逐页显式**打开：页的显隐是「当前状态」写进去的，上一张平面页关掉的
        # 「墙/窗」会顺延到这一张（实测踩过：F0 本层好着，F1~屋顶 本层全把墙窗关了）。
        cat_tags.each { |_c, t| pg.set_visibility(t, true) }
        pg.set_visibility(note_tag, true)                     # 注释跟着走
        z = b * fh
        av.camera = Sketchup::Camera.new(
          Geom::Point3d.new(cx - span * 0.30, cy - span * 0.55, z + span * 0.60),
          Geom::Point3d.new(cx, cy, z + 0.5),
          Geom::Vector3d.new(0, 0, 1)
        )
        (pg.use_camera = true) rescue nil
        (pg.use_hidden_layers = true) rescue nil
        pg.update
        pgs << pg
        pages << { 'name' => pg.name, 'hidden' => lay_names.call(pg),
                   'kept' => gn, 'kind' => '本层' }

        # 「平面」页 = 本层 + 关掉「墙」「窗」两个构件 Tag（房间与用途一目了然）
        pg2 = m.pages.add("#{pn} 平面")
        m.pages.selected_page = pg2
        tags.each { |n2, t| pg2.set_visibility(t, n2 == gn) }
        cat_tags.each { |c, t| pg2.set_visibility(t, !HIDE_IN_PLAN.include?(c)) }
        pg2.set_visibility(note_tag, true)
        av.camera = top_cam.call(cx, cy, z)
        (pg2.use_camera = true) rescue nil
        (pg2.use_hidden_layers = true) rescue nil
        pg2.update
        pgs << pg2
        pages << { 'name' => pg2.name, 'hidden' => lay_names.call(pg2),
                   'kept' => gn, 'kind' => '平面', 'hide' => HIDE_IN_PLAN }
      end

      # 收在「总览」：全局全可见 + 视口回总览机位
      tags.each_value { |t| t.visible = true }
      cat_tags.each_value { |t| t.visible = true }
      note_tag.visible = true
      av.camera = Sketchup::Camera.new(Geom::Point3d.new(ov[0][0], ov[0][1], ov[0][2]),
                                       Geom::Point3d.new(ov[1][0], ov[1][1], ov[1][2]),
                                       Geom::Vector3d.new(ov[2][0], ov[2][1], ov[2][2]))
      m.pages.selected_page = ov_pg
      ov_pg.update
    rescue StandardError => e
      R['pages_err'] = "#{e.class}: #{e.message}"
    end
    R['pages'] = pages
    R['pages_count'] = m.pages.count

    # ---------- 4b) 按材质回填：把 explode **新造出来的面**归回类别 Tag ----------
    # 为什么需要这一步：把部件 explode 进本层组时，SU 会把**共面且共享边**的面合并/切分，
    # 新造出来的面默认落在 Layer0 —— 身份丢了，但它**材质还在**。「颜色 → 类别」在建体端是
    # **单值表**（`su_spec_floors._categorize` 里加了守卫：一码两用直接中止），所以按材质回填
    # 是**唯一确定的**，不是猜。认不出来的面一个都不蒙：全部计数报进 `faces_retag_unknown`。
    # （实测：206 个面 / 79.6 m² 全是墙皮 `yzcfc9bd` —— 就是「隐藏墙」关不干净的那几块。）
    mat2cat = {}
    (meta['catColors'] || {}).each { |h, c| mat2cat["yz#{h.delete('#').downcase}"] = c }
    pad_cat = meta['padCat'] || '地垫'
    pad_prefix = meta['padMatPrefix'] || 'yz用途-'
    retag = 0
    retag_hit = Hash.new(0)
    retag_bad = Hash.new(0)
    groups.each do |gn, g|
      all_faces(g.entities).each do |f|
        ln = (f.layer.name rescue nil)
        next if ln && ln.start_with?(CAT_PREFIX)

        mn = (f.material ? f.material.name : (f.back_material ? f.back_material.name : nil)).to_s
        c = mn.start_with?(pad_prefix) ? pad_cat : mat2cat[mn]
        if c && cat_tags[c]
          f.layer = cat_tags[c]
          retag += 1
          retag_hit[[gn, mn]] += 1
        else
          retag_bad[[gn, mn.empty? ? '<无材质>' : mn]] += 1
        end
      end
    end
    # 表读没读到也要报数：为 0 说明 spec 是旧的（没有 `meta.catColors` 这一节），
    # 那时 retag 会整批失败 —— 报出来才不会误以为「回填过但没命中」
    R['cat_color_table_n'] = mat2cat.length
    R['faces_retag_by_material'] = retag
    R['faces_retag_hit'] = retag_hit.sort_by { |_, v| -v }.first(12).to_h
    R['faces_retag_unknown'] = retag_bad

    # ---------- 5) 对账 ----------
    faces_all = 0
    groups.each_value { |g| faces_all += all_faces(g.entities).length }
    R['groups'] = my_names.map do |n|
      { 'name' => n, 'tag' => (groups[n].layer.name rescue 'n/a'),
        # gmeta 的键是不带前缀的（F0…屋顶）；用带前缀的组名去取会恒为 nil（这个坑踩过一次）
        'spec_cnt' => gmeta[n.sub('yingzao-', '')],
        'run_cnt' => sel.count { |i| (all[i]['group'] || bname(all[i]['band'], nf)) == n.sub('yingzao-', '') },
        'built' => g_built[n], 'noface' => g_noface[n],
        'faces' => all_faces(groups[n].entities).length,
        'subs' => (sub_groups[n] || {}).keys,
        'sub_faces' => (sub_groups[n] || {}).map { |s, sg| [s, all_faces(sg.entities).length] }.to_h,
        'exp_vol' => exp_vol[n].round(3), 'act_vol' => act_vol[n].round(3),
        'vol_bad' => g_vol_bad[n], 'faces_bad' => g_faces_bad[n], 'edge_miss' => g_miss[n] }
    end
    # 水平面台账（>50 m² 的，按 z 平面列）：直接验「地面/屋面的盖面还在不在」——
    # 每个带在**楼板底面那个 z**上都该有一块面积 == 本层足迹的板面；屋顶带在 21.0 要有
    # 屋面板下盖面、21.2 要有上盖面。被合并删掉的话这一格就是空的，一眼就能看出来。
    R['big_horiz'] = groups.map do |gn, g|
      [gn, all_faces(g.entities).select { |f| f.normal.z.abs > 0.99 }
             .map { |f| [(f.bounds.center.z.to_m * 1000).round / 1000.0, (f.area * (LEN2M**2)).round(3)] }
             .select { |_, a| a > 50.0 }.sort]
    end.to_h
    # 构件类别实测：面**真的**落在类别 Tag 上吗（explode 若把 Tag 丢了，这里立刻暴露）
    cat_faces = Hash.new(0)
    off_cat = 0
    off_edge = 0
    off_sample = []
    groups.each_value do |g|
      # 边也要报到：关掉「墙」而墙的**边**还留在 Layer0 的话，平面上会剩一副线框
      all_edges(g.entities).each do |e|
        ln = (e.layer.name rescue nil)
        off_edge += 1 unless ln && ln.start_with?(CAT_PREFIX)
      end
      all_faces(g.entities).each do |f|
        ln = (f.layer.name rescue nil)
        if ln && ln.start_with?(CAT_PREFIX)
          cat_faces[ln.sub(CAT_PREFIX, '')] += 1
        else
          off_cat += 1
          off_sample << [g.name, ln] if off_sample.length < 5
        end
      end
    end
    R['cat_order'] = CAT_ORDER
    R['cat_spec'] = meta['catCounts']
    R['cat_parts'] = g_cat
    R['cat_faces'] = cat_faces
    R['faces_off_cat'] = off_cat
    R['faces_off_cat_sample'] = off_sample
    R['edges_off_cat'] = off_edge
    R['plan_hides'] = HIDE_IN_PLAN
    R['built'] = built
    R['noface'] = noface
    R['vol_bad'] = bad_v
    R['vol_err'] = verr
    R['faces_bad'] = bad_f
    R['edge_miss'] = miss
    R['missed'] = missed
    R['maxd_mm'] = maxd.round(5)
    R['painted'] = painted
    R['exp_vol'] = exp_vol.values.sum.round(3)
    R['act_vol'] = act_vol.values.sum.round(3)
    R['faces_after'] = faces_all
    R['labels_built'] = nlab
    R['label_err'] = lab_err
    R['colors'] = hist.sort_by { |_, v| -v }[0, 12].to_h
    R['materials'] = m.materials.map(&:name).select { |x| x.start_with?('yz') }.sort
    R['tags_after'] = m.layers.map(&:name)
    R['bbox'] = bb && bb.map { |v| (v.to_f * LEN2M).round(3) }
    R['secs'] = (Time.now - t0).round(1)
  rescue StandardError => e
    R['error'] = "#{e.class}: #{e.message}"
    R['error_backtrace'] = (e.backtrace || [])[0, 5]
  ensure
    m.commit_operation
  end
  prog "完成 建#{R['built']} 注释#{R['labels_built']} 页#{R['pages_count']} 用时#{R['secs']}s"
  R
end
