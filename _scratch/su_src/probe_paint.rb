# -*- coding: utf-8 -*-
# 查「剖开以后某一片是黑的」：数一数到底有多少张面**两侧都没材质**（SU 就会拿默认
# 背面色画它），再按「竖面/盖面」和坐标范围分开报，并朝关键方向打射线看打到谁。
# 上一版只查了南立面外侧 —— 那一面是对的，问题在别处，所以要全模型普查 + 内部打射线。
m = Sketchup.active_model
root = m.entities.grep(Sketchup::Group).find { |g| g.name.to_s.start_with?('yingzao-build') }
return { 'err' => '没找到 yingzao-build 组' } unless root

faces = root.entities.grep(Sketchup::Face)
tot = faces.length
both_nil = []
vert_nil = 0
sample = []
faces.each do |f|
  next unless f.material.nil? && f.back_material.nil?

  both_nil << f
  if f.normal.z.abs <= 0.99
    vert_nil += 1
    if sample.length < 8
      c = f.bounds.center
      sample << { 'n' => [f.normal.x, f.normal.y, f.normal.z].map { |v| v.round(2) },
                  'c' => [c.x.to_m, c.y.to_m, c.z.to_m].map { |v| v.round(2) },
                  'a' => (f.area / (1.m * 1.m)).round(2) }
    end
  end
end

# 竖面里未上色的，按朝向分（朝外/朝内哪一边丢的）
by_n = Hash.new(0)
both_nil.each do |f|
  next if f.normal.z.abs > 0.99

  k = "#{f.normal.x.round(1)},#{f.normal.y.round(1)}"
  by_n[k] += 1
end

def hit(m, from, dir)
  res = m.raytest(from, dir)
  pt = nil
  path = []
  if res.is_a?(Array)
    res.each do |e|
      pt = e if e.is_a?(Geom::Point3d)
      path = e if e.is_a?(Array)
    end
  end
  f = path.find { |e| e.is_a?(Sketchup::Face) }
  return nil unless f

  d = dir
  dot = d.x * f.normal.x + d.y * f.normal.y + d.z * f.normal.z
  seen = dot < 0 ? f.material : f.back_material   # 从法向那侧看=正面材质
  {
    'pt' => pt && [pt.x.to_m, pt.y.to_m, pt.z.to_m].map { |v| v.round(2) },
    'n' => [f.normal.x, f.normal.y, f.normal.z].map { |v| v.round(2) },
    'front' => f.material && f.material.name, 'back' => f.back_material && f.back_material.name,
    'from_front' => dot < 0, 'seen' => seen && seen.name,
    'seen_rgb' => seen && [seen.color.red, seen.color.green, seen.color.blue]
  }
end

rays = []
[[0.0, -4.0], [-8.0, -4.0], [14.0, -4.0], [0.0, 10.0], [-8.0, 20.0]].each do |x, y|
  rays << ['北看', x, y, hit(m, Geom::Point3d.new(x.m, y.m, 2.0.m), Geom::Vector3d.new(0, 1, 0))]
  rays << ['南看', x, y, hit(m, Geom::Point3d.new(x.m, y.m, 2.0.m), Geom::Vector3d.new(0, -1, 0))]
end

{ 'faces' => tot, 'unpainted_both' => both_nil.length, 'unpainted_vert' => vert_nil,
  'unpainted_by_normal' => by_n.sort_by { |_, v| -v }[0, 12].to_h,
  'sample' => sample, 'rays' => rays }
