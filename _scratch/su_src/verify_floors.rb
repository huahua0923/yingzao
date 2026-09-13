# -*- coding: utf-8 -*-
# 独立复核：**只读**模型，把 SU 里真实存在的几何量出来，写到 _floors_verify.json。
# 与 build_floors.rb 的 .out 的区别很重要：那份是**建体脚本自己报的**，这份是**重新量的**。
# 量四样：
#   ① 逐材质**正面面积**（每个面按 `material` 记一次，单位 m²）—— 与 spec 的解析面积
#      （su_spec_floors.color_areas，已在 ny27 上验到 0.00%）逐色对账。用途地垫是单色的，
#      没有正反配对问题，所以那 13 个色必须对得上；立面/室内两色会有逐面配对互换，
#      所以额外报「两色合计」。
#   ② 每组的面数 / 注释条数 / 层名 —— 验「每层一个组 + 一条注释挂对组」。
#   ③ 场景表：名字 + `page.layers`（被关掉的层）+ 该页保留的层 —— 验「每层能单独解开」。
#   ④ 面/边落在哪个 Tag 上 —— 验「关掉 `yz构件-墙`/`yz构件-窗` 能关干净」：
#      我的组里的面与边必须**全部**在构件 Tag 上，一个都不许留在 Layer0。
# 不改任何东西（不建几何、不动相机、不切页）。
require 'json'

OUT = 'D:/gym3d/_scratch/su_jobs/_floors_verify.json'

# 递归收集（二级组之后面/边不再直接挂在本层组上；不递归就会「量不到」而不是「量出来是 0」）
def all_faces(ents)
  fs = ents.grep(Sketchup::Face)
  ents.grep(Sketchup::Group).each { |g| fs.concat(all_faces(g.entities)) }
  fs
end

def all_edges(ents)
  es = ents.grep(Sketchup::Edge)
  ents.grep(Sketchup::Group).each { |g| es.concat(all_edges(g.entities)) }
  es
end

# 递归数实体（含二级组自身那一层）
def count_all(ents)
  n = ents.length
  ents.grep(Sketchup::Group).each { |g| n += count_all(g.entities) }
  n
end

m = Sketchup.active_model
u = m.options['UnitsOptions']['LengthUnit']
LEN2M = { 0 => 0.0254, 1 => 0.3048, 2 => 0.001, 3 => 0.01, 4 => 1.0 }[u] || 1.0
mine = m.entities.grep(Sketchup::Group).select { |g| g.name.to_s.start_with?('yingzao-') }

R = { 'unit' => u, 'len2m' => LEN2M, 'group_count' => mine.length,
      'group_names' => mine.map { |g| g.name.to_s },
      'top_entities' => m.entities.map { |e| "#{e.class.name.split('::').last}:#{(e.respond_to?(:name) ? e.name : '').to_s}" } }

# ① 逐材质正面面积（面只按 `material` 记一次；背面另记一列，供参考）
fa = Hash.new(0.0)
fc = Hash.new(0)
ba = Hash.new(0.0)
# ①b 实体落在哪个 **Tag** 上 —— 独立量「关掉某个构件 Tag 能不能关干净」：
#     面/边必须全部落在构件 Tag（`yz构件-*`）上，一个都不该留在 Layer0。
f_by_tag = Hash.new(0)
e_by_tag = Hash.new(0)
# ①c 「散在 Layer0」的到底是哪一类、长什么样 —— 只报数不足以定性，
#     所以连**组名 / 材质 / 面积 / 中心 / 边数**一起抄下来（`add_face` 在同容器里
#     并共面共享边时 SU 会**合并**出新面，新面默认落在 Layer0 ⇒ 这类面没有我的材质）。
stray_faces = []
by_group_tag = {}
mat_by_group = {}
R['groups'] = mine.map do |g|
  faces = all_faces(g.entities)
  texts = g.entities.grep(Sketchup::Text)
  # ②b 二级组台账：一个 sub 名一个容器 —— 独立量「容器分没分成、面落在哪个 Tag 上」
  subs = {}
  g.entities.grep(Sketchup::Group).each do |sg|
    sf = all_faces(sg.entities)
    st = Hash.new(0)
    sf.each { |f| (st[f.layer.name] += 1 rescue st['<无>'] += 1) }
    subs[sg.name] = { 'faces' => sf.length, 'edges' => all_edges(sg.entities).length,
                      'tag' => (sg.layer.name rescue nil),
                      'faces_by_tag' => st.sort_by { |_, v| -v }.to_h,
                      'area_m2' => (sf.sum { |f| f.area } * (LEN2M**2)).round(3) }
  end
  gt = Hash.new(0)
  faces.each do |f|
    if f.material
      fa[f.material.name] += f.area * (LEN2M**2)
      fc[f.material.name] += 1
    end
    ba[f.back_material.name] += f.area * (LEN2M**2) if f.back_material
    (f_by_tag[f.layer.name] += 1 rescue f_by_tag['<无>'] += 1)
    (gt[f.layer.name] += 1 rescue gt['<无>'] += 1)
    ln = (f.layer.name rescue nil)
    unless ln && ln.start_with?('yz构件-')
      c = f.bounds.center
      stray_faces << [g.name, ln, (f.material ? f.material.name : nil),
                      (f.area * (LEN2M**2)).round(4), f.edges.length,
                      [c.x.to_m, c.y.to_m, c.z.to_m].map { |v| v.round(3) }]
    end
  end
  by_group_tag[g.name] = gt.sort_by { |_, v| -v }.to_h
  # ①e 逐组逐色面积：逐色对账差一大截时，靠它定位到**哪一层哪一类**
  garea = Hash.new(0.0)
  faces.each { |f| garea[f.material.name] += f.area * (LEN2M**2) if f.material }
  mat_by_group[g.name] = garea.map { |k, v| [k, v.round(3)] }.sort_by { |_, v| -v }.to_h
  all_edges(g.entities).each do |e|
    (e_by_tag[e.layer.name] += 1 rescue e_by_tag['<无>'] += 1)
  end
  b = g.bounds
  { 'name' => g.name, 'layer' => (g.layer.name rescue nil),
    'faces' => faces.length, 'texts' => texts.length, 'subs' => subs,
    'bbox_m' => [b.min.x.to_m, b.min.y.to_m, b.min.z.to_m,
                 b.max.x.to_m, b.max.y.to_m, b.max.z.to_m].map { |v| v.round(3) },
    'text_sample' => texts.first(3).map { |t| [t.text, (t.layer.name rescue nil)] } }
