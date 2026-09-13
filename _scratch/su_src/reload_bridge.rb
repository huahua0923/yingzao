# -*- coding: utf-8 -*-
# 把修好的桥热重载进当前 SU 会话（不用重启 SU）。`module` 是重开，实例变量沿用，
# 所以新代码里的 @busy/@ticking 闸门立刻生效；旧定时器链还挂着，但它调的也是新代码。
PLUGIN = 'C:/Users/Administrator/AppData/Roaming/SketchUp/SketchUp 2023/SketchUp/Plugins/yingzao_bridge.rb'
before = File.read(PLUGIN, mode: 'rb').scan(/@busy/).length
load PLUGIN
after = File.read(PLUGIN, mode: 'rb').scan(/@busy/).length
{ 'plugin_has_guard' => after.positive?, 'occurrences' => after, 'was' => before,
  'pid' => Process.pid, 'secs' => Time.now.strftime('%H:%M:%S') }
