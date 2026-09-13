# -*- coding: utf-8 -*-
# 钉死「桥会不会被重入」：导出前后各数一次日志里的 bridge loaded 行数。
# 若导出期间行数增加 ⇒ 加载导出器扩展会把 Plugins/*.rb 重新 eval ⇒ 桥的 run_pending
# 会被嵌套调用 ⇒ 同一个任务被递归重跑（这就是 SU 被拖死的原因）。
LOG = 'D:/gym3d/_scratch/su_jobs/_bridge.log'
count = -> { File.read(LOG, mode: 'rb').scan(/bridge loaded/).length }
m = Sketchup.active_model
dir = 'D:/gym3d/_scratch/_su_export'
Dir.mkdir(dir) unless Dir.exist?(dir)

# 有几何才导得动
m.start_operation('yingzao: boot probe cube', true)
tmp = m.entities.add_group
tmp.entities.add_face([0, 0, 0], [1.m, 0, 0], [1.m, 1.m, 0], [0, 1.m, 0]).pushpull(1.m)
m.commit_operation

b = count.call
res = {}
begin
  res['dae'] = m.export(File.join(dir, '_boot_probe.dae'), {}).inspect
rescue StandardError => e
  res['dae_err'] = "#{e.class}: #{e.message}"
end
a = count.call
res['boots_before'] = b
res['boots_after'] = a
res['boots_during'] = a - b
res['pid'] = Process.pid

# 清理
m.start_operation('yingzao: boot probe off', true)
tmp.erase!
m.commit_operation
File.delete(File.join(dir, '_boot_probe.dae')) if File.exist?(File.join(dir, '_boot_probe.dae'))
res
