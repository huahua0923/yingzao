# -*- coding: utf-8 -*-
# 只读探针：当前文档的**落盘状态**。为「批量建 49 栋、各存一个 .skp」做准备。
#
# 为什么先问这一步：`build_floors.rb` 没有 new_document / save，
# 且它有一条安全闸「顶层有任何不属于我的实体就拒绝建、不撞不删」。
# 要批量，就得驱动 SU 开新文档 + 存盘；而**开新文档会丢掉当前文档**——
# ny27 那座已验证的楼若没存过盘，一句 `Sketchup.file_new` 就把它抹了。
# 所以先只读地问清楚：存过没有、路径是什么、顶层有什么。
#
# 本探针**只读**：不建、不删、不存、不开新文档、不动相机与页。
require 'json'

m = Sketchup.active_model

# `model.path` 空串 = 从没存过盘（新建后未保存）。这是判「能不能安全开新文档」的唯一依据。
path = (m.path.to_s rescue '')
R = {
  'path'        => path,
  'title'       => (m.title.to_s rescue ''),
  'saved'       => !path.empty?,
  'modified'    => (m.modified? rescue nil),
  'entities'    => m.entities.length,
  'groups'      => m.entities.grep(Sketchup::Group).map { |g| g.name.to_s },
  'groups_n'    => m.entities.grep(Sketchup::Group).length,
  'other_ents'  => m.entities.reject { |e| e.is_a?(Sketchup::Group) }
                    .group_by { |e| e.class.name.split('::').last }
                    .map { |k, v| [k, v.length] }.to_h,
  'pages'       => m.pages.map(&:name),
  'layers_n'    => m.layers.length,
  'units'       => m.options['UnitsOptions']['LengthUnit'],
  # SU 版本/平台：批量脚本要用到 file_new，得知道这台是哪个版本（API 差异按实测走）
  'su_version'  => Sketchup.version.to_s,
  'su_ver_num'  => Sketchup.version_number.to_s,
  # 我关心的 API 存不存在（**探针实测**，不照记忆写）
  'api' => {
    'Sketchup.file_new'          => Sketchup.respond_to?(:file_new),
    'Sketchup.open_file'         => Sketchup.respond_to?(:open_file),
    'Sketchup.save'              => Sketchup.respond_to?(:save),
    'model.save'                 => m.respond_to?(:save),
    'model.save_as'              => m.respond_to?(:save_as),
    'model.save_copy'            => m.respond_to?(:save_copy),
    'model.close'                => m.respond_to?(:close),
    'Sketchup.template'          => Sketchup.respond_to?(:template),
    'Sketchup.create_text'       => Sketchup.respond_to?(:create_text),
  },
  'done' => true
}

# 「建到一半留下的自己人」也一并报：有的话说明上次建体没清干净
R['mine'] = m.entities.grep(Sketchup::Group)
             .select { |g| g.name.to_s =~ /\Ayingzao-/ }
             .map { |g| [g.name.to_s, g.entities.length] }
R
