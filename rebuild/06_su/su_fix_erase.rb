# -*- coding: utf-8 -*-
# SU 无人值守 · **一次性补救**：按名字删掉 `c006_su.skp` 里的若干组，
# 好让 `su_step2_build.rb` 重跑时不再被「同名组跳过」挡住。
#
# 为什么要这个脚本（2026-10-13 晚，第 4 批顶部三件跑红）：
#   第 4 批第一次跑，SU 当场报了 `FACES built=4 fail=1`，`BBOX_mm size=[…, 90500.0]`。
#   两处都是**我们的输入错**，不是 SU 错：
#     ① 两个原点：`_attach_recs` 写进 JSON 的是**绝对**标高，而记录 `z` 的约定是
#        **相对本层底面**（SU 脚本写 `zbase + pr["z"]`）⇒ 女儿墙落到 84000 mm、
#        台阶屋面落到 51880 mm。总高因此从该有的 50.5 m 变成 90.5 m。
#     ② 零长边：坐标 `round(…, 1)`（0.1 mm）把两个点圆成同一个数，
#        环上出现连续重复点 —— shapely 判 `is_valid/is_simple` 全 True，
#        **SU 却建不出长度 0 的边**，那条多边形就静默少一张面（2 条只成了 1 条）。
#   两个缺陷都已在 `rebuild/tools/export_contours.py` 修掉（`_rel_z` / `_dedup`）。
#   ★ 但已经建进 skp 的那三个组**名字还在** ⇒ 重跑会被跳过 ⇒ 必须先按名字删掉。
#
# 名单从同目录 `_erase.txt` 读（一行一个组名，`#` 开头与空行忽略）——
# 不写死在脚本里，免得这段补救代码将来变成地雷（下次跑还会再删一遍）。
#
# 跑法（与其它脚本同规矩：必须给「已存在的文档」参数，且启动前杀掉残留的 SU）：
#   powershell -NoProfile -Command "& 'C:\Program Files\SketchUp\SketchUp 2023\SketchUp.exe' `
#       'D:\项目\cdut3d\rebuild\06_su\c006_su.skp' `
#       -RubyStartup 'D:\项目\cdut3d\rebuild\06_su\su_fix_erase.rb'"
#
# 它**只删**，不建：删完存盘 + 导出，然后退出；接着跑正常的第 4 批。

DIR  = "D:/项目/cdut3d/rebuild/06_su"
LIST = "#{DIR}/_erase.txt"
LOG  = "#{DIR}/build_log.txt"

def say(s)
  # 与 su_step2_build.rb 同规矩：行首带 pid、**不在开头删日志**（删了就看不出几趟在写）
  File.open(LOG, "a") { |f| f.puts("[#{Process.pid}] #{s}") }
end

say "ERASE_SCRIPT_ENTERED ruby=#{RUBY_VERSION} at=#{Time.now.strftime('%H:%M:%S')}"

SU = if defined?(SketchUp) then SketchUp
     elsif defined?(Sketchup) then Sketchup
     end
say "ERASE_SU=#{SU.inspect}"

def want_names(path)
  unless File.exist?(path)
    say "ERASE_FATAL 名单文件不存在：#{path}"
    return nil
  end
  File.readlines(path, encoding: "bom|utf-8").map(&:strip)
      .reject { |l| l.empty? || l.start_with?("#") }
end

def guarded(su)
  raise "no API module" if su.nil?
  model = su.active_model
  raise "no model" if model.nil?

  names = want_names(LIST)
  raise "no name list" if names.nil?
  say "ERASE_NAMES=#{names.inspect}"

  model.start_operation("c006_fix_erase", true)
  hit = Hash.new(0)
  model.entities.to_a.each do |e|
    next unless e.is_a?(Sketchup::Group)
    n = (e.name || "").strip
    next unless names.include?(n)
    model.entities.erase_entities(e)
    hit[n] += 1
  end
  model.commit_operation

  # ★ 报告要能把「删掉了」与「本来就没有」分开（铁律 199：崩了与没量到不许同形）
  names.each { |n| say "ERASE  #{n} 命中 #{hit[n]} 个" }
  left = model.entities.grep(Sketchup::Group).map(&:name).sort
  still = left & names
  say "ERASE_LEFT 剩下同名组=#{still.inspect}（应为空） groups_now=#{left.length}"

  skp = "#{DIR}/c006_su.skp"
  model.save(skp)
  say "ERASE_SAVED bytes=#{File.exist?(skp) ? File.size(skp) : 0}"
  # ★ 2026-10-15：与 `su_step2_build.rb` 同步 —— **不再导 `.dae`**（全仓无人读；
  #   见主链那份里的长注释）。铁律 183：同形状的错法换一个函数仍会再犯，
  #   所以这里一起改，不是只改主链那一处。
  [["obj", "#{DIR}/c006_su.obj"]].each do |tag, p|
    ok = begin
      model.export(p)
    rescue StandardError => e
      say "ERASE_EXPORT_RAISED #{tag} #{e.class}: #{e.message}"
      false
    end
    say "ERASE_EXPORT #{tag} ok=#{ok.inspect} bytes=#{File.exist?(p) ? File.size(p) : 0}"
  end
  say "ERASE_DONE"
rescue StandardError => e
  say "ERASE_FATAL #{e.class}: #{e.message}"
  say((e.backtrace || []).first(8).join(" | "))
end

# 与 su_step2_build.rb 同一个坑：`UI.start_timer(t, false)` **会重复触发**，靠标志位挡住重入
$erase_runs = 0
UI.start_timer(5.0, false) do
  $erase_runs += 1
  if $erase_runs == 1
    guarded(SU)
    UI.start_timer(3.0, false) { SU.quit rescue nil }
  else
    say "ERASE_REENTRY_BLOCKED run=#{$erase_runs}"
  end
end
say "ERASE_TIMER_ARMED"
