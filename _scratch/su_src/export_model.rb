# -*- coding: utf-8 -*-
# 把当前整栋楼导成可供 Blender 转 GLB 的中间格式（dae/fbx/obj 各来一份，比谁的颜色保得住）。
# SU 2023 没有 glb/gltf 原生导出（实测 ArgumentError: Unsupported file extension），
# 所以只能走中间格式；颜色要能过这一关，才能进前端。
OUT = 'D:/gym3d/_scratch/_su_export'
m = Sketchup.active_model
Dir.mkdir(OUT) unless Dir.exist?(OUT)

n_faces = m.entities.grep(Sketchup::Group).sum { |g| g.definition.entities.grep(Sketchup::Face).length }
res = { 'n_faces' => n_faces, 'pid' => Process.pid, 'out' => {} }
%w[dae fbx obj].each do |ext|
  p = File.join(OUT, "ny27_su.#{ext}")
  File.delete(p) if File.exist?(p)
  t0 = Time.now
  begin
    m.export(p, {})
    res['out'][ext] = { 'size' => (File.exist?(p) ? File.size(p) : nil),
                        'secs' => (Time.now - t0).round(1), 'err' => nil }
  rescue StandardError => e
    res['out'][ext] = { 'size' => nil, 'secs' => (Time.now - t0).round(1),
                        'err' => "#{e.class}: #{e.message}" }
  end
  # OBJ 的伴随文件也留着（转换时要用）
  mtl = File.join(OUT, 'ny27_su.mtl')
  res['out'][ext]['mtl'] = File.exist?(mtl) ? File.size(mtl) : nil
end
res
