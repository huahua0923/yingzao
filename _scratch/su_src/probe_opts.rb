# -*- coding: utf-8 -*-
# 把模型的所有渲染选项与风格名一次性列出来（RenderingOptions 可枚举）。
# 「剖切图里那片深灰是谁画的」查到最后只剩下「SU 自己画的」这一个解释，
# 那就把可用的开关列全，再决定按哪个开关关掉它。
m = Sketchup.active_model
opts = {}
m.rendering_options.each_pair { |k, v| opts[k] = v.is_a?(Numeric) || v == true || v == false ? v : v.to_s }
st = m.styles.selected_style
{ 'style' => st && st.name,
  'render_mode' => (m.rendering_options['RenderMode'] rescue nil),
  'section_opts' => opts.select { |k, _| k.downcase.include?('section') },
  'all_keys' => opts.keys.sort,
  'n' => opts.length,
  'materials' => m.materials.map(&:name).sort,
  'section_planes' => m.entities.grep(Sketchup::SectionPlane).length }
