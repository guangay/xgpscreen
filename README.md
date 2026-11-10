# xgpscreen

XGP V3 板载 1.47 寸 SPI 屏（GC9307，320x172 可见区）的自定义渲染器 + LuCI 三页，
从 iStoreOS 22.03 设备上原样抽出的可打包版本。

| 文件 | 作用 |
|---|---|
| `usr/bin/xgpscreen.py` | 渲染守护（2619 行）：采集 → 布局 → Pillow 绘制 → mmap 直写 `/dev/fb0`；`--preview` 离屏出 PNG |
| `usr/bin/xgp-temps` | 温度采集器（thermal/hwmon + 模组 AT），输出 JSON |
| `etc/init.d/xgpscreen` | procd 托管，启动时解绑 fbcon 独占 fb0 |
| `www/.../view/xgpscreen.js` | 「页面设置」：主配置 + 页面/条目编辑（取色器、日历、代码示例） |
| `www/.../view/xgppages.js` | 「页面预览」：离屏缩略图 + 拖拽排序 |
| `controller/xgpmedia.lua` + `model/cbi/xgpmedia.lua` | 媒体库（上传/列表/删除）、preview / mediafile(Range) / reorder 端点 |
| `usr/share/xgpscreen/wqy-microhei.ttc` | 中文字体（渲染必需） |

## 关键机制

- fb 是 320x240，但玻璃只露出 `y∈[36,207]`（320x172），渲染器把 mmap 偏移固定在 `VIS_Y0=36`
- fbtft 是 deferred-io，**只有 mmap 脏页才刷屏**，`write()` 不触发
- 布局与渲染共用 `item_render_h` 测高，超出 124px 预算自动切子帧轮播
- 媒体：ffmpeg 优先 `*_rkmpp` 硬解，`hwdownload,format=nv12` 必须在 transpose 之前
- 5G 数据走 `ubus call at-daemon sendat` 仲裁，避免和 qmodem 抢 ttyUSB2

## 依赖

```
CONFIG_PACKAGE_python3=y
CONFIG_PACKAGE_python3-pillow=y
CONFIG_PACKAGE_kmod-fb-tft=y
CONFIG_PACKAGE_ffmpeg=y
```

屏幕驱动 `kmod-fb-tft-gc9307` 由 `xgp-v3-screen` 包提供；本包与 LVGL 版
`xgp-v3-screen` **互斥**，同时启用会抢 fb0。

## feed 接入

```
src-git xgpscreen https://github.com/guangay/xgpscreen.git;main
```

## 已知问题（保留原样，未修）

1. `page_code` 的 Python 代码页不是沙箱：`exec` 跑在 root、主线程，`sys.settrace` 的 10s 保护可被代码里 `sys.settrace(None)` 绕过
2. `page_video` 写屏循环没有 try/finally，异常时 ffmpeg 子进程可能残留
3. 视频预览最坏 3 档解码器 × 2 次 seek × 25s 超时，单页可能卡 150s
4. `read_cfg_main()`/`main()` 未对 rotate 归一化，手改 uci 成非 90 倍数会让写屏抛异常