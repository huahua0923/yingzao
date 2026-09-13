# -*- coding: utf-8 -*-
# 探针：SU 2023 里「中文注释 / Tag（标签）/ 场景」三件事的 API 到底长什么样。
#
# 为什么不照记忆直接写建体脚本：这三样在 SU 各版本都改过（Layers→Tags 改名、
# Text#display_leader 在较新版变成只读/弃用、Pages#add 的 flags 参数时有时无），
# 猜错是**静默降级** —— 注释建不出来、Tag 没挂上、场景没生成，而模型看着是对的。
#
# 本脚本不留痕迹：几何改动包在 start_operation/abort_operation 里整体回滚，
# 标签与场景（不一定在回滚范围内）在 ensure 里显式删掉，并回读实体数确认没漏。
M2 = 0.0254 # SU 内部单位英寸 → 米（只在读数时用）

m = Sketchup.active_model
R = {}
R['su_version'] = Sketchup.version
R['su_pro'] = (Sketchup.is_pro? rescue 'n/a')
R['model_path'] = (m.path.to_s.empty? ? '(未保存)' : m.path.to_s)
R['entities_before'] = m.entities.count
R['pages_before'] = m.pages.count

# ---------- 1) TextOptions：中文字体 ----------
R['respond_to?(:textoptions)'] = m.respond_to?(:textoptions)
to = nil
begin
  to = m.textoptions if m.respond_to?(:textoptions)
rescue => e
  R['textoptions_err'] = "#{e.class}: #{e.message}"
end
R['textoptions_class'] = to.class.to_s
if to
  R['textoptions_methods'] = to.methods.grep(/font|size|bold|italic|color|leader|screen|align|hide/).sort
  begin
    R['textoptions_font'] = to.font
    R['textoptions_font_size'] = (to.font_size rescue 'n/a')
    old = to.font
    to.font = 'SimSun'
    R['textoptions_font_after_set'] = to.font
    R['font_set_ok'] = (to.font.to_s == 'SimSun')
    begin
      to.font = old
    rescue StandardError
      nil
    end
  rescue => e
    R['textoptions_set_err'] = "#{e.class}: #{e.message}"
  end
end

# options 管理器里找带 font/text 的那一档（TextOptions 不在 m.textoptions 时的退路）
opt_dump = {}
begin
  m.options.keys.each do |k|
    begin
      pairs = {}
      m.options[k].each_pair { |kk, vv| pairs[kk] = vv }
      opt_dump[k] = pairs.keys
      opt_dump["#{k}__values"] = pairs if k.to_s =~ /text/i || pairs.keys.any? { |x| x.to_s =~ /font/i }
    rescue => e
      opt_dump[k] = "ERR #{e.class}"
    end
  end
rescue => e
  opt_dump['ERR'] = "#{e.class}: #{e.message}"
end
R['options'] = opt_dump

