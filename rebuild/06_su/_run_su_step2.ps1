# SU 无人值守启动器（第二步：contours → 成面拉体 → 导正式件）
#
# 为什么要一个文件、而不是一行命令直接调：
#   ① 本机实测 —— **从 Git Bash 传中文 argv 会被改坏**（`项目` 变成 `y??v`），
#      所以路径**不经过任何 shell**，全部由 `$PSScriptRoot` 推出来；
#      运行期印出来的字符串**一律 ASCII**（本文件里的中文只在注释里）。
#   ② 用 `Start-Process` 起 —— 与本会话的控制台**解绑**。
#      实测教训：挂在会话控制台下的 GUI 程序，控制台被收走几秒后窗口会收到**外部 close**，
#      退出码 0、无栈，与「跑得好好的」同形（memory: console-teardown-closes-gui-window）。
#
# ★ 2026-10-16 改：本脚本从「只负责起、不负责杀」升级成「杀 + 起 + 等 + 没成就重跑」。
#   依据（都在 build_log.txt 里现算，不是估的）：整份日志 **27 趟 SCRIPT_ENTERED / 18 趟
#   `[pid] DONE`** ⇒ 约 30% 的趟数白跑；而白跑**不是起不来、是跑进一半崩**——
#   `[47184]` 跑了 4928 行才死、`[21044]` 跑 1017 行才死、`[43316]` 进 1 行就死。
#   最后一趟 `[43316] 23:25:34` 进、`[45163] 23:33:21` 才重进 —— **中间 8 分钟是人肉
#   发现崩溃再手敲一次的时间**。判成功与重跑本可以交给脚本，那 8 分钟就是白等的。
#
# 判「这趟成没成」的尺子（与 README §7 同一条，**三条齐了才算**）：
#   build_log.txt 里、**水位之后**新增的 `SCRIPT_ENTERED` + `EXPORT obj ok=true` + `DONE`。
#   ★ 水位在**起之前**取（`$off`）——否则上一趟留下的 DONE 会冒充这一趟的（铁律 194：
#     同一个量有两个估计器时，必须按身份分开，不能按值）。
#   ★ 「崩了」与「没量到」要分开印（铁律 199）：正常退出但没等到 DONE ⇒ `died-mid-run`；
#     连 SCRIPT_ENTERED 都没有 ⇒ `died-before-enter`（那多半是单实例静默接手）；两者都不许
#     印成「跑完了」。
#
# 用法（单行，直接粘；默认最多 3 趟、每趟最多等 600 s）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\项目\cdut3d\rebuild\06_su\_run_su_step2.ps1"
#   … 想单趟跑（老行为）：  -MaxAttempts 1

param(
    [int]$MaxAttempts = 3,
    [int]$TimeoutSec  = 600,
    # ★ 2026-10-17：-Dir 指定**产物目录**（contours/build_log/出件），默认 = 本脚本所在目录（c006 行为一字不动）
    [string]$Dir = '',
    # ★ -Name 指定出件前缀（su_step2_build.rb 读 CDUT_OUT_NAME），默认 c006
    [string]$Name = 'c006'
)

$ErrorActionPreference = 'Stop'

$dir = if ($Dir) { $Dir } else { $PSScriptRoot }        # …\rebuild\06_su 或 …\rebuild\c005\06_su
if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
$env:CDUT_SU_DIR   = $dir
$env:CDUT_OUT_NAME = $Name
# ★ 2026-10-17：真正传到 Ruby 的是**这份文件**（UTF-8 两行：产物目录 / 名前缀）。
#   环境变量只留给本脚本自己看 —— Ruby 侧 ENV 在中文路径上会按 GBK 解，实测先崩编码、再变乱码。
$target = Join-Path $PSScriptRoot '_su_target.txt'
[System.IO.File]::WriteAllText($target, ($dir + "`n" + $Name + "`n"),
    (New-Object System.Text.UTF8Encoding($false)))
