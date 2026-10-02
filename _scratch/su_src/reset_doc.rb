# -*- coding: utf-8 -*-
# 开工前清文档：把顶层**不属于我的**实体全部删掉，让文档回到「File → New」那种空状态。
#
# 为什么不用 `Sketchup.file_new`：它会弹「是否保存」模态框，桥是轮询式无人值守的 ——
# 弹框一出现就永远等不到结果（之前踩过模态框把自动化卡死的账）。这里改成脚本删实体：
#   ① 先 `save_copy` 存一份 .skp 备份（存不下也照做，只是把失败写在结果里）；
#   ② 删除包在**自己的操作栈**里 ⇒ 用户 Ctrl+Z 一步就能全撤回来；
#   ③ 只删顶层实体，并**逐个类别报数**（眼见为实：删了多少面/边/组/组件）。
# 页与 Tag 不在这里删（build_floors.rb 自己会清它自己那几个），只报出来。
require 'json'

# 由 su_deploy.sh 烘进来的 spec 路径（只为给备份文件起个带楼名的名字；本脚本不用它读几何）
SPEC = ENV['YZ_SPEC']

# ★ 2026-09-14 修：备份名原先**写死** `_su_before_lihua.skp` —— 不管在建哪栋楼都往同一个
#   文件覆盖（今天建 c006，日志里 `"backup"=>"..._su_before_lihua.skp"` 就是它）。
#   后果：每建一栋，**上一栋的"改前"备份就没了**；而 .skp 是含手工操作的唯一副本。
#   改成带楼名 + 时间戳（楼名从 SPEC 文件名推，取不到就退回 'doc'）。
_bakname = File.basename(defined?(SPEC) && SPEC ? SPEC.to_s : '').sub(/\.[^.]*\z/, '')
_bakname = 'doc' if _bakname.nil? || _bakname.empty? || _bakname == 'nil'
BAK = format('D:/gym3d/_scratch/su_jobs/_su_before_%s_%s.skp',
             _bakname, Time.now.strftime('%Y%m%d_%H%M%S'))
m = Sketchup.active_model

before = Hash.new(0)
m.entities.each { |e| before[e.class.name.split('::').last] += 1 }
bb = m.bounds
R = { 'before' => before, 'before_total' => m.entities.length,
      'before_bbox_m' => [bb.min.x.to_m, bb.min.y.to_m, bb.min.z.to_m,
                          bb.max.x.to_m, bb.max.y.to_m, bb.max.z.to_m].map { |v| v.round(3) },
      'pages_before' => m.pages.map(&:name), 'tags_before' => m.layers.map(&:name),
      'materials_before' => m.materials.map(&:name) }

begin
  ok = m.save_copy(BAK)
  R['backup'] = ok ? BAK : 'save_copy 返回 false'
rescue StandardError => e
  R['backup_err'] = "#{e.class}: #{e.message}"
end

m.start_operation('yingzao: 清空文档（理化楼开工前）', true)
begin
  # 快照一份再删（边删边遍历会漏）
  list = m.entities.to_a
  done = Hash.new(0)
  errs = []
  list.each do |e|
    cls = e.class.name.split('::').last
    begin
      e.erase!
      done[cls] += 1
    rescue StandardError => ex
      errs << "#{cls}: #{ex.class}: #{ex.message}" if errs.length < 5
    end
  end
  # 删掉实例**不等于**删掉组件定义：定义还在，挂在定义上的材质就还算「在用」
  # （实测：删完 1 个组件实例后 Heather/Lily 那 19 个材质一个没走）。两步一起清。
  # 先抄名字再 purge：purge 之后再碰快照里的对象会炸
  # `TypeError: reference to deleted ComponentDefinition`（这个坑踩过一次）。
  R['defs_before'] = m.definitions.map(&:name)
  begin
    m.definitions.purge_unused
  rescue StandardError => ex
    R['def_purge_err'] = "#{ex.class}: #{ex.message}"
  end
  R['defs_after'] = m.definitions.map(&:name)
  m.materials.purge_unused
  R['erased'] = done
  R['erase_err'] = errs
  R['after_total'] = m.entities.length
  R['materials_after'] = m.materials.map(&:name)
rescue StandardError => e
  R['error'] = "#{e.class}: #{e.message}"
  R['error_backtrace'] = (e.backtrace || [])[0, 5]
ensure
  m.commit_operation
end

R['done'] = true
R['note'] = '顶层实体已清空（Ctrl+Z 可整步撤回）；备份见 backup 字段'
R
