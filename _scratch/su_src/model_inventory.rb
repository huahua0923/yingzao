# -*- coding: utf-8 -*-
# 盘库存：模型里到底有什么（顶层组/散面/组件实例）、材质清单里哪些**真被面用着**。
# 起因：导出的 OBJ 里出现了 1 米见方的面（疑似探针方块没擦掉）和 Heather_/Lily_ 这类
# SU 自带人物组件的材质名 —— 交付前必须分清「真在模型里」和「只是材质表里的孤儿」。
m = Sketchup.active_model

def faces_under(ents)
  n = ents.grep(Sketchup::Face).length
  ents.grep(Sketchup::Group).each { |g| n += faces_under(g.entities) }
  n
end

top = m.entities
used = Hash.new(0)      # 面真正用到的材质（含背面）
bb_all = nil
m.entities.grep(Sketchup::Group).each { |g| bb_all = bb_all ? bb_all.add(g.bounds) : g.bounds }

groups = m.entities.grep(Sketchup::Group).map do |g|
  used_here = Hash.new(0)
  walk = lambda do |ents|
    ents.grep(Sketchup::Face).each do |f|
      [f.material, f.back_material].compact.each { |mt| used_here[mt.name] += 1 }
    end
    ents.grep(Sketchup::Group).each { |gg| walk.call(gg.entities) }
  end
  walk.call(g.entities)
  used_here.each { |k, v| used[k] += v }
  { 'name' => g.name, 'nested_groups' => g.entities.grep(Sketchup::Group).length,
    'faces' => faces_under(g.entities),
    'bbox_m' => [g.bounds.min.x.to_m, g.bounds.min.y.to_m, g.bounds.min.z.to_m,
                 g.bounds.max.x.to_m, g.bounds.max.y.to_m, g.bounds.max.z.to_m].map { |x| x.round(2) },
    'mats' => used_here.keys.sort }
end

{
  'pid' => Process.pid,
  'top_groups' => groups,
  'loose_faces_top' => top.grep(Sketchup::Face).length,
  'loose_edges_top' => top.grep(Sketchup::Edge).length,
  'component_instances_top' => top.grep(Sketchup::ComponentInstance).length,
  'images_top' => top.grep(Sketchup::Image).length,
  'materials_all' => m.materials.map(&:name).sort,
  'materials_used' => used.keys.sort,
  'materials_orphan' => m.materials.map(&:name).sort - used.keys.sort,
  'faces_total' => faces_under(m.entities),
  'bbox_m' => bb_all ? [bb_all.min.x.to_m, bb_all.min.y.to_m, bb_all.min.z.to_m,
                        bb_all.max.x.to_m, bb_all.max.y.to_m, bb_all.max.z.to_m].map { |x| x.round(2) } : nil
}
