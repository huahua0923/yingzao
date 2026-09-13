# -*- coding: utf-8 -*-
# 小探针：只会问「Tag / Layer 集合到底从哪拿」，不动任何几何。
m = Sketchup.active_model
R = {}
R['respond_to?(:tags)'] = m.respond_to?(:tags)
R['respond_to?(:layers)'] = m.respond_to?(:layers)
begin
  x = m.tags
  R['m.tags_class'] = x.class.to_s
  R['m.tags_inspect'] = x.inspect[0, 300]
rescue => e
  R['m.tags_err'] = "#{e.class}: #{e.message}"
end
begin
  y = m.layers
  R['m.layers_class'] = y.class.to_s
  R['m.layers_inspect'] = y.inspect[0, 300]
  R['m.layers_count'] = (y.respond_to?(:count) ? y.count : 'n/a')
  R['m.layers_names'] = (y.map { |z| z.name } rescue "map失败: #{$!.class}")
rescue => e
  R['m.layers_err'] = "#{e.class}: #{e.message}"
end
R['model_methods_tag'] = m.methods.grep(/tag/i).sort
R['model_methods_layer'] = m.methods.grep(/layer/i).sort
R['layers_class_methods'] = (Sketchup::Layers.instance_methods(false).sort rescue 'n/a')
R['model_class_has_layers'] = Sketchup::Model.instance_methods(false).grep(/layer|tag/).sort
R
