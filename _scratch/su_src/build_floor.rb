# -*- coding: utf-8 -*-
# 在 SU 里盖一层楼：读 Python 备好的 spec（多边形运算已在 shapely 里做完），
# 这里只做 add_face + pushpull + 逐面侧上色 —— SU 侧零布尔运算，不冻 UI。
#
# 关键：**每个挤出体在独立组里建，建完当场量体积对账**。同组里相邻高度带的顶面/
# 底面完全重合（都画在同一 z 的同一圈上），SU 会把 pushpull 作用到那张已有面上、
# 把下面的体扯开（实测丢 4.9% 材料）。独立组里建就不会撞上别人的重合面。
#
# 本文件是**源**：改完 `mv` 到 _scratch/su_jobs/ 投递（桥跑完即删任务文件）。
# 用法：spec 路径经环境变量 YZ_SPEC 传（桥是 eval 进来的，没有 $ARGV）。
require 'json'

SPEC = ENV['YZ_SPEC'] || 'D:/gym3d/_scratch/su_jobs/_ny27_f2_spec.json'
PROG = 'D:/gym3d/_scratch/su_jobs/_progress.txt'
VOL_TOL = 0.001        # m³ 允许误差
# SU 的 Group#volume 按「模型单位」的三次方返回。本例模型单位是英寸，
# 直接跟 m³ 比会得到 25463091 vs 417 的假警报 —— 按 LengthUnit 折算。
LEN_TO_M = { 0 => 0.0254, 1 => 0.3048, 2 => 0.001, 3 => 0.01, 4 => 1.0 }.freeze

def prog(s)
  File.open(PROG, 'a') { |f| f.puts("#{Time.now.strftime('%H:%M:%S')} #{s}") }
rescue StandardError
  nil
end

# 建一个「带洞的棱柱」。外环 add_face → 内环各 add_face 后抹掉（留洞）→ pushpull。
# 返回 :ok / :noface；SU 建不出面（自交/退化）时如实返回，不假装成功。
def prism(ents, ext, holes, z0, z1)
  f = ents.add_face(ext.map { |x, y| Geom::Point3d.new(x.m, y.m, z0.m) })
  return :noface if f.nil?

  holes.each do |h|
    hf = ents.add_face(h.map { |x, y| Geom::Point3d.new(x.m, y.m, z0.m) })
    hf.erase! if hf && !hf.deleted?        # 抹掉洞面 → 外环留下内环
  end
  f.reverse! if f.normal.z < 0             # 保证沿 +Z 挤出
  f.pushpull((z1 - z0).m)
  :ok
rescue StandardError
  :noface
end

spec = JSON.parse(File.read(SPEC, mode: 'rb').force_encoding('UTF-8'))
m = Sketchup.active_model
File.delete(PROG) if File.exist?(PROG)
prog "spec=#{spec['name']} 体#{1 + spec['prisms'].length}"

u = m.options['UnitsOptions']['LengthUnit']
LEN2M = LEN_TO_M[u] || 1.0
prog "模型长度单位=#{u} 折算#{LEN2M}"

# ---- 平面点在轮廓内？（判面朝外/朝内用）----
OL = spec['slab']['ext']
def inside?(x, y)
  c = false
  n = OL.length
  (0...n).each do |i|
    x1, y1 = OL[i]
    x2, y2 = OL[(i + 1) % n]
    if ((y1 > y) != (y2 > y)) && (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1)
      c = !c
    end
  end
  c
end

n_before = m.entities.length
mat_f = m.materials['yingzao_facade'] || m.materials.add('yingzao_facade')
mat_f.color = Sketchup::Color.new(95, 22, 12)
mat_i = m.materials['yingzao_inner'] || m.materials.add('yingzao_inner')
mat_i.color = Sketchup::Color.new(159, 149, 130)
mat_s = m.materials['yingzao_slab'] || m.materials.add('yingzao_slab')
mat_s.color = Sketchup::Color.new(214, 202, 183)

m.start_operation('yingzao: build floor', true)
# 只删「我上次建的那个组」，不动用户模型里任何别的东西
m.entities.grep(Sketchup::Group).select { |g| g.name == 'yingzao-build' }.each(&:erase!)
groups = []
bad_v = bad_f = noface = 0
verr = []
t0 = Time.now
begin
  root = m.entities.add_group
  root.name = 'yingzao-build'
  ([spec['slab']] + spec['prisms']).each_with_index do |p, i|
    g = root.entities.add_group
    if prism(g.entities, p['ext'], p['holes'] || [], p['z0'], p['z1']) != :ok
      noface += 1
      g.erase! if g.valid?
      next
    end
    vol = (g.respond_to?(:volume) ? (begin
                                       g.volume * (LEN2M**3)
                                     rescue StandardError
                                       nil
                                     end) : nil)
    if vol.nil? || (vol - p['vol']).abs > VOL_TOL
      bad_v += 1
      verr << [p['wallId'] || 'slab', i, vol && vol.round(4), p['vol']] if verr.length < 8
    end
    nf = g.entities.grep(Sketchup::Face).length
    bad_f += 1 if nf != p['nf']
    g.entities.grep(Sketchup::Face).each do |f|
      if i.zero?                                     # 楼板整块一个色
        f.material = mat_s
        next
      end
      if f.normal.z.abs > 0.99                       # 墙的上下盖面
        f.material = mat_f
        next
      end
      c = f.bounds.center
      out = !inside?(c.x.to_m + f.normal.x * 0.06, c.y.to_m + f.normal.y * 0.06)
      f.material = out ? mat_f : mat_i
      f.back_material = out ? mat_i : mat_f
    end
    groups << [g, p]
  end
  prog "建完+对账 #{groups.length} 体（noface #{noface} 体积不符 #{bad_v} 面数不符 #{bad_f}）用时#{(Time.now - t0).round(2)}s"
  verr.each { |w, i, got, want| prog "  ✗ #{w} ##{i} 体积 #{got} 应为 #{want}" }

  groups.each { |g, _| (g.explode rescue nil) }        # 合并进 root
  prog "已合并进一个组"
ensure
  m.commit_operation
end

faces = root.entities.grep(Sketchup::Face)
bb = root.bounds
exp_vol = spec['slab']['vol'] + spec['prisms'].sum { |q| q['vol'] }
Sketchup.active_model.active_view.zoom_extents
prog "完成 面#{faces.length} 用时#{(Time.now - t0).round(1)}s"

{ 'prisms' => groups.length, 'noface' => noface,
  'vol_bad' => bad_v, 'vol_err' => verr, 'faces_bad' => bad_f,
  'exp_vol' => exp_vol.round(4),
  'faces_after_explode' => faces.length,
  'entities_added' => m.entities.length - n_before,
  'bbox' => [bb.min.x.to_m, bb.min.y.to_m, bb.min.z.to_m, bb.max.x.to_m, bb.max.y.to_m, bb.max.z.to_m].map { |v| v.round(3) } }
