# -*- coding: utf-8 -*-
# 出图验收（**全库版**）：与 `shots_floors.rb` 逐行同构，只改两处：
#   ① `BANDS` 不再写死理化楼的 5 层 + 屋顶@band5，而是**从模型里实际存在的组派生**
#      —— 原脚本对 6 层的 ny27/28/29 会漏拍 F5（它按名找不到 `yingzao-F5 本层` 之外的问题：
#      BANDS 里 [5] 指的是「屋顶」，而 ny27 的 F5 组也叫 yingzao-F5，屋顶在 band 6，
#      于是 F5 那一层永远拍不到）。
#   ② 出图文件名加**楼名前缀**，各栋的图互不覆盖（原脚本直接写 `_su_yingzao-F0_floor.png`，
#      跑第二栋就把第一栋的盖掉）。
#
# 楼名从 su_deploy.sh 烘进来的 SPEC 路径取（`_ny27_floors_spec.json` → `ny27`）。
# 为什么新开文件而不是改原脚本：原脚本是理化楼那一版的验收件，改它等于动已验收的基准。
require 'json'

OUT = 'D:/gym3d/_scratch/su_jobs/'

# 楼名：SPEC 由 su_deploy.sh 的 `sed -i "s|^SPEC = ENV.*|SPEC = '<绝对路径>'|"` 烘进来。
# ★ 这行必须**逐字**长成 `SPEC = ENV[...]`，否则 sed 匹配不到、su_deploy 的守卫会拒收
#   （投递了但桥什么也没收到 —— 排查时先看 su_jobs 里有没有那份 .rb）。
SPEC = ENV['YZ_SPEC']
_bn = File.basename(SPEC.to_s, '.json')                 # _ny27_floors_spec
NAME = _bn.sub(/\A_/, '').sub(/_floors_spec\z/, '')     # ny27
PREFIX = NAME.empty? ? '' : "_#{NAME}"

m = Sketchup.active_model
v = m.active_view

# 拍哪几层：从模型里实际存在的组派生，而不是写死。
#   `yingzao-F<n>` 按 n 升序；屋顶组名不含数字，排在最后。
#   ★ 不用 band 号推组名 —— band 是 spec 的内部编号，屋顶的 band 随楼层数变（5 层楼是 5、6 层楼是 6），
#     写死就会拍错层的组（见文件头 ①）。
_gnames = m.entities.grep(Sketchup::Group).map { |g| g.name.to_s }
_fs = _gnames.select { |n| n =~ /\Ayingzao-F\d+\z/ }
      .sort_by { |n| n.sub('yingzao-F', '').to_i }
      .map { |n| [n.sub('yingzao-F', '').to_i, n.sub('yingzao-', '')] }
BANDS = _fs.dup
BANDS << [_fs.map { |b, _| b }.max + 1, '屋顶'] if _fs.any? && _gnames.include?('yingzao-屋顶')
SMALL = [820, 520]                 # 近景画布（看字形用）

def shoot(v, path, w = nil, h = nil)
  w ||= v.vpwidth
  h ||= v.vpheight
  v.write_image(path, w, h, true, 0.9)
  File.exist?(path) ? File.size(path) : -1
end

def find_page(m, name)
  m.pages.find { |pg| pg.name.to_s == name }
end

R = { 'name' => NAME, 'vp' => [v.vpwidth, v.vpheight], 'shots' => [],
      'bands' => BANDS.map { |b, l| [b, l] }, 'pages_before' => m.pages.map(&:name) }
BANDS.each do |b, lab|
  gname = "yingzao-#{lab}"
  g = m.entities.grep(Sketchup::Group).find { |x| x.name.to_s == gname }
  unless g
    R['shots'] << ["#{gname}_miss", 'no group']
    next
  end
  pg = find_page(m, "#{lab} 本层")
  if pg
    m.pages.selected_page = pg      # 切页 = 应用该页的图层可见性，这才叫「只显本层」
    R['shots'] << ["#{gname}_page", pg.name]
  else
    R['shots'] << ["#{gname}_page", 'no page']
  end
  bb = g.bounds
  c = bb.center
  r = [bb.width, bb.height, bb.depth].max
  texts = g.entities.grep(Sketchup::Text)

  # ① 全层斜俯视
  v.camera.perspective = true
  v.camera.set(Geom::Point3d.new(c.x - r * 0.35, c.y - r * 0.75, c.z + r * 0.95),
               Geom::Point3d.new(c.x, c.y, c.z + 0.5), Geom::Vector3d.new(0, 0, 1))
  R['shots'] << ["#{gname}_floor", shoot(v, "#{OUT}_su#{PREFIX}_#{gname}_floor.png")]

  # ② 近景：前几间房的注释锚点撑成的框
  if texts.length >= 3
    pick = texts[0, 6]
    pts = pick.map(&:point)
    cx = pts.sum(&:x) / pts.length
    cy = pts.sum(&:y) / pts.length
    cz = pts.sum(&:z) / pts.length
    span = [pts.map(&:x).max - pts.map(&:x).min, pts.map(&:y).max - pts.map(&:y).min].max
    span = 8.0 if span < 3.0
    v.camera.set(Geom::Point3d.new(cx - span * 0.15, cy - span * 0.85, cz + span * 0.75),
                 Geom::Point3d.new(cx, cy, cz), Geom::Vector3d.new(0, 0, 1))
    R['shots'] << ["#{gname}_labels",
                   shoot(v, "#{OUT}_su#{PREFIX}_#{gname}_labels.png", SMALL[0], SMALL[1])]
    R['shots'] << ["#{gname}_label_texts", pick.map(&:text)]
  else
    R['shots'] << ["#{gname}_labels", "注释只有 #{texts.length} 条"]
  end
