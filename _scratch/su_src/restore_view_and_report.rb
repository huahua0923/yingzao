# -*- coding: utf-8 -*-
# 两件事，一件是补救、一件是必答的问题：
#  1) 补救：上一版探针里 `av.camera = want` 连带把 `orig` 也改了（View#camera 返回**活引用**
#     不是副本），所以 ensure 里那份"还原"用的是被污染的值，把用户视口停在了 (0,0,5)。
#     这里按探针记下的原始 eye 还原。教训已记：改相机前必须先把 eye/target/up 抄成纯数值。
#  2) 必答：当前文档里是什么？`model_path` 报"(未保存)"、顶层实体只有 2 个 ——
#     既可能是空文档，也可能是 ny27 那栋楼（build_model.rb 把 2759 件 explode 进**一个** root 组，
#     顶层本来就只有 1 个组）。这决定建理化楼前要不要先 File → New，必须如实看清再问。
M2 = 0.0254
m = Sketchup.active_model
av = m.active_view
R = {}

# ---------- 1) 还原视口（原始 eye，探针记的 [37.3, -50.88, 18.57] m，透视）----------
begin
  cam = Sketchup::Camera.new(Geom::Point3d.new(37.3.m, -50.88.m, 18.57.m),
                             Geom::Point3d.new(0, 0, 0),
                             Geom::Vector3d.new(0, 0, 1))
  av.camera = cam
  (av.camera.perspective = true) rescue nil
  R['view_restored_eye_m'] = av.camera.eye.to_a.map { |v| (v * M2).round(2) }
  R['view_perspective'] = (av.camera.perspective? rescue 'n/a')
rescue => e
  R['restore_err'] = "#{e.class}: #{e.message}"
end

# ---------- 2) 文档里到底有什么（只读）----------
R['model_path'] = (m.path.to_s.empty? ? '(未保存)' : m.path.to_s)
R['title'] = (m.title rescue 'n/a')
R['modified'] = (m.modified? rescue 'n/a')
R['entities_count'] = m.entities.count
R['pages_count'] = m.pages.count
R['layers'] = m.layers.map { |x| x.name }
R['materials_count'] = m.materials.count
R['materials_names'] = (m.materials.map { |x| x.name } rescue 'n/a')

# 顶层实体逐条：类/名/所属层/包围盒（米）/体积（m³）
items = []
m.entities.each do |e|
  it = { 'class' => e.class.to_s }
  it['name'] = (e.respond_to?(:name) ? e.name.to_s : nil)
  it['layer'] = (e.respond_to?(:layer) && e.layer ? e.layer.name : nil)
  begin
    bb = e.bounds
    it['bbox_m'] = [bb.min.to_a, bb.max.to_a].map { |p| p.map { |v| (v * M2).round(3) } }
  rescue => ex
    it['bbox_err'] = ex.class.to_s
  end
  begin
    it['volume_m3'] = e.volume.round(4) if e.respond_to?(:volume)
  rescue => ex
    it['volume_err'] = ex.class.to_s
  end
  it['typename'] = (e.typename rescue nil)
  items << it
end
R['top_entities'] = items

# 递归数一下组/组件总数（ny27 那种规模会是几千）
begin
  n = 0
  stack = m.entities.to_a
  until stack.empty?
    e = stack.pop
    n += 1
    if e.respond_to?(:definition) && e.definition.respond_to?(:entities)
      stack.concat(e.definition.entities.to_a)
    end
  end
  R['recursive_entity_count'] = n
rescue => e
  R['recursive_err'] = "#{e.class}: #{e.message}"
end
R