op_started = false
begin
  m.start_operation('yz-probe', true)
  op_started = true

  # ---------- 2) add_text（中文） ----------
  label = '实验室 05-01-08'
  t = m.entities.add_text(label, Geom::Point3d.new(0, 0, 0), Geom::Vector3d.new(0, 0, 1))
  R['add_text_class'] = t.class.to_s
  if t
    R['text_readback'] = (t.text rescue 'n/a')
    R['text_cjk_roundtrip'] = (t.text == label)
    R['text_point_m'] = (t.point.to_a.map { |v| (v * M2).round(3) } rescue 'n/a')
    R['text_vector'] = (t.vector.to_a rescue 'n/a')
    R['text_methods'] = t.methods.grep(/display_leader|leader|arrow|text|point|vector|layer|hidden/).sort
    R['text_has_display_leader_eq'] = t.respond_to?(:display_leader=)
    if t.respond_to?(:display_leader=)
      begin
        t.display_leader = true
        R['text_display_leader'] = (t.display_leader rescue 'n/a')
      rescue => e
        R['text_display_leader_err'] = "#{e.class}: #{e.message}"
      end
    end
    R['text_has_leader_type_eq'] = t.respond_to?(:leader_type=)
    R['text_has_arrow_type_eq'] = t.respond_to?(:arrow_type=)
    R['text_has_layer_eq'] = t.respond_to?(:layer=)
  end

  # ---------- 3) Tag（UI 里叫「标签」，API 里一直是 layers） ----------
  # ★ 实测坑：SU 2023 的 `Model#tags` **不是**标签集合，是个 String（配 `tags=`，模型
  #   信息里的自由文本）。`respond_to?(:tags)` 返回 true 但拿到的是 ""。
  #   标签集合只有 `Model#layers`（Sketchup::Layers，有 add/remove/[]/each/purge_unused）。
  #   按「2020 后 UI 改名 Tags，API 应该也改了」去猜，就是这里静默降级。
  R['respond_to?(:tags)'] = m.respond_to?(:tags)
  R['m_tags_class'] = (m.tags.class.to_s rescue 'n/a')
  R['tags_source'] = 'm.layers'
  tags = m.layers
  R['tags_before'] = tags.map { |x| x.name }

  tag = tags.add('yingzao-probe')
  R['tag_add_class'] = tag.class.to_s
  R['tag_name'] = (tag.name rescue 'n/a')
  R['tag_visible_default'] = (tag.visible? rescue 'n/a')
  begin
    tag.visible = false
    R['tag_visible_false_ok'] = (tag.visible == false)
    tag.visible = true
  rescue => e
    R['tag_visible_err'] = "#{e.class}: #{e.message}"
  end

  g = m.entities.add_group
  f = g.entities.add_face([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]].map do |a|
    Geom::Point3d.new(a[0].m, a[1].m, a[2].m)
  end)
  R['probe_face_ok'] = !f.nil?
  f.pushpull(1.m) if f
  R['group_has_layer_eq'] = g.respond_to?(:layer=)
  g.layer = tag
  R['group_layer_name'] = (g.layer.name rescue 'n/a')

  # 组内文本挂**另一个** Tag：验「组可见但注释可单独关」
  tag2 = tags.add('yingzao-probe-note')
  t2 = g.entities.add_text('注释', Geom::Point3d.new(0, 0, 0), Geom::Vector3d.new(0, 0, 1))
  R['group_entities_add_text_class'] = t2.class.to_s
  if t2 && t2.respond_to?(:layer=)
    t2.layer = tag2
    R['text_layer_name'] = (t2.layer.name rescue 'n/a')
  end
  R['tags_after_add'] = tags.map { |x| x.name }.length

  # 组挂 Tag 后：组自己隐藏 vs 只关注释 Tag
  R['group_hidden_via_tag'] = (tag.visible = false; g.hidden?)
  tag.visible = true

  # ---------- 4) 场景（Pages） ----------
  pg = m.pages.add('yz-probe')
  R['page_add_class'] = pg.class.to_s
  R['page_name'] = (pg.name rescue 'n/a')
  R['page_methods'] = pg.methods.grep(/update|use_camera|camera|name|layer|include|transition|flags/).sort
  begin
    pg.update
    R['page_update_ok'] = true
  rescue => e
    R['page_update_err'] = "#{e.class}: #{e.message}"
  end
  R['page_has_use_camera_eq'] = pg.respond_to?(:use_camera=)
  pg.use_camera = true if pg.respond_to?(:use_camera=)
  R['pages_after_add'] = m.pages.count
  m.pages.erase(pg)
  R['pages_after_erase'] = m.pages.count
ensure
  (m.abort_operation rescue nil) if op_started
  begin
    tx = m.layers                      # 同上：别用 m.tags（是 String）
    ['yingzao-probe', 'yingzao-probe-note'].each do |nm|
      tg = tx[nm]
      tx.remove(tg) if tg
    end
    R['tags_cleanup'] = tx.map { |x| x.name }
  rescue => e
    R['cleanup_err'] = "#{e.class}: #{e.message}"
  end
end

R['entities_after'] = m.entities.count
R['pages_after'] = m.pages.count
R['leak_entities'] = R['entities_after'] - R['entities_before']
R['leak_pages'] = R['pages_after'] - R['pages_before']
R