end

# ③ 每层的「平面」页（关掉「墙」「窗」两类构件）。
#    ★ 2026-09-14 修：原注释是「**不动相机** —— 页面自带正射俯视相机」，实测没兑现：
#      · `plan_F0` 拍成了**斜视**且只截到一角（相机停在上一次"本层"那张的透视视角上）；
#      · `plan_F7` 虽然是正射俯视，但缩成画面 1/4（没有框住本层）。
#      作为"每层平面图"交付，这两张都不能看。所以现在**显式设相机**：
#      正射（perspective=false）+ 正上方俯视 + 用本层组的 bbox 定高 + zoom_extents。
#      同时把"页面自带相机"的状态**照旧报出来**（那两个字段就是原意图的验证，别丢）。
m.pages.select { |pg| pg.name.to_s.end_with?(' 平面') }.each do |pg|
  m.pages.selected_page = pg
  hid = (pg.layers.map { |x| x.respond_to?(:name) ? x.name : x.to_s } rescue [])
  tag = pg.name.to_s.split(' ').first
  gname = "yingzao-#{tag}"
  grp = m.entities.grep(Sketchup::Group).find { |x| x.name.to_s == gname }
  # 页面自带相机（原设计想验的就是这两个数：正射？俯视？）
  pc = v.camera
  R["plan_#{tag}_page_cam"] = { 'perspective' => (pc.perspective? rescue nil),
                                'eye_z_m' => (pc.eye.z.to_m.round(3) rescue nil),
                                'tgt_z_m' => (pc.target.z.to_m.round(3) rescue nil) }
  if grp
    bb = grp.bounds
    c = bb.center
    span = [bb.width, bb.height].max
    v.camera.perspective = false                       # ← 建筑平面必须正射
    v.camera.set(Geom::Point3d.new(c.x, c.y, c.z + span * 1.2),
                 Geom::Point3d.new(c.x, c.y, c.z),
                 Geom::Vector3d.new(0, 1, 0))            # 正上方俯视，北朝上
    (v.zoom_extents rescue nil)                        # 框住本层可见实体
    # ★ 打印要 `.to_m`：`bb.width` 是 **Length（内部英寸）**，直接 `%.1f` 会印成英寸
    #   （实测把 129.3m 印成 "span=5090.6m" —— 数字吓人且错，属于"量一个写另一个"）。
    R["plan_#{tag}_fitted_on"] = '%s span=%.1fm (h=%.1fm)' % [
      gname, span.to_m, (c.z + span * 1.2).to_m]
  end
  R['shots'] << ["plan_#{tag}", hid, shoot(v, "#{OUT}_su#{PREFIX}_plan_#{tag}.png", 1100, 700)]
end

# ④ 总览：全可见 + 整栋斜俯视（呈现的封面图）。先切「总览」页再动相机。
#    ★ 封面必须**关掉用途标注**再拍：全开着在整栋视距下叠成一团墨，看不出楼。
#      拍完**立刻还原**并记进台账（改了不还原 = 存盘后各页标注全没了，属静默改文档）。
ov = find_page(m, '总览')
if ov
  m.pages.selected_page = ov
  ltag = m.layers.find { |x| x.name.to_s == 'yingzao-用途标注' }
  lbl_before = ltag ? ltag.visible? : nil
  ltag.visible = false if ltag
  gs = m.entities.grep(Sketchup::Group)
  bb = gs.map(&:bounds).reduce { |a, x| a.add(x) } if gs.length > 0
  if bb
    c = bb.center
    r = [bb.width, bb.height, bb.depth].max
    v.camera.perspective = true
    v.camera.set(Geom::Point3d.new(c.x - r * 0.55, c.y - r * 0.85, c.z + r * 1.05),
                 Geom::Point3d.new(c.x, c.y, c.z * 0.35), Geom::Vector3d.new(0, 0, 1))
    R['shots'] << ['overview', shoot(v, "#{OUT}_su#{PREFIX}_overview.png", 1280, 800)]
    R['overview_bbox'] = [bb.min.x, bb.min.y, bb.min.z, bb.max.x, bb.max.y, bb.max.z].map { |x| x.to_m.round(3) }
  end
  # 还原标注可见性（封面拍完就该恢复原状），并把「拍前 → 拍后」写进台账自证没改坏文档
  ltag.visible = lbl_before if ltag && !lbl_before.nil?
  R['overview_label_tag'] = ['yingzao-用途标注', lbl_before, ltag ? ltag.visible? : nil]
end
R['pages_after'] = m.pages.map(&:name)
R['done'] = true
R
