# -*- coding: utf-8 -*-
# 逐格式试导出，把 SU 2023 真正支持的三维格式问出来（不猜版本特性）。
# 只导出到 _scratch/_su_export/ 下的临时文件，跑完删掉，不动用户模型。
#
# ★ 模型为空时要先放一个临时方块：空模型下有些导出器（OBJ 之类）会「不生成文件」，
#   那和「扩展名不支持」长得一模一样，都会得到 no-file —— 分不清就会误判成不支持。
#   所以先保证有几何，跑完把方块擦掉。
m = Sketchup.active_model
dir = 'D:/gym3d/_scratch/_su_export'
Dir.mkdir(dir) unless Dir.exist?(dir)

n_faces_before = m.entities.grep(Sketchup::Face).length +
                 m.entities.grep(Sketchup::Group).sum { |g| g.definition.entities.grep(Sketchup::Face).length }
tmp_grp = nil
if n_faces_before.zero?
  m.start_operation('yingzao: probe cube', true)
  tmp_grp = m.entities.add_group
  tmp_grp.entities.add_face([0, 0, 0], [1.m, 0, 0], [1.m, 1.m, 0], [0, 1.m, 0]).pushpull(1.m)
  m.commit_operation
end
res = { 'empty_before' => n_faces_before.zero?, 'n_faces_before' => n_faces_before }
out = {}
%w[glb gltf dae obj fbx stl 3ds wrl xsi ifc dwg dxf kmz pdf png].each do |ext|
  p = File.join(dir, "_probe.#{ext}")
  File.delete(p) if File.exist?(p)
  begin
    m.export(p, {})
    sz = File.exist?(p) ? File.size(p) : nil
    out[ext] = sz ? "OK #{sz}B" : 'no-file'
  rescue StandardError => e
    out[ext] = "#{e.class}: #{e.message}"
  end
  File.delete(p) if File.exist?(p)
  # 随附文件（.mtl / .dae 贴图目录 / .obj 等）
  %w[_probe.mtl].each do |f|
    fp = File.join(dir, f)
    File.delete(fp) if File.exist?(fp)
  end
end
if tmp_grp
  m.start_operation('yingzao: probe cube off', true)
  tmp_grp.erase!
  m.commit_operation
end
res['formats'] = out
res['unit'] = m.options['UnitsOptions']['LengthUnit']
res['faces_after'] = m.entities.grep(Sketchup::Face).length +
                     m.entities.grep(Sketchup::Group).sum { |g| g.definition.entities.grep(Sketchup::Face).length }
res
