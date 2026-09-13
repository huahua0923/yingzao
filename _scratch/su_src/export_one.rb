# -*- coding: utf-8 -*-
# 一次只试一种格式（EXT 行由部署时 sed 烘入）。报进程号：下一种格式的进程号变了
# = 上一种把 SU 搞崩了。空模型先放临时方块，跑完擦掉。
EXT = 'dae'
m = Sketchup.active_model
dir = 'D:/gym3d/_scratch/_su_export'
Dir.mkdir(dir) unless Dir.exist?(dir)

n0 = m.entities.grep(Sketchup::Face).length +
     m.entities.grep(Sketchup::Group).sum { |g| g.definition.entities.grep(Sketchup::Face).length }
tmp = nil
if n0.zero?
  m.start_operation('yingzao: probe cube', true)
  tmp = m.entities.add_group
  tmp.entities.add_face([0, 0, 0], [1.m, 0, 0], [1.m, 1.m, 0], [0, 1.m, 0]).pushpull(1.m)
  m.commit_operation
end

out = File.join(dir, "_probe.#{EXT}")
File.delete(out) if File.exist?(out)
rec = { 'pid' => Process.pid, 'ext' => EXT, 'empty_before' => n0.zero? }
t0 = Time.now
begin
  rec['ret'] = m.export(out, {}).inspect
rescue StandardError => e
  rec['err'] = "#{e.class}: #{e.message}"
end
rec['secs'] = (Time.now - t0).round(2)
rec['size'] = File.exist?(out) ? File.size(out) : nil
# 先只看大小，文件留着给 Python 量（下一步真转 GLB 时还要用）；temp 方块擦掉
if tmp
  m.start_operation('yingzao: probe cube off', true)
  tmp.erase!
  m.commit_operation
end
rec['n_faces_after'] = m.entities.grep(Sketchup::Face).length +
                       m.entities.grep(Sketchup::Group).sum { |g| g.definition.entities.grep(Sketchup::Face).length }
rec
