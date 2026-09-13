# -*- coding: utf-8 -*-
# 探针 4：把「逐页图层可见性」和「页相机」定死。上一版两个错误假设已排除：
#   · Page#layers 是 Array（整数索引，不是页作用域图层集）
#   · Page#camera= 不存在（只有 reader）
# 方法表里露出的真身是 Page#set_visibility / get_drawingelement_visibility，
# 相机大概率只能「选中页 → 设视口相机 → update」捕获。两件都实测。
#
# 决定性判据（页作用域的核心）：对页设某层不可见后，**全局**那层的 visible? 必须仍是 true。
# 视口相机在 ensure 里还原（用户正开着这个文档，不能把人家视角挪走）。
M2 = 0.0254
m = Sketchup.active_model
av = m.active_view
orig = av.camera
R = {}
R['entities_before'] = m.entities.count
R['pages_before']    = m.pages.count
R['layers_before']   = m.layers.map { |x| x.name }
R['cam_before_m']    = orig.eye.to_a.map { |v| (v * M2).round(2) }
R['cam_before_persp'] = (orig.perspective? rescue 'n/a')

op = false
pg = nil
begin
  m.start_operation('yz-probe4', true)
  op = true
  lay = m.layers.add('yz-pv')
  g = m.entities.add_group
  f = g.entities.add_face([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]].map do |a|
    Geom::Point3d.new(a[0].m, a[1].m, a[2].m)
  end)
  f.pushpull(1.m) if f
  g.layer = lay

  pg = m.pages.add('yz-pv-page')

  # ---------- A) page.layers 里到底是什么 ----------
  pl = pg.layers
  R['a_class'] = pl.class.to_s
  R['a_len'] = (pl.length rescue 'n/a')
  R['a_items'] = (pl.map { |x| [x.class.to_s, (x.respond_to?(:name) ? x.name : x.to_s)] } rescue "ERR #{$!.class}: #{$!.message}")
  R['a_methods'] = (pl.methods.grep(/layer|name|visib|include/).sort rescue 'n/a')

  # ---------- B) set_visibility：页作用域？需不需要先选中页？ ----------
  R['has_set_visibility'] = pg.respond_to?(:set_visibility)
  R['has_get_dev'] = pg.respond_to?(:get_drawingelement_visibility)
  R['has_set_dev'] = pg.respond_to?(:set_drawingelement_visibility)
  begin
    pg.set_visibility(lay, false)
    R['b_set_ok'] = true
    R['b_global_visible'] = (m.layers['yz-pv'].visible? rescue 'n/a')   # ★ 必须 true
    R['b_page_layers_after'] = (pg.layers.map { |x| (x.respond_to?(:name) ? x.name : x.to_s) } rescue "ERR #{$!.class}")
    R['b_get_dev'] = (pg.get_drawingelement_visibility(lay) rescue "ERR #{$!.class}")
    R['b_entity_hidden'] = (g.hidden? rescue 'n/a')
    pg.update
    R['b_global_after_update'] = (m.layers['yz-pv'].visible? rescue 'n/a')
    R['b_get_dev_after_update'] = (pg.get_drawingelement_visibility(lay) rescue "ERR #{$!.class}")
    # 反过来：全局设为不可见，看页里记录是不是独立（若独立，两者可以不一致）
    m.layers['yz-pv'].visible = false
    R['b_page_record_when_global_false'] = (pg.get_drawingelement_visibility(lay) rescue "ERR #{$!.class}")
    m.layers['yz-pv'].visible = true
    pg.set_visibility(lay, true)
    R['b_restore_global'] = (m.layers['yz-pv'].visible? rescue 'n/a')
  rescue => e
    R['b_err'] = "#{e.class}: #{e.message}"
  end

  # ---------- C) 相机：选中页 → 设视口相机 → update 能不能落到页上 ----------
  begin
    m.pages.selected_page = pg
    R['c_selected'] = m.pages.selected_page.name
    want = Sketchup::Camera.new(Geom::Point3d.new(10.m, 10.m, 40.m),
                                Geom::Point3d.new(0, 0, 0),
                                Geom::Vector3d.new(0, 1, 0))
    av.camera = want
    R['c_view_eye_m'] = av.camera.eye.to_a.map { |v| (v * M2).round(2) }
    pg.use_camera = true
    pg.update
    R['c_page_eye_m'] = (pg.camera.eye.to_a.map { |v| (v * M2).round(2) } rescue 'n/a')
    R['c_page_target_m'] = (pg.camera.target.to_a.map { |v| (v * M2).round(2) } rescue 'n/a')
    R['c_page_use_camera'] = (pg.use_camera? rescue 'n/a')
    # 视口再挪走，页里那台相机是否还留着（=已捕获）
    av.camera = Sketchup::Camera.new(Geom::Point3d.new(0, 0, 5.m), Geom::Point3d.new(0, 0, 0),
                                     Geom::Vector3d.new(0, 1, 0))
    R['c_page_eye_after_move'] = (pg.camera.eye.to_a.map { |v| (v * M2).round(2) } rescue 'n/a')
  rescue => e
    R['c_err'] = "#{e.class}: #{e.message}"
  end

  m.pages.erase(pg)
  pg = nil
ensure
  (m.abort_operation rescue nil) if op
  begin
    m.pages.erase(pg) if pg
    t = m.layers['yz-pv']
    if t
      t.visible = true
      m.layers.remove(t)
    end
    av.camera = Sketchup::Camera.new(orig.eye, orig.target, orig.up)
    (av.camera.perspective = orig.perspective?) rescue nil
    (av.camera.fov = orig.fov) rescue nil
  rescue => e
    R['cleanup_err'] = "#{e.class}: #{e.message}"
  end
end

R['cam_after_restore_m'] = (av.camera.eye.to_a.map { |v| (v * M2).round(2) } rescue 'n/a')
R['entities_after'] = m.entities.count
R['pages_after']    = m.pages.count
R['layers_after']   = m.layers.map { |x| x.name }
R['leak_entities']  = R['entities_after'] - R['entities_before']
R['leak_pages']     = R['pages_after'] - R['pages_before']
R
