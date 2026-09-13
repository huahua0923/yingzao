# -*- coding: utf-8 -*-
# 最小探针：桥还活着吗？顺带报自己的进程号与启动时刻（PID 变了 = SU 崩过重启过）。
{ 'pong' => true, 'pid' => Process.pid, 'secs' => Time.now.strftime('%H:%M:%S'),
  'unit' => Sketchup.active_model.options['UnitsOptions']['LengthUnit'],
  'n_faces' => Sketchup.active_model.entities.grep(Sketchup::Face).length }