$exe = 'C:\Program Files\SketchUp\SketchUp 2023\SketchUp.exe'
# ★ 2026-10-16 修：原来这里写的是 'c006_su.skp' —— 那是**上一趟的输出件**（7.40 MB）。
#   两处不对：① 它自己的 Ruby 头（`su_step2_build.rb` 第 6~7 行）写的跑法就是拿
#   `c006_su_1f.skp`（664,305 B）起；② `EXPORT.md:498` 记的最后那趟成功，处置之一正是
#   「换 664 KB 的小文档启动」。拿 7.4 MB 正式件起 = 每次启动先吞整个成品，与记的做法相反。
#   ★ 输出**不受影响**：存到哪写在 `su_step2_build.rb:147` 里（`#{DIR}/c006_su.skp`），
#     与起始文档是哪个无关。
$skp = Join-Path $dir ($Name + '_su_1f.skp')             # 必须给一个「已存在的文档」，否则欢迎屏挡启动
if (-not (Test-Path -LiteralPath $skp)) {
    # ★ 2026-10-17：本楼没有种子件时，拿仓里已有的 c006 小文档起（Ruby 第一件事是清空全部实体，
    #   所以种子文档是哪个楼**不影响产物**，只影响「有没有一个文档可挂」）。
    $skp = Join-Path $PSScriptRoot 'c006_su_1f.skp'
}
$rb  = Join-Path $PSScriptRoot 'su_step2_build.rb'      # 脚本永远在本文件旁边，不随 -Dir 走
$log = Join-Path $dir 'build_log.txt'
$arc = Join-Path $dir '_archive'

# ★★ 2026-10-17（本机实测，两趟对照）：
#    SU 2023 在「**非 ASCII 文档路径** + `-RubyStartup`」下**必崩**（rc=-3 / 0xC0000374 堆损坏）；
#    同一份 Ruby、同一个开关，文档换到纯 ASCII 路径就正常跑进。
#    probe8: C:\sutest\seed.skp + _su_min.rb  ⇒ MIN ALIVE，_su_min_out.txt 有 RUBY_ENTERED
#    probe9: D:\项目\cdut3d\_scratch\seed_cn.skp + 同一份 Ruby ⇒ EXITED ruby=False rc=-3
#    ⇒ 起 SU 时用的**文档路径与脚本路径**都搬到 ASCII 暂存区再给；
#      **产物目录仍是 $dir**（Ruby 按 `_su_target.txt` 里的绝对路径写，中文没问题）。
#    ★ 暂存表必须跟脚本放一起 —— Ruby 是按 `__FILE__` 旁边找 `_su_target.txt` 的
#      （su_step2_build.rb:42-43）。只搬 .rb 不搬表 ⇒ 它会退回写死的 c006 目录。
$stage = 'C:\sutest\stage'
$stageSkp = Join-Path $stage 'seed.skp'
$stageRb  = Join-Path $stage 'su_step2_build.rb'

foreach ($p in @($exe, $skp, $rb)) {
    if (-not (Test-Path -LiteralPath $p)) {
        Write-Output ('MISSING ' + $p)
        exit 4
    }
}

# 只读「水位之后」的新字节 —— 每 5 s 重读整份 2 MB 日志太亏，改成按字节偏移续读
function Read-NewText {
    param([string]$Path, [ref]$Offset)
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open,
                                 [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $fs.Seek($Offset.Value, [System.IO.SeekOrigin]::Begin) | Out-Null
        $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
        $txt = $sr.ReadToEnd()
        $Offset.Value = $fs.Position
        $sr.Dispose()
    } finally { $fs.Dispose() }
    return $txt
}

