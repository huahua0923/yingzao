# -*- coding: utf-8 -*-
# 出图验收：轴测 / 南立面 / 顶视 / 剖切看内部，直接 view.write_image 写 PNG
# （不截屏：截屏要抢窗口焦点，写图不用）。
require 'json'

OUT = 'D:/gym3d/_scratch/'
m = Sketchup.active_model
v = m.active_view
root = m.entities.grep(Sketchup::Group).find { |g| g.name.to_s.start_with?('yingzao-build') }
return { 'err' => '没找到 yingzao-build 组' } unless root

bb = root.bounds
c = bb.center
r = [bb.width, bb.height, bb.depth].max
shots = []

def shoot(v, path, w = nil, h = nil)
  # 用**视口自己的宽高比**：write_image 是按视口渲染的，写死一个别的比例（原来 1400×1000
  # 对视口 1920×917）会让画面被裁掉两端 —— 南立面和顶视都少了半个楼。
  w ||= v.vpwidth
  h ||= v.vpheight
  v.write_image(path, w, h, true, 0.9)
  File.exist?(path) ? File.size(path) : -1
end

# 1 轴测（透视）
v.camera.perspective = true
v.camera.set(Geom::Point3d.new(c.x + r * 0.75, c.y - r * 1.15, c.z + r * 0.85), c,
             Geom::Vector3d.new(0, 0, 1))
v.zoom_extents
shots << ['iso', shoot(v, OUT + '_su_iso.png')]

# 2 南立面（正投影：立面不透视才好量比例）
v.camera.perspective = false
v.camera.set(Geom::Point3d.new(c.x, c.y - r * 3, c.z), Geom::Point3d.new(c.x, c.y, c.z),
             Geom::Vector3d.new(0, 0, 1))
v.zoom_extents
shots << ['south', shoot(v, OUT + '_su_south.png')]

# 3 顶视
v.camera.set(Geom::Point3d.new(c.x, c.y, c.z + r * 3), Geom::Point3d.new(c.x, c.y, c.z),
             Geom::Vector3d.new(0, 1, 0))
v.zoom_extents
shots << ['top', shoot(v, OUT + '_su_top.png')]

# 4 剖切：**切掉南半**，相机在南侧往北看，才能看进室内（内墙皮=室内色 / 楼梯踏步）。
# SU 的剖切面砍掉的是「法向指的那一侧」的反面 —— 上一版写 -y 时砍掉的是北半，
# 相机却站在南侧，于是拍到的是完好无损的南立面，等于没剖（实测就是这个坑）。
# 现在是 +y 法向 + 刀口在 c.y+1：南半被砍，镜头正对断面。
# ★ 剖切填充必须关掉：SU 2023 的 `SectionCutFilled` 默认开、填充色是
# `SectionDefaultFillColor = (63,63,63)` —— 剖切图里那片中性深灰就是它。查了半天
# 「是谁画的那片暗」：材质直方图 9 色全在调色板里、unpainted=0、逐色面积与交付 GLB
# 0.00% 吻合 —— 楼是对的，是 SU 自己拿 63,63,63 把断面糊住了。渲染选项枚举一下就现形。
v.camera.perspective = true
sp = nil
ro = m.rendering_options
sec_old = begin
  [ro['DisplaySectionCuts'], ro['DisplaySectionPlanes'], ro['SectionCutFilled']]
rescue StandardError
  [nil, nil, nil]
end
begin
  ro['DisplaySectionPlanes'] = false
  ro['SectionCutFilled'] = false
  ro['DisplaySectionCuts'] = true
rescue StandardError
  nil
end
begin
  m.start_operation('yingzao: section', true)
  sp = m.entities.add_section_plane([0.0, 1.0, 0.0, -(c.y + 1.0)])   # y - (c.y+1) = 0
  sp.activate if sp
  m.commit_operation
rescue StandardError => e
  shots << ['section_err', e.message]
end
if sp
  v.camera.set(Geom::Point3d.new(c.x + r * 0.5, c.y - r * 1.0, c.z + r * 0.55),
               Geom::Point3d.new(c.x, c.y + 1.0, c.z), Geom::Vector3d.new(0, 0, 1))
  v.zoom_extents
  shots << ['cut', shoot(v, OUT + '_su_cut.png')]
  m.start_operation('yingzao: section off', true)
  sp.erase!
  m.commit_operation
  # A/B：同一台相机、没有剖切面的一张。两张逐像素比 —— 那片深灰到底随剖切面消失
  # 不消失，比任何猜测都硬。（渲染选项 DisplaySectionPlanes 实测本来就是 false，
  # 改动它等于没改；而 pick_helper 照样挑得到剖切面，所以「挑到」不等于「画了」。）
  shots << ['cut_off', shoot(v, OUT + '_su_cutoff.png')]
end
begin
  ro['DisplaySectionPlanes'] = sec_old[1] unless sec_old[1].nil?
  ro['SectionCutFilled'] = sec_old[2] unless sec_old[2].nil?
rescue StandardError
  nil
end
shots << ['sec_opts_was', sec_old]

{ 'bbox' => [bb.min.x.to_m, bb.min.y.to_m, bb.min.z.to_m,
             bb.max.x.to_m, bb.max.y.to_m, bb.max.z.to_m].map { |x| x.round(2) },
  'faces' => root.entities.grep(Sketchup::Face).length,
  'groups_in_model' => m.entities.grep(Sketchup::Group).map(&:name),
  'shots' => shots }