end
R['mat_front_m2'] = fa.map { |k, v| [k, v.round(4)] }.sort_by { |_, v| -v }.to_h
# ①d **所有**面的面积（不看材质）+ 没有材质的面 ——
#     逐色对账差一大截时，先问「是不是有面压根没材质」（没材质的面不计进逐色表 ⇒ 看着像丢了面积）
all_area = 0.0
no_mat_area = 0.0
no_mat_n = 0
back_only_n = 0
mine.each do |g|
  all_faces(g.entities).each do |f|
    ar = f.area * (LEN2M**2)
    all_area += ar
    unless f.material
      no_mat_area += ar
      no_mat_n += 1
      back_only_n += 1 if f.back_material
    end
  end
end
# ①f **水平面台账**（> HORIZ_MIN_M2 的）：直接验「地面/屋顶的盖面在不在」——
#     每个带在楼板底面那个 z 上都该有一块 == 本层足迹的板面；屋面板的上下盖面同在中招名单里。
# ★ 阈值必须**低于最小被检板面**：F4 翼楼女儿墙是**环**（环面积 45.08/47.68 m²），
#   原来卡在 50 ⇒ 这两块板整个被滤出台账，检查报「没有这一块」——**假报**。
#   阈值是量具的量程，量程之外不是「合格」而是「没量」。（2026-09-12 实测踩过。）
HORIZ_MIN_M2 = 10.0
R['big_horiz'] = {}
mine.each do |g|
  R['big_horiz'][g.name] = all_faces(g.entities)
                              .select { |f| f.normal.z.abs > 0.99 }
                              .map { |f| [(f.bounds.center.z.to_m * 1000).round / 1000.0,
                                          (f.area * (LEN2M**2)).round(3)] }
                              .select { |_, a| a > HORIZ_MIN_M2 }.sort
end
R['horiz_min_m2'] = HORIZ_MIN_M2
R['area_all_faces_m2'] = all_area.round(4)
R['area_no_mat_m2'] = no_mat_area.round(4)
R['faces_no_mat_n'] = no_mat_n
R['faces_no_mat_with_back_n'] = back_only_n
R['faces_by_tag'] = f_by_tag.sort_by { |_, v| -v }.to_h
R['faces_by_group_tag'] = by_group_tag
R['mat_by_group_m2'] = mat_by_group
R['stray_faces_n'] = stray_faces.length
R['stray_faces_sample'] = stray_faces.first(12)
R['stray_area_m2'] = stray_faces.sum { |x| x[3] }.round(4)
R['edges_by_tag'] = e_by_tag.sort_by { |_, v| -v }.to_h
R['mat_front_faces'] = fc.sort_by { |_, v| -v }.to_h
R['mat_back_m2'] = ba.map { |k, v| [k, v.round(4)] }.sort_by { |_, v| -v }.to_h

# ② 场景表（不切页，只读记录）
R['pages'] = m.pages.map do |pg|
  { 'name' => pg.name,
    'hidden' => (pg.layers.map { |x| x.respond_to?(:name) ? x.name : x.to_s } rescue ['ERR']) }
end
R['tags'] = m.layers.map(&:name)
R['materials_yz'] = m.materials.map(&:name).select { |x| x.start_with?('yz') }.sort
R['texts_total'] = mine.sum { |g| g.entities.grep(Sketchup::Text).length }
R['faces_total'] = mine.sum { |g| all_faces(g.entities).length }
R['subgroups_total'] = mine.sum { |g| g.entities.grep(Sketchup::Group).length }
R['entities_total'] = mine.sum { |g| count_all(g.entities) }

begin
  File.open(OUT, 'wb') { |f| f.write(JSON.generate(R)) }
  R['written'] = OUT
rescue StandardError => e
  R['write_err'] = "#{e.class}: #{e.message}"
end
R['note'] = '只读复核：面按 material 记一次；立面/室内两色会有逐面配对互换，看两色合计'
R
