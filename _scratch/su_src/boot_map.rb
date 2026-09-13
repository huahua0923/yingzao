# -*- coding: utf-8 -*-
# 逐格式量「导出期间桥被重入几次」。任何一个格式出现增量就立刻跳出返回 ——
# 不再往下试，免得又变成连环重跑把 SU 拖死。
LOG = 'D:/gym3d/_scratch/su_jobs/_bridge.log'
count = -> { File.read(LOG, mode: 'rb').scan(/bridge loaded/).length }
m = Sketchup.active_model
dir = 'D:/gym3d/_scratch/_su_export'
Dir.mkdir(dir) unless Dir.exist?(dir)

m.start_operation('yingzao: boot map cube', true)
tmp = m.entities.add_group
tmp.entities.add_face([0, 0, 0], [1.m, 0, 0], [1.m, 1.m, 0], [0, 1.m, 0]).pushpull(1.m)
m.commit_operation

rows = {}
stopped_at = nil
%w[dae obj fbx stl wrl xsi ifc dwg dxf kmz pdf].each do |ext|
  p = File.join(dir, "_map.#{ext}")
  File.delete(p) if File.exist?(p)
  b = count.call
  begin
    m.export(p, {})
    sz = File.exist?(p) ? File.size(p) : nil
    rows[ext] = { 'size' => sz, 'boots' => count.call - b, 'err' => nil }
  rescue StandardError => e
    rows[ext] = { 'size' => nil, 'boots' => count.call - b, 'err' => "#{e.class}: #{e.message}" }
  end
  File.delete(p) if File.exist?(p)
  if rows[ext]['boots'].to_i > 0
    stopped_at = ext
    break
  end
end

m.start_operation('yingzao: boot map off', true)
tmp.erase!
m.commit_operation
{ 'rows' => rows, 'stopped_at' => stopped_at, 'pid' => Process.pid,
  'total_boots' => count.call }
