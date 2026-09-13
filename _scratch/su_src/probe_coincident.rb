# -*- coding: utf-8 -*-
# 只读探针（跑完 abort_operation，模型不留痕）：SU 到底怎么处理**共面重合**的面？
#
# 为什么问这个：理化楼实测「屋面板的下盖面整块不见了（921.3 m²）」「每层楼板的下盖面也不见了」，
# 猜测是 SU 在**同一个容器**里遇到共面重合的面会合并、并把旧的整块删掉。猜不能当结论，
# 这里做三个受控实验（每例都在自己的新组里建，互不干扰）：
#   例1 同平面画大面 + 里面套小面        → 大面还在吗？（面数 / 面积 / 材质）
#   例2 两块**互相穿插**的盒子（墙脚扎进楼板 0.2 m）→ 楼板下盖面还在吗？
#   例3 两块**只贴着不穿插**的盒子（墙坐在楼板上）  → 楼板下盖面还在吗？
# 结论直接决定「楼板/屋顶该怎么建」：能不能把所有部件 explode 进同一个组。
require 'json'

IN2M2 = 0.0254 * 0.0254
m = Sketchup.active_model
mm = lambda { |n| m.materials[n] || m.materials.add(n) }
R = {}

def stats(e)
  fs = e.grep(Sketchup::Face)
  by = Hash.new(0.0)
  fs.each { |f| by[f.material ? f.material.name : '<无>'] += f.area * IN2M2 }
  { 'faces' => fs.length,
    'area_m2' => (fs.sum { |f| f.area } * IN2M2).round(3),
    'by_mat' => by.map { |k, v| [k, v.round(3)] }.sort_by { |_, v| -v }.to_h,
    'z_of_faces' => fs.map { |f| f.bounds.center.z.to_m.round(3) }.sort }
end

def box(e, x0, y0, x1, y1, z0, z1, mat)
  # 六个面：只建盖面 + 侧壁，跟 build_floors 的做法同构
  pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
  lo = pts.map { |x, y| [x, y, z0] }
  hi = pts.map { |x, y| [x, y, z1] }
  f = e.add_face(lo)
  f.material = mat; f.back_material = mat
  f2 = e.add_face(hi.reverse)
  f2.material = mat; f2.back_material = mat
  4.times do |i|
    j = (i + 1) % 4
    sf = e.add_face([lo[i], lo[j], hi[j], hi[i]])
    next unless sf
    sf.material = mat; sf.back_material = mat
  end
end

m.start_operation('probe-coincident', true)
begin
  # 例1：共面套面
  g1 = m.entities.add_group
  e1 = g1.entities
  a = e1.add_face([0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0])
  a.material = mm.call('pA'); a.back_material = a.material
  R['1_after_big'] = stats(e1)
  b = e1.add_face([3, 3, 0], [7, 3, 0], [7, 7, 0], [3, 7, 0])
  b.material = mm.call('pB'); b.back_material = b.material
  R['1_after_small'] = stats(e1)
  R['1_note'] = '大面 100 + 小面 16；若面积=100 说明大面被小面顶掉（不是加成 116）'

  # 例2：互相穿插（墙脚扎进楼板 0.2）—— 楼板 z  0..0.2，墙 z 0..4.2
  g2 = m.entities.add_group
  e2 = g2.entities
  box(e2, 0, 0, 10, 10, 0.0, 0.2, mm.call('slab2'))
  R['2_after_slab'] = stats(e2)
  box(e2, 2, 0, 3, 10, 0.0, 4.2, mm.call('wall2'))
  R['2_after_wall'] = stats(e2)
  R['2_note'] = '楼板下盖面 100 m² 是「多出来的」还是被墙的下盖面顶掉？'

  # 例3：只贴着（墙坐在楼板上）—— 楼板 0..0.2，墙 0.2..4.2
  g3 = m.entities.add_group
  e3 = g3.entities
  box(e3, 0, 0, 10, 10, 0.0, 0.2, mm.call('slab3'))
  R['3_after_slab'] = stats(e3)
  box(e3, 2, 0, 3, 10, 0.2, 4.2, mm.call('wall3'))
  R['3_after_wall'] = stats(e3)
  R['3_note'] = '贴着建，楼板的上/下盖面还在吗？'

  R['done'] = true
ensure
  m.abort_operation          # 单步回滚：模型回到探针之前，什么都不留
end
R