# 上一趟崩掉留下的 .skb：SU 会拿它当恢复件、于是接着崩。起跑前一律挪进 _archive/（不删）
# ★ 2026-10-17：**种子文档所在的目录也要清** —— 用 -Dir 指到别的楼时，SU 的恢复件
#   （.skb）躺在种子 .skp 旁边（rebuild/06_su/），只清产物目录会让 SU 一起动就弹
#   「恢复上一个文档」对话框，Ruby 一行不跑（实测 `died-before-enter`）。
foreach ($sd in @($dir, (Split-Path -Parent $skp), $stage) | Select-Object -Unique) {
    foreach ($stale in @(Get-ChildItem -LiteralPath $sd -Filter '*.skb' -ErrorAction SilentlyContinue)) {
        if (-not (Test-Path -LiteralPath $arc)) { New-Item -ItemType Directory -Path $arc | Out-Null }
        $dst = Join-Path $arc ($stale.Name + '.stale-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        Move-Item -LiteralPath $stale.FullName -Destination $dst -Force
        Write-Output ('MOVED_STALE_SKB ' + $stale.FullName)
    }
}

$verdict  = 'no-attempt'
$attempts = 0

for ($k = 1; $k -le $MaxAttempts; $k++) {
    $attempts = $k

    # ── 起之前：杀净 SU 并**无条件等 >=5 s**（SU 是单实例：新实例会把参数交给旧实例、
    #    然后自己退出 —— 脚本一行不跑、零报错，与「跑得好好的」同形）
    $killed = 0
    # ★ 2026-10-17：连 `sketchup_webhelper` 一起杀 —— 老写法只按名字 'SketchUp'，
    #   实测主进程退出后 webhelper 仍在，下一次启动会在 10 s 内自行退出（`died-before-enter`）。
    foreach ($pr in @(Get-Process -ErrorAction SilentlyContinue |
                      Where-Object { $_.ProcessName -like '*sketchup*' })) {
        try { $pr.Kill(); $killed++ } catch { }
    }
    Start-Sleep -Seconds 5

    # 每趟都重新铺一次（复制失败就大声失败，不许带着旧种子起）
    if (-not (Test-Path -LiteralPath $stage)) { New-Item -ItemType Directory -Path $stage | Out-Null }
    Copy-Item -LiteralPath $skp -Destination $stageSkp -Force
    Copy-Item -LiteralPath $rb  -Destination $stageRb  -Force
    [System.IO.File]::WriteAllText((Join-Path $stage '_su_target.txt'),
        ($dir + "`n" + $Name + "`n"), (New-Object System.Text.UTF8Encoding($false)))

    $off = 0
    if (Test-Path -LiteralPath $log) { $off = (Get-Item -LiteralPath $log).Length }
    $wf = [int64]$off
    $ref = [ref]$wf

    $proc = Start-Process -FilePath $exe -ArgumentList @($stageSkp, '-RubyStartup', $stageRb) -PassThru
    Write-Output ('ATTEMPT k=' + $k + ' pid=' + $proc.Id + ' killed=' + $killed +
                  ' at=' + (Get-Date -Format 'HH:mm:ss') + ' watermark=' + $off)

    $acc   = ''
    $t0    = Get-Date
    $verdict = 'timeout'
    while ($true) {
        Start-Sleep -Seconds 5
        $acc += (Read-NewText -Path $log -Offset $ref)

        $hasIn     = $acc -match 'SCRIPT_ENTERED'
        $hasExport = $acc -match 'EXPORT obj ok=true'
        $hasDone   = $acc -match '(?m)^\[\d+\] DONE'
        if ($hasIn -and $hasExport -and $hasDone) { $verdict = 'done'; break }

        $alive = $null -ne (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)
        # ★ 2026-10-17：SU 冷启动要十几秒（还要开种子文档）。10 s 内进程消失就判死**太早**
        #   —— 上一版把「启动器进程退场、真正的 SU 交给单实例」误判成 died-before-enter。
        #   给 30 s 宽限：宽限内只等 SCRIPT_ENTERED，不判死。
        if (-not $alive -and ((Get-Date) - $t0).TotalSeconds -lt 30) { continue }
        if (-not $alive) {
            # ★ 崩了 / 没进去 / 没量到，三种分开印 —— 不许合成一个「没成」
            $verdict = if ($hasIn -and $hasExport) { 'exited-before-done' }
                       elseif ($hasIn)              { 'died-mid-run' }
                       else                         { 'died-before-enter' }
            break
        }
        if (((Get-Date) - $t0).TotalSeconds -gt $TimeoutSec) {
            $verdict = 'timeout-killed'
            try { $proc.Kill() } catch { }
            break
        }
    }

    $faces = ''
    if ($acc -match '(?m)^\[(\d+)\] FACES built=(\d+) fail=(\d+)') { $faces = $Matches[2] + '/fail=' + $Matches[3] }
    $bytes = ''
    if ($acc -match 'EXPORT obj ok=true bytes=(\d+)') { $bytes = $Matches[1] }
    Write-Output ('  -> ' + $verdict + ' pid=' + $proc.Id + ' faces=' + $faces + ' obj_bytes=' + $bytes +
                  ' elapsed=' + [int]((Get-Date) - $t0).TotalSeconds + 's')
    if ($verdict -eq 'done') { break }
}

Write-Output ('RESULT verdict=' + $verdict + ' attempts=' + $attempts + ' max=' + $MaxAttempts)
if ($verdict -eq 'done') { exit 0 }
exit 1
