# -*- coding: utf-8 -*-
# 只读探针：把某个楼层组的**每个面**列出来（材质 / 面积 / 法向 / 中心 / 边数 / Tag）。
#
# 为什么需要它：逐色面积对账对不上时（屋顶组少了 921.3 m² = 正好一块盖面），
# 光看合计永远猜不出是「面被合并了」还是「面压根没建」。15 个面全列出来，一眼就能定性。
require 'json'

m = Sketchup.active_model
u = m.options['UnitsOptions']['LengthUnit']
LEN2M = { 0 => 0.0254, 1 => 0.3048, 2 => 0.001, 3 => 0.01, 4 => 1.0 }[u] || 1.0
GNAME = ENV['YZ_GROUP'] || 'yingzao-屋顶'
g = m.entities.grep(Sketchup::Group).find { |x| x.name.to_s == GNAME }

# 二级组之后面在**子组**里，必须递归（不递归只会得到 0 个面）
def all_faces(ents)
  fs = ents.grep(Sketchup::Face)
  ents.grep(Sketchup::Group).each { |gg| fs.concat(all_faces(gg.entities)) }
  fs
end

R = { 'group' => GNAME, 'found' => !g.nil? }
if g
  R['subs'] = g.entities.grep(Sketchup::Group).map { |sg|
    [sg.name, all_faces(sg.entities).length, (sg.layer.name rescue nil)]
  }
  fs = all_faces(g.entities)
  R['faces_n'] = fs.length
  R['faces'] = fs.map do |f|
    c = f.bounds.center
    n = f.normal
    { 'mat' => (f.material ? f.material.name : nil),
      'back' => (f.back_material ? f.back_material.name : nil),
      'area_m2' => (f.area * (LEN2M**2)).round(3),
      'n' => [n.x, n.y, n.z].map { |v| v.round(3) },
      'c' => [c.x.to_m, c.y.to_m, c.z.to_m].map { |v| v.round(3) },
      'edges' => f.edges.length,
      'tag' => (f.layer.name rescue nil) }
  end
  by = Hash.new(0.0)
  fs.each { |f| by[f.material ? f.material.name : '<无>'] += f.area * (LEN2M**2) }
  R['area_by_mat_m2'] = by.map { |k, v| [k, v.round(3)] }.sort_by { |_, v| -v }.to_h
end
R['done'] = true
R
