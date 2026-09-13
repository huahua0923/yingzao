# -*- coding: utf-8 -*-
# 导「只有楼」的 OBJ：文档里还有 SU 自带的比例人偶（组件定义 Heather，88 面、1.63m 高，
# 不是我建的），先把它隐藏再导；导完立刻恢复可见性（不改用户的东西）。
# 导完自己读一遍 OBJ/MTL 里有没有 Heather_/Lily_ —— 隐藏到底算不算数，让文件自己回答。
# ★ SU 的 OBJ 是**英寸数值**（文件头写着 File units = inches），转换侧要 global_scale=0.0254。
OUT = 'D:/gym3d/_scratch/_su_export'
m = Sketchup.active_model
Dir.mkdir(OUT) unless Dir.exist?(OUT)

insts = m.entities.grep(Sketchup::ComponentInstance)
was = insts.map { |i| begin; i.hidden?; rescue StandardError; nil; end }
insts.each { |i| begin; i.hidden = true; rescue StandardError; nil; end }

obj = File.join(OUT, 'ny27_bldg.obj')
File.delete(obj) if File.exist?(obj)
t0 = Time.now
res = { 'n_instances_hidden' => insts.length, 'secs' => nil }
begin
  m.export(obj, {})
rescue StandardError => e
  res['err'] = "#{e.class}: #{e.message}"
end
res['secs'] = (Time.now - t0).round(1)

insts.each_with_index { |i, k| begin; i.hidden = was[k]; rescue StandardError; nil; end }

mtl = File.join(OUT, 'ny27_bldg.mtl')
res['obj_size'] = File.exist?(obj) ? File.size(obj) : nil
res['mtl_size'] = File.exist?(mtl) ? File.size(mtl) : nil
if File.exist?(obj)
  txt = File.read(obj, mode: 'rb')
  res['obj_has_heather'] = txt.include?('Heather')
  res['obj_has_lily'] = txt.include?('Lily')
  res['usemtl_lines'] = txt.scan(/^usemtl (.+)$/).flatten.uniq.sort
  res['units_line'] = txt[/^#\s*File units.*$/]
  res['n_verts'] = txt.scan(/^v /).length
  res['n_faces'] = txt.scan(/^f /).length
end
if File.exist?(mtl)
  mt = File.read(mtl, mode: 'rb')
  res['mtl_has_heather'] = mt.include?('Heather')
  res['mtl_materials'] = mt.scan(/^newmtl (.+)$/).flatten
end
res['pid'] = Process.pid
res
