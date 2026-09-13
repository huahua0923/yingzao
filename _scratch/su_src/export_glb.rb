# -*- coding: utf-8 -*-
# 「SU 2023 能不能直接导出 GLB」不猜，试一次：Model#export 到 .glb，
# 成功就把文件留下（下一步用 Python 量它的包围盒/颜色，判断单位与轴向是否可直接给前端用）。
m = Sketchup.active_model
dir = 'D:/gym3d/_scratch/_su_export'
Dir.mkdir(dir) unless Dir.exist?(dir)
out = File.join(dir, 'ny27_su.glb')
File.delete(out) if File.exist?(out)

res = { 'path' => out }
t0 = Time.now
begin
  res['ret'] = m.export(out, {}).inspect
rescue StandardError => e
  res['err'] = "#{e.class}: #{e.message}"
end
res['exists'] = File.exist?(out)
res['size'] = res['exists'] ? File.size(out) : nil
res['secs'] = (Time.now - t0).round(1)
res['unit'] = m.options['UnitsOptions']['LengthUnit']
res['n_faces'] = m.entities.grep(Sketchup::Group).sum { |g| g.definition.entities.grep(Sketchup::Face).length }
res['mats'] = m.materials.map(&:name).sort
res
