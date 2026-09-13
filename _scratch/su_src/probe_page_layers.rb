# -*- coding: utf-8 -*-
# 探针 3：补两个还没定下来的空格（都不许猜，猜错是静默降级）
#   A) 中文字体：`m.textoptions` 返回 false ⇒ TextOptions 到底从哪拿？拿不到怎么降级。
#      （注：OptionsManager#[] 有「不存在就创建」的行为，所以要直接 [] 而不是看 keys）
#   B) 场景的逐页图层可见性：`Page#layers` 是页作用域，还是要「先选中页→改全局→update」？
#      判据：把 page 里的那层设成不可见，看**全局**那层变不变 ——
#        全局没变 ⇒ 路线①（page.layers 页作用域）成立；
#        全局也变 ⇒ 是同一个对象，只能走路线②。
#
# 不留痕：几何改动包在 start_operation/abort_operation 整体回滚；页与图层在 ensure 显式删掉，
# 并回读实体/页/图层数确认没漏（上一版探针的 leak 计数都是 0，这个也照做）。
M2 = 0.0254
m = Sketchup.active_model
R = {}
R['entities_before'] = m.entities.count
R['pages_before']   = m.pages.count
R['layers_before']  = m.layers.map { |x| x.name }

# ---------- A) TextOptions：中文字体从哪设 ----------
begin
  to = m.options['TextOptions']          # 不存在时 OptionsManager 会现创建
  R['opt_textoptions_class'] = to.class.to_s
  if to
    begin
      pairs = {}
      to.each_pair { |k, v| pairs[k] = v }
      R['opt_textoptions_pairs'] = pairs
    rescue => e
      R['opt_pairs_err'] = "#{e.class}: #{e.message}"
    end
    R['to_methods'] = to.methods.grep(/font|size|color|bold|italic|leader|align/).sort
    # 两套写法都试：hash 风格 to['Font'] 与 方法风格 to.font
    begin
      R['font_read_hash'] = to['Font']
      to['Font'] = 'SimSun'
      R['font_hash_after'] = to['Font']
    rescue => e
      R['font_hash_err'] = "#{e.class}: #{e.message}"
    end
    begin
      R['has_font_eq'] = to.respond_to?(:font=)
      if to.respond_to?(:font=)
        old = (to.font rescue nil)
        to.font = 'SimSun'
        R['font_method_after'] = to.font
        R['font_old_restore'] = (to.font = old; to.font) rescue nil
      end
    rescue => e
      R['font_method_err'] = "#{e.class}: #{e.message}"
    end
  end
  R['opt_keys_after'] = (m.options.keys rescue 'n/a')
rescue => e
  R['opt_textoptions_err'] = "#{e.class}: #{e.message}"
end
# Text 的 leader 常量在不在（建注释时想画引线）
R['text_constants'] = (Sketchup::Text.constants.sort rescue 'n/a')

# ---------- B) 逐页图层可见性 ----------
R['pages_class_methods'] = (Sketchup::Pages.instance_methods(false).sort rescue 'n/a')
R['page_class_methods']  = (Sketchup::Page.instance_methods(false).sort rescue 'n/a')
op = false
begin
  m.start_operation('yz-probe3', true)
  op = true
  lay = m.layers.add('yz-pl')
  g = m.entities.add_group
  f = g.entities.add_face([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]].map do |a|
    Geom::Point3d.new(a[0].m, a[1].m, a[2].m)
  end)
  f.pushpull(1.m) if f
  g.layer = lay
  R['probe_face_ok'] = !f.nil?

  pg = m.pages.add('yz-pl-page')
  R['pg_layers_class'] = (pg.layers.class.to_s rescue 'n/a')
  R['pg_layers_names'] = (pg.layers.map { |x| x.name } rescue "ERR #{$!.class}")
  R['same_ruby_object'] = (pg.layers['yz-pl'].equal?(m.layers['yz-pl']) rescue 'n/a')

  # 路线①：改 page.layers 里那个（若为页作用域，全局那层不该变）
  begin
    pl = pg.layers['yz-pl']
    pl.visible = false
    R['r1_page_visible']   = (pl.visible? rescue 'n/a')
    R['r1_global_visible'] = (m.layers['yz-pl'].visible? rescue 'n/a')
    R['r1_entity_hidden']  = (g.hidden? rescue 'n/a')
    pl.visible = true
    R['r1_restore_page_visible'] = (pl.visible? rescue 'n/a')
  rescue => e
    R['r1_err'] = "#{e.class}: #{e.message}"
  end

  # 路线②：选中该页 → 改全局 → page.update，再回读该页记录
  begin
    R['has_selected_page_eq'] = m.pages.respond_to?(:selected_page=)
    if m.pages.respond_to?(:selected_page=)
      m.pages.selected_page = pg
      R['selected_page_name'] = m.pages.selected_page.name
    end
    m.layers['yz-pl'].visible = false
    pg.update
    R['r2_page_visible']   = (pg.layers['yz-pl'].visible? rescue 'n/a')
    R['r2_global_visible'] = m.layers['yz-pl'].visible?
  rescue => e
    R['r2_err'] = "#{e.class}: #{e.message}"
  end

  # 决定性一步：全局改回可见，页里的记录若仍是 false ⇒ 页作用域独立（路线②真身）
  begin
    m.layers['yz-pl'].visible = true
    R['r2_after_global_true_page_visible'] = (pg.layers['yz-pl'].visible? rescue 'n/a')
  rescue => e
    R['recheck_err'] = "#{e.class}: #{e.message}"
  end

  # 相机能不能写进页（每层俯视图要用）
  begin
    R['cam_class'] = Sketchup::Camera.to_s
    cam = Sketchup::Camera.new(Geom::Point3d.new(0, 0, 50.m), Geom::Point3d.new(0, 0, 0),
                               Geom::Vector3d.new(0, 1, 0))
    pg.camera = cam
    pg.use_camera = true
    R['cam_set_ok'] = (pg.use_camera? rescue 'n/a')
    R['cam_eye_m'] = (pg.camera.eye.to_a.map { |v| (v * M2).round(2) } rescue 'n/a')
    pg.update
    R['cam_after_update'] = (pg.camera.eye.to_a.map { |v| (v * M2).round(2) } rescue 'n/a')
  rescue => e
    R['cam_err'] = "#{e.class}: #{e.message}"
  end

  m.pages.erase(pg)
ensure
  (m.abort_operation rescue nil) if op
  begin
    m.layers['yz-pl'].visible = true if m.layers['yz-pl']   # 别把用户图层留成隐藏
    t = m.layers['yz-pl']
    m.layers.remove(t) if t
  rescue => e
    R['cleanup_layers_err'] = "#{e.class}: #{e.message}"
  end
end

R['entities_after'] = m.entities.count
R['pages_after']    = m.pages.count
R['layers_after']   = m.layers.map { |x| x.name }
R['leak_entities']  = R['entities_after'] - R['entities_before']
R['leak_pages']     = R['pages_after'] - R['pages_before']
R
