# -*- coding: utf-8 -*-
# 营造 SU 桥 —— 让命令行/脚本能驱动 SketchUp 画图（SU 无 headless，只能靠 Plugins 目录常驻）。
#
# 原理：本文件放 Plugins 目录，每次 SU 启动自动加载；它**启动即跑一次**任务目录里的
#       *.rb（不依赖 UI 定时器 —— 实测 SU 的重复定时器在窗口失焦后会停摆），
#       之后用「一次性定时器自我重武装」的链继续轮询。任务用 SU 自己的 Ruby 执行，
#       结果写同名 .out，然后删掉任务文件。
#
# 用法（在 SU 之外）：
#   echo '...' > D:/gym3d/_scratch/su_jobs/hello.rb
#   启动 SU → 任务自动执行 → 看 D:/gym3d/_scratch/su_jobs/hello.out
#
# 危险开关：任务目录放一个名为 quit 的空文件 → 执行完所有任务后关掉 SU。
# 卸载：删掉本文件即可（不留任何残留）。
#
# ---------------------------------------------------------------- 重入这件事
# `Model#export` 会**泵一轮消息循环**，排队的 UI 定时器就在导出途中烧掉了。于是
# tick → run_pending 会**在一次任务的 eval 里被嵌套调用**；而那时任务文件还没删
# （外层才跑到一半），于是同一个任务被递归重跑一遍 —— 越往后导的格式越多、递归越深，
# 最后把 SU 拖死（实测：15 个格式的探针把 SU 崩了两次，`bridge loaded` 连刷 15 次）。
#   两个闸门一起上：
#     1) `@busy` —— 重入的 run_pending 直接返回（任务 eval 期间不许再来一遍）；
#     2) 认领任务文件用 `File.rename` 到 `.rb.inflight`（原子，且不再被 `*.rb` 匹配上），
#        这样即使另有一条定时器链/另一份被 eval 的桥，也抢不到同一个任务。
#   另外 SU 加载某些导出器扩展时会把 Plugins/*.rb 重新 eval 一遍，`boot` 因此可能被
#   调多次 —— `@ticking` 保证只装一条定时器链（`module` 是重开，实例变量不会清）。
#
# 安全边界（为什么这里必须 eval）：本桥存在的意义就是执行**本地**任务脚本，
#   等价于 SU 自带的「Ruby 控制台」——能往 JOB_DIR 写文件的人本来就能直接写
#   Plugins 目录，权限没有放大。JOB_DIR 写死在仓库的 _scratch 下、不进版本库、
#   不联网、不接收外部输入。若要收紧，把 JOB_DIR 换成仅当前用户可写的目录即可。
require 'sketchup.rb'

module YingzaoBridge
  JOB_DIR = 'D:/gym3d/_scratch/su_jobs'.freeze
  LOG     = File.join(JOB_DIR, '_bridge.log').freeze
  INFLIGHT = '.inflight'.freeze

  def self.log(msg)
    File.open(LOG, 'ab') { |f| f.write("#{Time.now.strftime('%H:%M:%S')} #{msg}\n") }
  rescue StandardError
    nil
  end

  def self.write_out(path, text)
    File.open(path, 'wb') { |f| f.write(text.to_s.dup.force_encoding('UTF-8')) }
  rescue StandardError => e
    begin
      File.open(path, 'wb') { |f| f.write("write_out failed: #{e.class}: #{e.message}") }
    rescue StandardError
      nil
    end
  end

  # 任务源码一律按 UTF-8 读（任务里有中文注释，别让默认编码把它变成 SyntaxError）
  # inflight：已经原子认领过来的那一份（不是原文件名）。
  def self.run_job(job, inflight)
    out = job.sub(/\.rb\z/, '.out')
    begin
      src = File.read(inflight, mode: 'rb').force_encoding('UTF-8')
      result = eval(src, TOPLEVEL_BINDING, job) # rubocop:disable Security/Eval
      write_out(out, "OK\n#{result.inspect}")
      log("ok #{File.basename(job)}")
    rescue Exception => e # rubocop:disable Lint/RescueException
      write_out(out, "ERR #{e.class}: #{e.message}\n#{(e.backtrace || []).first(10).join("\n")}")
      log("err #{File.basename(job)} #{e.class}: #{e.message}")
    ensure
      begin
        File.delete(inflight)
      rescue StandardError
        nil
      end
    end
  end

  def self.run_pending
    return unless File.directory?(JOB_DIR)
    return if @busy # ← 重入闸：任务 eval 期间（export 泵消息循环）不许再进来

    @busy = true
    begin
      Dir.glob(File.join(JOB_DIR, '*.rb')).sort.each do |job|
        inflight = "#{job}#{INFLIGHT}"
        begin
          File.rename(job, inflight) # 原子认领；抢不到说明别人已认领
        rescue StandardError
          next
        end
        run_job(job, inflight)
      end
    ensure
      @busy = false
    end
  end

  # 一次性定时器链：每跳重武装，任何异常都不许逃出去（逃出去 SU 会把定时器废掉）
  def self.tick
    begin
      run_pending
      quit = File.join(JOB_DIR, 'quit')
      if File.exist?(quit)
        File.delete(quit)
        log('quit requested')
        Sketchup.quit if Sketchup.respond_to?(:quit)
        return
      end
    rescue Exception => e # rubocop:disable Lint/RescueException
      log("tick ERR #{e.class}: #{e.message}")
    ensure
      UI.start_timer(2.0, false) { YingzaoBridge.tick }
    end
  end

  def self.boot
    log("bridge loaded, model=#{Sketchup.active_model.nil? ? 'nil' : 'ok'}")
    run_pending           # 启动即跑，关键路径不依赖定时器
    return if @ticking    # 扩展加载会重 eval 本文件，别叠出第二条定时器链

    @ticking = true
    tick
  end
end

UI.start_timer(1.0, false) { YingzaoBridge.boot }
