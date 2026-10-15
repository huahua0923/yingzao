# -*- coding: utf-8 -*-
# SU 无人值守 · 第一步：把 CAD 底图 DXF 导进 SU，量清楚它到底按什么单位/朝向进来的。
#
# 跑法（必须给一个「已存在的文档」参数，否则欢迎屏挡启动 —— 见 README.md §5）：
#   "C:\Program Files\SketchUp\SketchUp 2023\SketchUp.exe" "<某个.skp>" ^
#       -RubyStartup "D:\项目\cdut3d\rebuild\06_su\su_step1_import.rb"
#
# 为什么先跑这一步：DXF 自己声明 $INSUNITS=6（米），而坐标是 mm 量级
# （1层窗口 164000 × 111000）。声明和实际不一致 ⇒ 不能猜，必须实测答一句：
# SU 进来之后，模型量出的宽度是 129 m 还是 129000 m。
#
# 本步**只导入 + 量**，不建任何几何。

DIR = "D:/项目/cdut3d/rebuild/06_su"
DXF = "D:/项目/cdut3d/rebuild/01_cad/raw/1层.dxf"
LOG = "#{DIR}/import_log.txt"

def say(s)
  File.open(LOG, "a") { |f| f.puts(s) }
end

File.delete(LOG) if File.exist?(LOG)
say "SCRIPT_ENTERED pid=#{Process.pid} ruby=#{RUBY_VERSION}"

SU = if defined?(SketchUp) then SketchUp
     elsif defined?(Sketchup) then Sketchup
     end
say "SU=#{SU.inspect}"
say "DXF exists=#{File.exist?(DXF)} bytes=#{File.exist?(DXF) ? File.size(DXF) : 0}"

def guarded(su)
  raise "no API module" if su.nil?
  model = su.active_model
  raise "no model" if model.nil?

  # 把随启动文档带进来的样件清掉，留一张白纸
  model.start_operation("clear", true)
  n0 = model.entities.length
  model.entities.erase_entities(model.entities.to_a)
  model.commit_operation
  say "CLEARED was=#{n0} now=#{model.entities.length}"

  model.options["UnitsOptions"]["LengthUnit"] = 2   # 2=毫米（只管显示）
  model.options["UnitsOptions"]["LengthFormat"] = 0

  t0 = Time.now
  ok = begin
    model.import(DXF)
  rescue => e
    say "IMPORT_RAISED #{e.class}: #{e.message}"
    false
  end
  say "IMPORT ok=#{ok.inspect} secs=#{(Time.now - t0).round(2)}"

  ents = model.entities.to_a
  say "ENTITIES=#{ents.length}"
  by = Hash.new(0)
  ents.each { |e| by[e.typename] += 1 }
  say "TYPENAMES=#{by.sort_by { |_k, v| -v }.inspect}"

  # 图层名也打出来 —— 用来核对导进来的确实是那 8 个层
  lay = model.layers.map { |l| l.name }
  say "LAYERS(#{lay.length})=#{lay.inspect}"

  bb = model.bounds
  say "BBOX_inch min=#{bb.min.to_a.map { |v| v.round(3) }.inspect} " \
      "max=#{bb.max.to_a.map { |v| v.round(3) }.inspect}"
  say "BBOX_mm   min=#{bb.min.to_a.map { |v| v.to_mm.round(1) }.inspect} " \
      "max=#{bb.max.to_a.map { |v| v.to_mm.round(1) }.inspect}"
  say "BBOX_mm   size=[#{bb.width.to_mm.round(1)}, #{bb.height.to_mm.round(1)}, "\
      "#{bb.depth.to_mm.round(1)}]"
  say "期望（1层窗口 164000 × 111000 mm；内容约 129 × 84 m）"

  skp = "#{DIR}/c006_su_1f.skp"
  obj = "#{DIR}/c006_su_1f.obj"
  model.save(skp)
  say "SAVED exists=#{File.exist?(skp)} bytes=#{File.exist?(skp) ? File.size(skp) : 0}"
  eok = begin
    model.export(obj)
  rescue => e
    say "EXPORT_RAISED #{e.class}: #{e.message}"
    false
  end
  say "EXPORT obj ok=#{eok.inspect} exists=#{File.exist?(obj)} " \
      "bytes=#{File.exist?(obj) ? File.size(obj) : 0}"
  say "DONE"
rescue => e
  say "FATAL #{e.class}: #{e.message}"
  say((e.backtrace || []).first(8).join(" | "))
end

UI.start_timer(5.0, false) do
  guarded(SU)
  UI.start_timer(2.0, false) do
    SU.quit rescue nil
  end
end
say "TIMER_ARMED"
