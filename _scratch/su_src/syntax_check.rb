# -*- coding: utf-8 -*-
# 语法预检：把目标 .rb 交给 **SU 自带的那一版 Ruby** 编译一遍，只编译不执行。
# 为什么绕这一道：本机没有 ruby，而真正要跑的是 SU 2023 里的 2.7.x —— 只有它能说明语法过不过。
# 走 su_deploy.sh 的 SPEC 槽传目标路径（sed 会把下面这行换成目标文件的绝对路径）：
#   bash _scratch/su_deploy.sh syntax_check.rb /d/gym3d/_scratch/su_src/build_floors.rb
# 注意：只 compile、不 eval，所以对模型零影响（连操作栈都不碰）。
SPEC = ENV['YZ_SPEC'] || 'D:/gym3d/_scratch/su_src/build_floors.rb'
src = File.read(SPEC, mode: 'rb').force_encoding('UTF-8')
R = { 'ruby' => RUBY_VERSION, 'patchlevel' => RUBY_PATCHLEVEL, 'file' => SPEC,
      'bytes' => src.bytesize, 'lines' => src.lines.count }
begin
  RubyVM::InstructionSequence.compile(src, SPEC)
  R['syntax'] = 'OK'
rescue SyntaxError => e
  R['syntax'] = 'FAIL'
  R['err'] = e.message
rescue StandardError => e
  R['syntax'] = "ERR #{e.class}: #{e.message}"
end
# 顺带把「本文件里用到的 SU API 名字」列出来，便于对照探针结论（纯字符串扫描，不碰模型）
R['api_names'] = ['m.layers', 'layers.add', 'layers.remove', 'visible=', 'visible?',
                  'add_text', 'display_leader=', 'set_visibility', 'selected_page=',
                  'use_camera=', 'use_hidden_layers=', 'pages.add', 'zoom_extents',
                  'page.camera=', 'model.textoptions'].select { |n| src.include?(n) }
R
