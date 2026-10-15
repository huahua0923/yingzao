# SU 无人值守启动器（第二步：contours → 成面拉体 → 导正式件）
#
# 为什么要一个文件、而不是一行命令直接调：
#   ① 本机实测 —— **从 Git Bash 传中文 argv 会被改坏**（`项目` 变成 `y??v`），
#      所以路径**不经过任何 shell**，全部由 `$PSScriptRoot` 推出来；本文件里**一个中文都不沾**。
#   ② 用 `Start-Process` 起 —— 与本会话的控制台**解绑**。
#      实测教训：挂在会话控制台下的 GUI 程序，控制台被收走几秒后窗口会收到**外部 close**，
#      退出码 0、无栈，与「跑得好好的」同形（memory: console-teardown-closes-gui-window）。
#
# 跑之前必须先杀净 SketchUp 并**无条件等 ≥5 s**（SU 是单实例，会静默接手：
# 新实例把参数交给旧的然后自己退出，脚本一行不跑、零报错）。本脚本只负责起，不负责杀。
#
# 用法（单行，直接粘）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\项目\cdut3d\rebuild\06_su\_run_su_step2.ps1"
#
# 判「这趟进没进去」只认 build_log.txt 里**新的** `SCRIPT_ENTERED` 行；
# 判「跑完没有」只认**新的** `EXPORT … ok=true` 与 `DONE`
# （半截件看着也像文件：README §7 第 9 条实测 5 302 081 / 13 310 958）。

$dir = $PSScriptRoot                                    # …\rebuild\06_su
$exe = 'C:\Program Files\SketchUp\SketchUp 2023\SketchUp.exe'
# ★ 2026-10-16 修：原来这里写的是 'c006_su.skp' —— 那是**上一趟的输出件**（7.40 MB）。
#   两处不对：① 它自己的 Ruby 头（`su_step2_build.rb` 第 6~7 行）写的跑法就是拿
#   `c006_su_1f.skp`（664,305 B）起；② `EXPORT.md:498` 记的最后那趟成功，处置之一正是
#   「换 664 KB 的小文档启动」。拿 7.4 MB 正式件起 = 每次启动先吞整个成品，与记的做法相反。
#   ★ 输出**不受影响**：存到哪写在 `su_step2_build.rb:147` 里（`#{DIR}/c006_su.skp`），
#     与起始文档是哪个无关。
$skp = Join-Path $dir 'c006_su_1f.skp'                   # 必须给一个「已存在的文档」，否则欢迎屏挡启动
$rb  = Join-Path $dir 'su_step2_build.rb'

foreach ($p in @($exe, $skp, $rb)) {
    if (-not (Test-Path -LiteralPath $p)) {
        Write-Output ('MISSING ' + $p)
        exit 4
    }
}

$proc = Start-Process -FilePath $exe -ArgumentList @($skp, '-RubyStartup', $rb) -PassThru
Write-Output ('STARTED pid=' + $proc.Id + ' skp=' + $skp + ' rb=' + $rb)
