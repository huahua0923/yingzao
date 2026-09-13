# 给当前模型一个好看的等轴测视角（顺着建筑长轴斜看）
v = Sketchup.active_model.active_view
bb = Sketchup.active_model.bounds
c = bb.center
r = [bb.width, bb.height, bb.depth].max.to_m
v.camera.set(Geom::Point3d.new(c.x + r * 0.75, c.y - r * 1.15, c.z + r * 0.85),
             Geom::Point3d.new(c.x, c.y, c.z), Geom::Vector3d.new(0, 0, 1))
v.zoom_extents
"cam=(#{[v.camera.eye.x.to_m, v.camera.eye.y.to_m, v.camera.eye.z.to_m].map { |x| x.round(1) }.join(', ')}) r=#{r.round(1)}"
