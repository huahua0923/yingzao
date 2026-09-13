# -*- coding: utf-8 -*-
# 在 SU 里盖整栋楼：读 Python(su_spec.py) 备好的部件表，逐个挤出、当场量体积对账、
# 逐面逐侧上色，最后 explode 合并。SU 侧零布尔运算（多边形运算都在 shapely 里做完）。
#
# 三条不能动的规矩（都是踩出来的）：
#
# ① **每个部件在独立组里建**：同组里相邻部件（楼板顶面 / 墙底带底面、墙的上中下
#    三段）的顶底面完全重合，SU 会把 pushpull 作用到那张已有面上、把下面的体扯开，
#    实测丢 4.9% 材料（417→397 m³）。独立组里建就撞不上别人的重合面。
#
# ② **逐面要贴两次色**（material + back_material）：SU 的材质贴在「面的某一侧」，
#    没上色的那一侧显示的是默认的浅蓝灰，不是正面材质。交付件里一张侧壁只有一个
#    颜色，那是**沿外法向**探出来的朝向色；到 SU 要贴到法向所指的那侧，另一侧贴
#    配对色（朝外=立面 / 朝内=室内，与 building.html 同口径）。
#
# ③ **建完当场量体积**：SU 的 Group#volume 按「模型单位」的三次方返回（英寸模型
#    直接跟 m³ 比会差 25463091 倍）。按 LengthUnit 折算后再比，这才是唯一能抓住
#    ①那类材料损失的检查（面数对不上、体积对不上都要报出来，不假装成功）。
#
# 本文件是**源**：改完经 su_deploy.sh 投递（桥跑完即删任务文件）。
# 用法：SPEC 路径与 BAND（-1=全部，>=0 只建该层带）由 su_deploy.sh 烘进来。
require 'json'

SPEC = ENV['YZ_SPEC'] || 'D:/gym3d/_scratch/su_jobs/_ny27_su.json'
BAND = -1
PROG = 'D:/gym3d/_scratch/su_jobs/_progress.txt'
VOL_TOL = 0.002                      # m³ 允许误差
LEN_TO_M = { 0 => 0.0254, 1 => 0.3048, 2 => 0.001, 3 => 0.01, 4 => 1.0 }.freeze

def prog(s)
  File.open(PROG, 'a') { |f| f.puts("#{Time.now.strftime('%H:%M:%S')} #{s}") }
rescue StandardError
  nil
end

# 带洞的棱柱：外环 add_face → 内环各 add_face 后抹掉（留洞）→ pushpull。
def prism(ents, ext, holes, z0, z1)
  f = ents.add_face(ext.map { |x, y| Geom::Point3d.new(x.m, y.m, z0.m) })
  return false if f.nil?

  holes.each do |h|
    hf = ents.add_face(h.map { |x, y| Geom::Point3d.new(x.m, y.m, z0.m) })
    hf.erase! if hf && !hf.deleted?  # 留洞：洞环变成外环的内环
  end
  f.reverse! if f.normal.z < 0       # 保证朝 +Z 挤出
  f.pushpull((z1 - z0).m)
  true
rescue StandardError
  false
end

# 侧壁配对用**边中点**，不用端点。端点会栽在毫米半格上：spec 的坐标 round 到
# 1e-5 m、SU 存英寸，正好落在 x.5mm 的点两边会取整到相邻格（实测女儿墙有个
# y=1875.5mm 的点：spec 记 1876、SU 算 1875），端点键就永远配不上，而且按整条边
# 平移回查也救不了 —— 差的是**单个端点**的半格。
# 中点没有这个毛病：一条边的中点离别的边的中点总有半个边长的距离。
GRID = 20.0     # 中点分桶的格宽（mm）
TOL_MM = 5.0    # 中点配对容差（mm）—— 实测误差在 1e-4mm 量级，5mm 是保险

def mid_mm(x1, y1, x2, y2)
  [(x1 + x2) * 500.0, (y1 + y2) * 500.0]   # 入参是米，出参是 mm
end

spec = JSON.parse(File.read(SPEC, mode: 'rb').force_encoding('UTF-8'))
m = Sketchup.active_model
File.delete(PROG) if File.exist?(PROG)

u = m.options['UnitsOptions']['LengthUnit']
LEN2M = LEN_TO_M[u] || 1.0
fh = spec['meta']['floor_h'] || 4.2
PAIR = spec['meta']['pair'] || []
all = spec['parts']

# 分带按**底板标高**落在哪一层，不是四舍五入：门过梁(2.3)、上半跑踏步(z0>2.1)
# 这些「层上半部的部件」按 round 会被划到上一层去。加 1e-6 是吸掉 12.6/4.2=2.9999… 这类
# 浮点误差（4µm 的容差，部件离层边界不会这么近）。
sel = if BAND >= 0
        (0...all.length).select { |i| ((all[i]['z0'] / fh) + 1e-6).floor == BAND }
      else
        (0...all.length).to_a
      end
MY = BAND >= 0 ? "yingzao-build-b#{BAND}" : 'yingzao-build'
prog "spec=#{spec['name']} 部件#{all.length} 本次#{sel.length} 带#{BAND} 单位#{u}/#{LEN2M}"

# 朝外是立面色、朝内是室内色 —— 同一张面两侧的配对
other_color = lambda do |hex|
  next hex unless PAIR.length == 2
  next PAIR[1] if hex == PAIR[0]
  next PAIR[0] if hex == PAIR[1]
  hex
end

