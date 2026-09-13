# -*- coding: utf-8 -*-
# 「剖开以后有一片是暗的」第二问：不是漏上色（unpainted=0），那就是上成了别的色。
# 全模型面材质直方图 + 每种材质的包围盒/总面积 —— 一眼看出那片暗到底是谁。
m = Sketchup.active_model
root = m.entities.grep(Sketchup::Group).find { |g| g.name.to_s.start_with?('yingzao-build') }
return { 'err' => '没找到 yingzao-build 组' } unless root

faces = root.entities.grep(Sketchup::Face)
h = Hash.new { |hh, k| hh[k] = { 'n' => 0, 'area' => 0.0, 'vert' => 0,
                                'bb' => [1e9, 1e9, 1e9, -1e9, -1e9, -1e9] } }
faces.each do |f|
  nm = (f.material && f.material.name) || '(nil)'
  e = h[nm]
  e['n'] += 1
  e['area'] = (e['area'] + f.area / (1.m * 1.m)).round(3)
  e['vert'] += 1 if f.normal.z.abs <= 0.99
  c = f.bounds
  bb = e['bb']
  bb[0] = [bb[0], c.min.x.to_m].min
  bb[1] = [bb[1], c.min.y.to_m].min
  bb[2] = [bb[2], c.min.z.to_m].min
  bb[3] = [bb[3], c.max.x.to_m].max
  bb[4] = [bb[4], c.max.y.to_m].max
  bb[5] = [bb[5], c.max.z.to_m].max
end

colors = {}
h.each_key do |nm|
  mt = m.materials[nm]
  colors[nm] = mt && [mt.color.red, mt.color.green, mt.color.blue]
end

# 后侧单独一列（有没有「正面= X 背面= Y」这种不对称没被配平）
back = Hash.new(0)
faces.each { |f| back[(f.back_material && f.back_material.name) || '(nil)'] += 1 }

{ 'faces' => faces.length,
  'front' => h.sort_by { |_, v| -v['n'] }.map { |k, v| [k, v['n'], v['area'], v['vert'], v['bb'].map { |x| x.round(2) }] },
  'back' => back.sort_by { |_, v| -v }.to_h,
  'rgb' => colors }
