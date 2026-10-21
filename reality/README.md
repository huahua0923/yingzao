# 实景层发布目录

服务器只读装载本目录。建议结构：

```text
reality/
  tileset.json
  tiles/
    ...
  manifest.json
```

要求：

- `tileset.json` 的 `root.transform` 原样记录。
- `manifest.json` 记录瓦片数、总字节、LOD 范围、坐标基准和控制点残差。
- 本目录不放原始影像、POS、控制点或工程文件。
- 发布时与 `packs/` 使用同一个 release manifest 版本。

