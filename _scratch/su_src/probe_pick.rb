# -*- coding: utf-8 -*-
# 「剖切图里那片中性深灰 (63,63,63) 是谁」——调色板里没有中性灰，所以它大概率不是
# 上了色的面，而是渲染元素（背景/地面/剖切填充）。用 PickHelper 在**同样的相机 + 同样的
# 剖切**下逐像素去挑：挑到面就报面的材质，挑不到就说明那儿没有几何体。
#
# 关键：必须自己重建 shot 时的相机与剖切（shots.rb 跑完把剖切面删了、相机也留在最后
# 那张图上），否则问的是「剖切复原后的楼」，答非所问。
m = Sketchup.active_model
v = m.active_view
root = m.entities.grep(Sketchup::Group).find { |g| g.name.to_s.start_with?('yingzao-build') }
return { 'err' => '没找到 yingzao-build 组' } unless root

bb = root.bounds
c = bb.center
r = [bb.width, bb.height, bb.depth].max

m.start_operation('yingzao: probe pick', true)
sp = m.entities.add_section_plane([0.0, 1.0, 0.0, -(c.y + 1.0)])
sp.activate if sp
m.commit_operation

v.camera.perspective = true
v.camera.set(Geom::Point3d.new(c.x + r * 0.5, c.y - r * 1.0, c.z + r * 0.55),
             Geom::Point3d.new(c.x, c.y + 1.0, c.z), Geom::Vector3d.new(0, 0, 1))
v.zoom_extents

W = 1400.0
H = 1000.0
sx = v.vpwidth / W
sy = v.vpheight / H

pts = [[700, 500], [800, 600], [900, 400], [1000, 700], [600, 450], [1100, 550],
       [200, 400], [1250, 500], [400, 800], [700, 900]]
out = []
pts.each do |px, py|
  ph = v.pick_helper
  ph.do_pick(px * sx, py * sy)
  best = ph.best_picked
  f = nil
  begin
    f = ph.picked_face
  rescue StandardError
    nil
  end
  out << {
    'px' => [px, py],
    'best' => best ? best.class.to_s.split('::').last : nil,
    'face_mat' => f && f.material && f.material.name,
    'face_back' => f && f.back_material && f.back_material.name,
    'depth' => (ph.depth_at(0) rescue nil),
    'pt' => (best.respond_to?(:position) ? [best.position.x.to_m, best.position.y.to_m, best.position.z.to_m].map { |z| z.round(2) } : nil)
  }
end

m.start_operation('yingzao: probe pick off', true)
sp.erase! if sp
m.commit_operation

{ 'vp' => [v.vpwidth, v.vpheight], 'pick' => out }
