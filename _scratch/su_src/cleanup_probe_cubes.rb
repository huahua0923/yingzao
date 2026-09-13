# -*- coding: utf-8 -*-
# 扫掉探针留下的方块：判据卡死 —— 顶层组 + 组名为空 + 恰好 6 面 + 所有面无材质/无背材质
# + 三个方向尺寸都 ≤1.01m + 整块落在 [-1.01, 1.01] 里。用户自己的几何不可能同时满足，
# 每擦一个都把 bbox 报出来备查；顺手把那个顶层组件实例是什么也报出来（先不动它）。
m = Sketchup.active_model
LIMIT = 1.01.m

swept = []
m.entities.grep(Sketchup::Group).each do |g|
  next unless g.name.to_s.empty?
  faces = g.entities.grep(Sketchup::Face)
  next unless faces.length == 6
  next unless faces.all? { |f| f.material.nil? && f.back_material.nil? }
  b = g.bounds
  next unless [b.width, b.height, b.depth].all? { |d| d <= LIMIT }
  next unless [b.min.x, b.min.y, b.min.z, b.max.x, b.max.y, b.max.z].all? { |c| c.abs <= LIMIT }
  swept << [b.min.x.to_m, b.min.y.to_m, b.min.z.to_m, b.max.x.to_m, b.max.y.to_m, b.max.z.to_m].map { |x| x.round(2) }
  g.erase!
end

insts = m.entities.grep(Sketchup::ComponentInstance).map do |i|
  b = i.bounds
  mats = []
  walk = lambda do |ents|
    ents.grep(Sketchup::Face).each { |f| [f.material, f.back_material].compact.each { |mt| mats << mt.name } }
    ents.grep(Sketchup::Group).each { |gg| walk.call(gg.entities) }
    ents.grep(Sketchup::ComponentInstance).each { |ii| walk.call(ii.definition.entities) }
  end
  walk.call(i.definition.entities)
  { 'name' => i.name, 'definition' => i.definition.name,
    'faces_in_def' => i.definition.entities.grep(Sketchup::Face).length,
    'mats' => mats.uniq.sort,
    'bbox_m' => [b.min.x.to_m, b.min.y.to_m, b.min.z.to_m, b.max.x.to_m, b.max.y.to_m, b.max.z.to_m].map { |x| x.round(2) } }
end

{ 'swept_count' => swept.length, 'swept_bboxes' => swept,
  'instances' => insts, 'pid' => Process.pid,
  'groups_left' => m.entities.grep(Sketchup::Group).map { |g| [g.name, g.definition.entities.grep(Sketchup::Face).length] },
  'loose_faces_top' => m.entities.grep(Sketchup::Face).length }
