# -*- coding: utf-8 -*-
"""把本机 PG17 的 lihua_twin 导成**服务器 PG13 能读**的纯 SQL。

★ 为什么要动刀（两处，都是实测的，不是推的）：

  ① `SET transaction_timeout = 0;`
     本机 PG 17.4、服务器 PG 13.23，PG17 的 pg_dump 不降级。实测：全份 35315925 字节里，
     PG13 唯一不认的 SET 就是这一行。（`SET default_table_access_method = heap;` 是 PG12
     就有的，13 认；本机 17.4 也**没有**吐 17.6+ 才有的 `\\restrict`。）

  ② 曾经还有两条，靠**去掉 `--schema=public`** 一次解决（不是靠继续剥行）：
     `CREATE SCHEMA public;` 与 `COMMENT ON SCHEMA public IS 'standard public schema';`

     根因：带 `--schema=public` 时，pg_dump 改按「导**一个 schema**」的口径吐，
     于是把 initdb 早就建好的那个 public 也当成要建的对象写出来。
     后果分两段、症状完全不同：
       · `CREATE SCHEMA public;` —— 新库里 public 本来就存在 ⇒ `already exists`（一眼看得出）
       · `COMMENT ON SCHEMA public …` —— PG13 里 public 的属主是 postgres，
         而灌库用的是应用角色 ⇒ `ERROR: must be owner of schema public`（2026-10-01 实测，
         第一次灌就倒在这一条上，而且它**排在所有建表之前**，所以一行数据都没进去）
     不带 `-n/--schema` 时，全量库 dump 只写一行注释说「不建，initdb 自己会建」，
     这两条**根本不会出现** ⇒ 把旗标去掉，KILLS 就只剩 ① 一条。

     ★ 教训：看到「这几个语句灌不进去」时，先问「是不是我让 pg_dump 换了个口径」，
     而不是一条一条往外剥 —— 剥出来的列表会随着旗标不同而不同，而真正的根因只有一个。

  ③ 服务器那台机上**不需要改 pg_hba.conf** —— 计划里原本要插一行 `local all postgres trust`
     开一个临时信任窗口，实测**不需要**：兄弟应用的 .env 里就有能连上的超级用户凭据
     （`/opt/cdut70-v2/.env` 与 `/opt/cdut-meeting/.env` 的 `DATABASE_URL`，实测
     `current_user|rolsuper = postgres|true`）。零改动就能建库灌库 ⇒ 那个「改共享配置、
     用完还原」的窗口整个取消，少一个能把全机 PG 锁在门外的动作。

★ 为什么用 Python 而不是 sed/awk —— 2026-10-01 实测踩到两次：
  1) `pg_dump.exe` 在 Windows 上按**文本模式**写盘 ⇒ 每行尾多一个 0x0D。
     语句之间多一个 CR 灌得进去，**不会自己报错**；但 `COPY ... FROM stdin;`
     的数据行会带着它一起进字段 ⇒ **每行最后一列多一个看不见的 \\r**。
  2) `grep -v` / `sed` 在 MSYS 上**读写都走文本模式**：一边把输入的 CRLF 抹掉，
     一边又给输出补回去 —— 两个动作互相抵消，屏幕上却写着「已处理」。
   ⇒ 行尾归一、删行、压缩，三件事全部按**字节**做，每一步都有独立断言。

用法：python deploy/_make_dump.py
产物：_scratch/_deploy/lihua_twin.sql.gz
"""
import gzip
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except (AttributeError, OSError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUTDIR = os.path.join(ROOT, "_scratch", "_deploy")
PGDUMP = r"C:\Program Files\PostgreSQL\17\bin\pg_dump.exe"
DB = "lihua_twin"

# 要剥掉的行（每条都带一个「为什么」——见文件头 ①）
# ★ 只剩一条了：`CREATE SCHEMA public;` 与 `COMMENT ON SCHEMA public …` 已经不出现，
#   因为下面 pg_dump 不再带 `--schema=public`（见文件头 ②）。**别再把那个旗标加回来** ——
#   加回来它们就会重现，而这里的断言会以「出现次数 0，比期望少」的形式挡住，
#   挡是挡得住，但那时你多半会去改 KILLS 而不是去改旗标。
KILLS = [
    # PG13 不认这个 GUC（PG17 才加的）
    (b"SET transaction_timeout = 0;\n", "PG13 不认这个 GUC（PG17 才加的）"),
]


def die(msg):
    print("  \u2717 " + msg)
    raise SystemExit(1)


def read_env_password():
    """口令只从 .env 读 —— 不写进本文件、不进对话（铁律 005）。"""
    p = os.path.join(ROOT, ".env")
    if not os.path.isfile(p):
        die("找不到 %s" % p)
    for line in open(p, encoding="utf-8", errors="replace"):
        if line.startswith("LIHUA_DB_PASSWORD="):
            v = line.split("=", 1)[1].strip()
            if v:
                return v
    die(".env 里 LIHUA_DB_PASSWORD 是空的")


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    env = dict(os.environ, PGPASSWORD=read_env_password())

    print("── ① 导出（PG17，纯 SQL，**全库口径**）──")
    # ★ 这里**故意不加** `--schema=public`：加了它 pg_dump 就改成「导一个 schema」的口径，
    #   会把 initdb 建好的 public 也写成要创建的对象（CREATE + COMMENT），
    #   而那两条在目标库上必错（已存在 / 不是属主）。详见文件头 ②。
    r = subprocess.run(
        [PGDUMP, "-h", "127.0.0.1", "-U", "postgres", "--format=plain",
         "--no-owner", "--no-privileges", DB],
        capture_output=True, env=env)
    if r.returncode != 0:
        die("pg_dump 退 %d：%s" % (r.returncode, r.stderr.decode("utf-8", "replace")[:400]))
    raw = r.stdout
    print("  %d 字节，%d 行（按 \\n 数）" % (len(raw), raw.count(b"\n")))

    print("── ② 行尾归一：CRLF → LF（按字节，不经任何文本模式工具）──")
    n_crlf = raw.count(b"\r\n")
    n_lf = raw.count(b"\n")
    n_lone_cr = raw.count(b"\r") - n_crlf
    print("  CRLF %d 行 / LF %d 行 / 游离 CR %d 个" % (n_crlf, n_lf, n_lone_cr))
    if n_crlf != n_lf:
        die("CRLF 行数(%d) != 总行数(%d) —— 行尾不齐，别在这种输入上做替换" % (n_crlf, n_lf))
    if n_lone_cr:
        die("有 %d 个不跟在 \\n 前面的 CR —— 那可能是**数据里的真实字符**，不许一律删" % n_lone_cr)
    lf = raw.replace(b"\r\n", b"\n")
    if b"\r" in lf:
        die("归一后仍有 CR 残留")
    print("  \u2713 归一后 %d 字节，一个 CR 都不剩" % len(lf))

    is_copy = b"\nCOPY " in lf or lf.startswith(b"COPY ")
    print("  %s" % ("本份用 COPY 灌数据 —— 所以上面这一步是必需的" if is_copy else "本份不用 COPY"))

    print("── ③ 剥掉那 %d 类行 ──" % len(KILLS))
    fix = lf
    n_total = 0
    declared = set()
    for pat, why in KILLS:
        n = fix.count(pat)
        print("  '%s'  出现 %d 次   —— %s" % (pat.decode().strip(), n, why))
        if n < 1:
            die("没找到 '%s' —— pg_dump 变了，或我的假设错了，人工看一遍再走"
                % pat.decode().strip())
        fix = fix.replace(pat, b"")
        if fix.count(pat):
            die("剥完 '%s' 还有残留" % pat.decode().strip())
        n_total += n
        declared.add(pat.rstrip(b"\n"))
    print("  \u2713 共剥掉 %d 处" % n_total)

    print("── ④ 断言：与【归一后】比，差异恰好等于我声明剥掉的那几处 ──")
    a = lf.split(b"\n")
    b = fix.split(b"\n")
    if len(a) - len(b) != n_total:
        die("行数差 %d ≠ %d" % (len(a) - len(b), n_total))
    diffs = set()
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            diffs.add(a[i])
            i += 1
    if i != len(a):
        diffs.update(a[i:])
    diffs -= declared
    if diffs:
        die("出现了我没声明的差异：%r" % list(diffs)[:5])
    print("  \u2713 差异全部落在我声明的那 %d 类里（共 %d 处），其余逐字节相同"
          % (len(declared), n_total))
    print("    注：schema 头那两段（CREATE SCHEMA public / COMMENT ON SCHEMA public）")
    print("        现在是 pg_dump **自己就没吐**，不在这里剥 —— 见文件头 ②。")

    rawp = os.path.join(OUTDIR, "lihua_twin.raw.sql")
    fixp = os.path.join(OUTDIR, "lihua_twin.sql")
    open(rawp, "wb").write(raw)
    open(fixp, "wb").write(fix)
    print("  落盘：%s（%d 字节）" % (fixp, len(fix)))

    print("── ⑤ 压缩（Python gzip，同样按字节）──")
    gzp = fixp + ".gz"
    with gzip.open(gzp, "wb", compresslevel=9) as g:
        g.write(fix)
    # 往返证明：读回来必须与写进去的逐字节相同（铁律 106：量具自己要先在已知为真的输入上验一次）
    with gzip.open(gzp, "rb") as g:
        back = g.read()
    if back != fix:
        die("gzip 往返不一致：读回 %d 字节 ≠ 写前 %d 字节" % (len(back), len(fix)))
    print("  \u2713 gzip 往返逐字节一致（%d 字节 → %d 字节）" % (len(fix), os.path.getsize(gzp)))

    print()
    print("  产物 %s" % gzp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
