# -*- coding: utf-8 -*-
# 只读探针：**贴近**看一条用途注释，验中文有没有变方框（tofu）。
#
# 为什么单开这个：`shots_floors_fleet.rb` 的近景是按「前 6 条注释撑成的框」自动取景的，
# 一层房间横跨几十米时相机会被撑得很远 —— SU 的屏幕文字是**固定像素高**，离远了两三个像素，
# 截图上就是一团墨，看不出字形。这里改成**照准单条注释**、由近及远拍三档。
#
# 不动几何、不切页以外的任何状态；拍完把选中的页还原。
require 'json'

OUT = 'D:/gym3d/_scratch/su_jobs/'
SPEC = ENV['YZ_SPEC']
_bn = File.basename(SPEC.to_s, '.json')
NAME = _bn.sub(/\A_/, '').sub(/_floors_spec\z/, '')
PREFIX = NAME.empty? ? '' : "_#{NAME}"

m = Sketchup.active_model
v = m.active_view

# 挑一条注释：取第一个 yingzao-F* 组里的第一条 Text（挑不到就报出来，别静默返回）
gs = m.entities.grep(Sketchup::Group).select { |g| g.name.to_s =~ /\Ayingzao-F\d+\z/ }
            .sort_by { |g| g.name.to_s.sub('yingzao-F', '').to_i }
R = { 'name' => NAME, 'groups' => gs.map { |g| g.name.to_s }, 'shots' => [] }
# ★ 顶层不能写 `return`（本文件是被 eval 进来的，top-level return 抛 LocalJumpError）
g = gs.first
texts = g ? g.entities.grep(Sketchup::Text) : []
if g.nil?
  R['err'] = '一个 yingzao-F* 组都没有'
elsif texts.empty?
  R['err'] = "#{g.name} 组里没有 Text"
else
  t = texts.first
  pt = t.point
  R['text'] = t.text
  R['anchor_m'] = [pt.x.to_m.round(3), pt.y.to_m.round(3), pt.z.to_m.round(3)]

  prev = m.pages.selected_page
  pg = m.pages.find { |x| x.name.to_s == "#{g.name.to_s.sub('yingzao-', '')} 本层" }
  if pg
    m.pages.selected_page = pg
    R['page'] = pg.name
  else
    R['page'] = nil
  end

  # 由近及远三档：2.5m / 5m / 9m。文字挂在锚点上，从稍高处斜看。
  [2.5, 5.0, 9.0].each do |d|
    v.camera.perspective = true
    v.camera.set(Geom::Point3d.new(pt.x - d * 0.35, pt.y - d * 0.75, pt.z + d * 0.55),
                 Geom::Point3d.new(pt.x, pt.y, pt.z), Geom::Vector3d.new(0, 0, 1))
    f = "#{OUT}_su#{PREFIX}_glyph_#{d.to_s.gsub('.', 'p')}m.png"
    v.write_image(f, 900, 480, true, 0.95)
    R['shots'] << [f.split('/').last, (File.exist?(f) ? File.size(f) : -1)]
  end

  m.pages.selected_page = prev if prev
  R['page_restored'] = (m.pages.selected_page ? m.pages.selected_page.name.to_s : nil)
  R['done'] = true
end
R
