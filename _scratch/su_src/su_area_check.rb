# -*- coding: utf-8 -*-
# SU 当基准：逐材质的**正面/背面**面积（SU 自己算的 face.area，不走导出器，不经过三角化）。
# 用途：判断「面积差」到底出在 SU 导出、Blender 转换，还是交付 GLB 本身。
# 面积一律换算成平方米（SU 内部是英寸，1 in = 0.0254 m）。
M2 = 0.0254 * 0.0254
m = Sketchup.active_model
front = Hash.new(0.0)
back = Hash.new(0.0)
nfront = Hash.new(0)
nback = Hash.new(0)
total = 0.0
nfaces = 0

walk = lambda do |ents|
  ents.grep(Sketchup::Face).each do |f|
    a = f.area * M2
    total += a
    nfaces += 1
    if f.material
      front[f.material.name] += a
      nfront[f.material.name] += 1
    else
      front['(无)'] += a
      nfront['(无)'] += 1
    end
    if f.back_material
      back[f.back_material.name] += a
      nback[f.back_material.name] += 1
    else
      back['(无)'] += a
      nback['(无)'] += 1
    end
  end
  ents.grep(Sketchup::Group).each { |g| walk.call(g.entities) }
  ents.grep(Sketchup::ComponentInstance).each { |i| walk.call(i.definition.entities) }
end
walk.call(m.entities)

{ 'pid' => Process.pid,
  'n_faces' => nfaces,
  'total_m2' => total.round(1),
  'front' => front.map { |k, v| [k, v.round(1), nfront[k]] }.sort_by { |x| -x[1] },
  'back' => back.map { |k, v| [k, v.round(1), nback[k]] }.sort_by { |x| -x[1] } }