mats = {}
mat_of = lambda do |hex|
  mats[hex] ||= begin
    mt = m.materials["yz#{hex.delete('#')}"] || m.materials.add("yz#{hex.delete('#')}")
    mt.color = Sketchup::Color.new(hex[1, 2].to_i(16), hex[3, 2].to_i(16), hex[5, 2].to_i(16))
    mt
  end
end

# 「是不是我建的」——按材质认领，不只按组名。组名会丢（实测早先一次试验留下的组
# 名字是空的，按名字扫不到，于是它的旧几何一直在楼里显形：底层那圈暗栗色其实是
# 旧材质 yingzao_facade 的线性空间色 [95,22,12]）。用户自己的材质不会叫 yz*/yingzao_*。
def mine?(g)
  return false unless g.respond_to?(:definition)

  g.definition.entities.grep(Sketchup::Face).any? do |f|
    [f.material, f.back_material].compact.any? do |mt|
      nm = mt.name.to_s
      nm.start_with?('yz') || nm.start_with?('yingzao')
    end
  end
rescue StandardError
  false
end

n_before = m.entities.length
m.start_operation("yingzao: build #{MY}", true)
begin
  swept = []
  m.entities.grep(Sketchup::Group).each do |g|
    n = g.name.to_s
    if n == MY || (BAND < 0 && n.start_with?('yingzao-build')) || mine?(g)
      swept << (n.empty? ? '(无名组)' : n)
      g.erase!
    end
  end
  m.materials.purge_unused          # 顺手回收旧run 留下的孤儿材质（不被引用的才清）

  root = m.entities.add_group
  root.name = MY
  built = noface = bad_v = bad_f = miss = painted = 0
  missed = []
  maxd = 0.0            # 中点配对的最大偏差（mm）：这个数应该是 1e-3 量级
  verr = []
  act_vol = 0.0
  hist = Hash.new(0)
  t0 = Time.now

  sel.each_with_index do |pi, k|
    p = all[pi]
    g = root.entities.add_group
    unless prism(g.entities, p['ext'], p['holes'] || [], p['z0'], p['z1'])
      noface += 1
      g.erase! if g.valid?
      next
    end
    built += 1
    vol = (begin
      g.volume * (LEN2M**3)
    rescue StandardError
      nil
    end)
    act_vol += vol if vol
    if vol.nil? || (vol - p['vol']).abs > VOL_TOL
      bad_v += 1
      verr << [p['kind'], pi, vol && vol.round(4), p['vol']] if verr.length < 10
    end

    faces = g.entities.grep(Sketchup::Face)
    bad_f += 1 if faces.length != p['nf']
    capm = mat_of.call(p['cap'])
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
      # 逐边色表：环上第 i 条边 → [色, 外法向]，按中点分桶
      buckets = Hash.new { |h, kk| h[kk] = [] }
      rings = [[p['ext'], p['edgeCols'], p['edgeN']]]
      (p['holes'] || []).each_with_index do |ring, hi|
        rings << [ring, p['holeEdgeCols'][hi], p['holeEdgeN'][hi]]
      end
      rings.each do |pts, cols, norms|
        n = pts.length
        n.times do |i|
          a = pts[i]
          b = pts[(i + 1) % n]
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
              missed << [pi, p['kind'], [mx.round(2), my.round(2)]] if missed.length < 12
              next
            end
            maxd = bd if bd > maxd
            sf = e.faces.find { |x| x != bot && x.normal.z.abs <= 0.99 }
            next unless sf
            hex, nr = info
            front = hex
            back = other_color.call(hex)
            if sf.normal.x * nr[0] + sf.normal.y * nr[1] < 0   # SU 面法向与记录相反 → 换个侧
              front, back = back, front
            end
            sf.material = mat_of.call(front)
            sf.back_material = mat_of.call(back)
            painted += 1
            hist[front] += 1
          end
        end
      end
    end

    (g.explode rescue nil)               # 立刻并进 root：别让几千个组拖住 UI
    if ((k + 1) % 100).zero?
      el = Time.now - t0
      prog "  #{k + 1}/#{sel.length} 用时#{el.round(1)}s 预计#{(el / (k + 1) * sel.length).round}s"
    end
  end
  prog "建完 #{built} 件（noface #{noface} 体不符 #{bad_v} 面不符 #{bad_f} 边没认 #{miss} 上色 #{painted}）用时#{(Time.now - t0).round(1)}s"
  verr.each { |kd, i, got, want| prog "  x #{kd} ##{i} 体积 #{got} 应为 #{want}" }
ensure
  m.commit_operation
end

faces = root.entities.grep(Sketchup::Face)
bb = root.bounds
Sketchup.active_model.active_view.zoom_extents
prog "完成 面#{faces.length} 用时#{(Time.now - t0).round(1)}s"

{ 'band' => BAND, 'sel' => sel.length, 'built' => built, 'noface' => noface,
  'vol_bad' => bad_v, 'vol_err' => verr, 'faces_bad' => bad_f,
  'edge_miss' => miss, 'missed' => missed, 'maxd_mm' => maxd.round(5), 'painted' => painted,
  'exp_vol' => sel.sum { |i| all[i]['vol'] }.round(3), 'act_vol' => act_vol.round(3),
  'faces_after' => faces.length, 'colors' => hist.sort_by { |_, v| -v }[0, 10].to_h,
  'secs' => (Time.now - t0).round(1),
  'bbox' => [bb.min.x.to_m, bb.min.y.to_m, bb.min.z.to_m,
             bb.max.x.to_m, bb.max.y.to_m, bb.max.z.to_m].map { |v| v.round(3) } }
