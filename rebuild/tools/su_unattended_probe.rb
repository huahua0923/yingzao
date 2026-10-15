# -*- coding: utf-8 -*-
# SU 无人值守探针：先**实测常量名**再干活，跑完自己退出。
#
# ★ 这条探针的**结论已经落盘**，不必再跑它去「确认一遍」：
#   · `rebuild/06_su/README.md` §7（十条实测：欢迎屏挡启动、常量名是 `Sketchup`、
#     单实例静默接手、`model.export` 泵消息循环、半截导出仍像个文件…）；
#   · 记忆 `cdut3d-su-unattended-and-export-conventions`（裸数字=英寸、导出单位/朝向
#     是**对话框选项**因而两次实测给出不同答案、`Get-Process` 计数 0 证明不了什么）。
#   留着它是**为了复现**（比如换 SU 版本 / 换机器后 `Sketchup` 常量还在不在）。
#
# 2026-10-13 从 `rebuild/06_su/` 挪到这里：它原先写在**交付件目录**里、且往
# `C:/Users/Administrator/_su_probe`（仓外、随手删）写件 —— 交付件目录只放
# 正式件 + `EXPORT.md` + `README.md` + 出件脚本。现在输出落**本脚本旁边**的
# `_probe_out/`，目录自己建，删起来是一整个目录。
#
# 跑法（Windows / PowerShell；★从 bash 直接调 `SketchUp.exe` 实测 rc=127）：
#   powershell -NoProfile -Command "& 'C:\Program Files\SketchUp\SketchUp 2023\SketchUp.exe' `
#       '某个已存在的.skp' -RubyStartup 'D:\项目\cdut3d\rebuild\tools\su_unattended_probe.rb'"
# ★ 启动前先杀掉所有 SketchUp 并**无条件等 ≥5 s**（单实例会静默接手，症状和
#   「欢迎屏挡启动」同形：脚本一行不跑、零报错）。判据：日志里出现新的 SCRIPT_ENTERED。

DIR = File.expand_path("_probe_out", __dir__)
LOG = "#{DIR}/log.txt"
Dir.mkdir(DIR) unless File.directory?(DIR)

def say(s)
  File.open(LOG, "a") { |f| f.puts(s) }
end

File.delete(LOG) if File.exist?(LOG)
say "SCRIPT_ENTERED pid=#{Process.pid} ruby=#{RUBY_VERSION} dir=#{DIR}"

# ── ① 实测：到底哪个常量才是 API 模块 ──
say "defined?(SketchUp)=#{defined?(SketchUp).inspect}"
say "defined?(Sketchup)=#{defined?(Sketchup).inspect}"
say "constants~/ketch/i=#{Object.constants.grep(/ketch/i).inspect}"
begin
  say "top-level methods~/active_model/i=" \
      "#{self.private_methods.grep(/active_model/i).inspect}"
rescue => e
  say "meth probe failed #{e.class}"
end

SU = if defined?(SketchUp) then SketchUp
     elsif defined?(Sketchup) then Sketchup
     end
say "CHOSEN=#{SU.inspect}"

def guarded(su)
  raise "no API module" if su.nil?
  model = su.active_model
  say "ACTIVE_MODEL=#{model.nil? ? 'nil' : 'ok'}"

  if model.nil?
    say "NO_MODEL_YET —— 连文档都没开，那就新建一个"
    su.file_new
    model = su.active_model
    say "AFTER_FILE_NEW=#{model.nil? ? 'nil' : 'ok'}"
  end
  return say("STILL_NO_MODEL") if model.nil?

  model.start_operation("probe_box", true)
  model.options["UnitsOptions"]["LengthUnit"] = 2      # 0=in 1=ft 2=mm 3=cm 4=m
  model.options["UnitsOptions"]["LengthFormat"] = 0    # decimal

  ents = model.active_entities
  pts = [[0, 0, 0], [10_000, 0, 0], [10_000, 8_000, 0], [0, 8_000, 0]]
  ents.add_face(pts).pushpull(-4_000)                  # ★裸数字是**英寸** ⇒ 实得 254000×203200×101600 mm
  model.commit_operation

  bb = model.bounds
  say "SU_BBOX min=#{bb.min.to_a.inspect} max=#{bb.max.to_a.inspect}"
  say "SU_UNIT LengthUnit=#{model.options['UnitsOptions']['LengthUnit']}"

  skp = "#{DIR}/probe.skp"
  model.save(skp)
  say "SAVED exists=#{File.exist?(skp)} bytes=#{File.exist?(skp) ? File.size(skp) : 0}"

  [["probe.obj", "obj"], ["probe.dae", "dae"]].each do |fn, kind|
    p = "#{DIR}/#{fn}"
    begin
      ok = model.export(p)
      say "EXPORT #{kind} ok=#{ok.inspect} exists=#{File.exist?(p)}" \
          "#{File.exist?(p) ? " bytes=#{File.size(p)}" : ''}"
    rescue => e
      say "EXPORT #{kind} FAILED #{e.class}: #{e.message}"
    end
  end
  say "DONE"
rescue => e
  say "FATAL #{e.class}: #{e.message}"
  say((e.backtrace || []).first(6).join(" | "))
end

# ── ② 延迟到界面就绪再干活；quit 也要用**实测到的**那个常量 ──
# ★ `model.export` 会泵消息循环 ⇒ 那个 5 s 计时器在导出**进行中**可能再触发一次。
#   等的是新的 `DONE` 行，不是「进程数归零」（`Get-Process` 计数 0 证明不了跑完了）。
# ★ `ensure` 里写错常量名 ⇒ `quit` 也抛 ⇒ SU 不退出，只能 `taskkill`。
UI.start_timer(5.0, false) do
  guarded(SU)
  UI.start_timer(1.0, false) do
    SU.quit rescue nil
  end
end
say "TIMER_ARMED"
