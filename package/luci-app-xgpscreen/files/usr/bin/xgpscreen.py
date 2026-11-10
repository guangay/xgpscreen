#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""XGP V3 屏幕自定义渲染守护
整页类型: image 图片 / gif 动画 / video 视频 / code Python 代码页
普通页条目: clock date uptime hostname ip_lan ip_wan cpu_temp load mem disk
            modem custom + netgraph cpugraph signal devices conncount
            docker lunar countdown
"""
import os, sys, re, time, signal, socket, struct, mmap, subprocess, json, shutil, threading
import termios, select
from collections import deque
from datetime import date, datetime

from PIL import Image, ImageDraw, ImageFont, ImageOps

FB = "/dev/fb0"
FONT = "/usr/share/xgpscreen/wqy-microhei.ttc"

# 玻璃可见区（实测标定）：模块玻璃为 172x320（1.47 寸级 IPS），而控制器按 240x320
# 寻址 → fb(320x240) 中 y∈[36,207] 才物理可见（上下各藏 ~35 行，标题栏曾因此永不
# 可见）。x0=0 保证可见区行连续，可整块偏移写 mmap。预览走同一窗口 → 预览=真机。
VIS_X0 = 0
VIS_Y0 = 36
VIS_H = 172

_CHILD_PROCS = []
_RUNNING = True


def _sigterm(_sig, _frm):
    """procd stop 发 SIGTERM：杀掉所有 ffmpeg 子进程后退出（防孤儿进程）"""
    global _RUNNING
    _RUNNING = False
    for p in list(_CHILD_PROCS):
        try:
            p.terminate()
        except Exception:
            pass

ITEM_NAMES = {
    "clock": "时间", "date": "日期", "uptime": "运行时间",
    "hostname": "主机名", "ip_lan": "内网 IP", "ip_wan": "外网 IP",
    "cpu_temp": "CPU 温度", "load": "负载", "mem": "内存", "disk": "存储",
    "modem": "5G 模组", "custom": "自定义", "temps": "温度总览",
    "netgraph": "网速曲线", "lanrate": "LAN 总流量", "topsites": "热门网址", "cpugraph": "CPU 四核", "signal": "网络信号",
    "devices": "在线设备", "conncount": "连接数", "docker": "Docker 容器",
    "lunar": "农历/节日", "countdown": "倒计时",
    "image": "图片", "gif": "GIF 动画", "video": "视频", "code": "代码页",
}

NET_IFACE_CANDIDATES = ("wwan0_1", "wwan0", "wwan1_1", "eth1", "br-lan", "eth0")

# ---------------- 农历（数据表与算法移植自 zhdate，1900-2100） ----------------
CHINESEYEARCODE = [19416, 19168, 42352, 21717, 53856, 55632, 91476, 22176, 39632, 21970, 19168, 42422, 42192, 53840, 119381, 46400, 54944, 44450, 38320, 84343, 18800, 42160, 46261, 27216, 27968, 109396, 11104, 38256, 21234, 18800, 25958, 54432, 59984, 92821, 23248, 11104, 100067, 37600, 116951, 51536, 54432, 120998, 46416, 22176, 107956, 9680, 37584, 53938, 43344, 46423, 27808, 46416, 86869, 19872, 42416, 83315, 21168, 43432, 59728, 27296, 44710, 43856, 19296, 43748, 42352, 21088, 62051, 55632, 23383, 22176, 38608, 19925, 19152, 42192, 54484, 53840, 54616, 46400, 46752, 103846, 38320, 18864, 43380, 42160, 45690, 27216, 27968, 44870, 43872, 38256, 19189, 18800, 25776, 29859, 59984, 27480, 23232, 43872, 38613, 37600, 51552, 55636, 54432, 55888, 30034, 22176, 43959, 9680, 37584, 51893, 43344, 46240, 47780, 44368, 21977, 19360, 42416, 86390, 21168, 43312, 31060, 27296, 44368, 23378, 19296, 42726, 42208, 53856, 60005, 54576, 23200, 30371, 38608, 19195, 19152, 42192, 118966, 53840, 54560, 56645, 46496, 22224, 21938, 18864, 42359, 42160, 43600, 111189, 27936, 44448, 84835, 37744, 18936, 18800, 25776, 92326, 59984, 27296, 108228, 43744, 37600, 53987, 51552, 54615, 54432, 55888, 23893, 22176, 42704, 21972, 21200, 43448, 43344, 46240, 46758, 44368, 21920, 43940, 42416, 21168, 45683, 26928, 29495, 27296, 44368, 84821, 19296, 42352, 21732, 53600, 59752, 54560, 55968, 92838, 22224, 19168, 43476, 41680, 53584, 62034, 54560]
CHINESENEWYEAR = ['19000131', '19010219', '19020208', '19030129', '19040216', '19050204', '19060125', '19070213', '19080202', '19090122', '19100210', '19110130', '19120218', '19130206', '19140126', '19150214', '19160203', '19170123', '19180211', '19190201', '19200220', '19210208', '19220128', '19230216', '19240205', '19250124', '19260213', '19270202', '19280123', '19290210', '19300130', '19310217', '19320206', '19330126', '19340214', '19350204', '19360124', '19370211', '19380131', '19390219', '19400208', '19410127', '19420215', '19430205', '19440125', '19450213', '19460202', '19470122', '19480210', '19490129', '19500217', '19510206', '19520127', '19530214', '19540203', '19550124', '19560212', '19570131', '19580218', '19590208', '19600128', '19610215', '19620205', '19630125', '19640213', '19650202', '19660121', '19670209', '19680130', '19690217', '19700206', '19710127', '19720215', '19730203', '19740123', '19750211', '19760131', '19770218', '19780207', '19790128', '19800216', '19810205', '19820125', '19830213', '19840202', '19850220', '19860209', '19870129', '19880217', '19890206', '19900127', '19910215', '19920204', '19930123', '19940210', '19950131', '19960219', '19970207', '19980128', '19990216', '20000205', '20010124', '20020212', '20030201', '20040122', '20050209', '20060129', '20070218', '20080207', '20090126', '20100214', '20110203', '20120123', '20130210', '20140131', '20150219', '20160208', '20170128', '20180216', '20190205', '20200125', '20210212', '20220201', '20230122', '20240210', '20250129', '20260217', '20270206', '20280126', '20290213', '20300203', '20310123', '20320211', '20330131', '20340219', '20350208', '20360128', '20370215', '20380204', '20390124', '20400212', '20410201', '20420122', '20430210', '20440130', '20450217', '20460206', '20470126', '20480214', '20490202', '20500123', '20510211', '20520201', '20530219', '20540208', '20550128', '20560215', '20570204', '20580124', '20590212', '20600202', '20610121', '20620209', '20630129', '20640217', '20650205', '20660126', '20670214', '20680203', '20690123', '20700211', '20710131', '20720219', '20730207', '20740127', '20750215', '20760205', '20770124', '20780212', '20790202', '20800122', '20810209', '20820129', '20830217', '20840206', '20850126', '20860214', '20870203', '20880124', '20890210', '20900130', '20910218', '20920207', '20930127', '20940215', '20950205', '20960125', '20970212', '20980201', '20990121', '21000209']
CN_MONTH = ("错", "正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊")
CN_DAY = ("初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
          "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
          "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十")
ZODIAC = ("鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪")
LUNAR_FEST = {(1, 1): "春节", (1, 15): "元宵", (5, 5): "端午", (7, 7): "七夕",
              (8, 15): "中秋", (9, 9): "重阳", (12, 8): "腊八"}
SOLAR_FEST = {"0101": "元旦", "0214": "情人节", "0501": "劳动节", "0601": "儿童节",
              "1001": "国庆节", "1225": "圣诞"}


def _year_days(code):
    md = []
    for i in range(4, 16):
        md.insert(0, 30 if (code >> i) & 1 else 29)
    if code & 0xF:
        md.insert(code & 0xF, 30 if code >> 16 else 29)
    return md


def solar_to_lunar(d):
    """公历 date -> (农历年, 月, 是否闰月, 日)"""
    dt = datetime(d.year, d.month, d.day)
    ly = dt.year
    if (datetime.strptime(CHINESENEWYEAR[ly - 1900], "%Y%m%d") - dt).total_seconds() > 0:
        ly -= 1
    newyear = datetime.strptime(CHINESENEWYEAR[ly - 1900], "%Y%m%d")
    days = (dt - newyear).days
    code = CHINESEYEARCODE[ly - 1900]
    md = _year_days(code)
    acc = 0
    month = len(md)
    day = 1
    for pos, mdays in enumerate(md):
        acc += mdays
        if days + 1 <= acc:
            month = pos + 1
            day = md[pos] - (acc - days) + 1
            break
    leap_pos = code & 0xF
    is_leap = False
    if leap_pos == 0 or month <= leap_pos:
        lm = month
    else:
        lm = month - 1
    if leap_pos != 0 and month == leap_pos + 1:
        is_leap = True
    return ly, lm, is_leap, day


def lunar_str(d=None):
    d = d or date.today()
    y, m, leap, day = solar_to_lunar(d)
    zodiac = ZODIAC[(y - 4) % 12]
    name = "农历%s月%s" % (("闰" if leap else "") + CN_MONTH[m], CN_DAY[day - 1])
    fest = LUNAR_FEST.get((m, day)) or SOLAR_FEST.get(d.strftime("%m%d"))
    return "%s %s年%s" % (name, zodiac, "·" + fest if fest else "")


# ---------------- 采集 ----------------

def uci_unescape(raw):
    """还原 uci show 的引号转义：值内每个 ' 被打成 '\''（busybox 恒以
    '…' 包裹输出，反斜杠不转义——设备实测）。先剥首尾引号再替换，
    首尾本身是引号的值（'abc… / …abc'）也正确还原。"""
    if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
        raw = raw[1:-1]
    return raw.replace("'\\''", "'")


def uci_parse_list(raw):
    """逐字符解析 uci show 的 list 值（'A' 'B' 'C'，元素内 ' 以 '\'' 转义）。
    朴素 split("' '") 会被元素内的转义引号劈碎，首尾元素残留边缘引号。"""
    out, i, n = [], 0, len(raw)
    while i < n:
        if raw[i] == "'":
            i += 1
            cur = ""
            while i < n:
                if raw[i] == "'":
                    if raw[i:i + 4] == "'\\''":
                        cur += "'"
                        i += 4
                    else:
                        break
                else:
                    cur += raw[i]
                    i += 1
            out.append(cur)
            i += 1                      # 收尾引号
        else:
            i += 1                      # 元素间空白等
    return out or [""]


def parse_uci_val(val, is_list=False):
    """uci show 输出值：list 选项（仅 items）为单行多引号段 'a' 'b'；
    单值选项（custom_text/code_text 等）绝不按 "' '" 拆——代码里的
    ' '.join(...) 含同样的字符序列，误拆成 list 会让渲染循环崩溃。
    两类都须还原 '\\' 引号转义（曾缺失导致含单引号代码全部损坏）。"""
    if is_list:
        return uci_parse_list(val) if "'" in val else [val]
    return uci_unescape(val)


def uci_get(opt, default=""):
    try:
        v = subprocess.check_output(["uci", "-q", "get", "xgpscreen." + opt],
                                    text=True).strip()
        return v or default
    except Exception:
        return default


def uci_pages(all_pages=False):
    """解析 uci show：两段键=section类型；重复同名键=list 聚合。
    all_pages=True 时含禁用页（LuCI 预览/排序用）。"""
    try:
        out = subprocess.check_output(["uci", "-q", "show", "xgpscreen"], text=True)
    except Exception:
        return []
    sect_types = {}
    pages = {}
    # 跨行值合并：uci show 的多行值（custom_text）以奇数引号开头，吞到引号配对
    lines = []
    buf = ""
    for raw in out.splitlines():
        if buf:
            buf += "\n" + raw
            if buf.count("'") % 2 == 0:
                lines.append(buf)
                buf = ""
        elif raw.count("'") % 2 == 1:
            buf = raw
        else:
            lines.append(raw)
    if buf:
        lines.append(buf)
    for line in lines:
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        parts = key.split(".")
        val = parse_uci_val(val.strip(),
                            is_list=len(parts) == 3 and parts[2] == "items")
        if parts[0] != "xgpscreen":
            continue
        if len(parts) == 2:
            sect_types[parts[1]] = val
            continue
        if len(parts) != 3 or parts[1] == "main":
            continue
        sec, opt = parts[1], parts[2]
        cfg = pages.setdefault(sec, {})
        if opt in cfg:
            if isinstance(cfg[opt], list):
                cfg[opt].extend(val if isinstance(val, list) else [val])
            else:
                cfg[opt] = [cfg[opt]] + (val if isinstance(val, list) else [val])
        else:
            cfg[opt] = val
    result = []
    for sec in sorted(pages):
        cfg = pages[sec]
        if sect_types.get(sec) != "page":
            continue
        if not all_pages and cfg.get("enabled", "1") != "1":
            continue
        items = cfg.get("items", [])
        if isinstance(items, str):
            items = [items]

        def _text(opt):
            """文本选项归一：残留 list（历史坏配置/其它写入路径）拼接防崩溃。"""
            v = cfg.get(opt, "")
            return "\n".join(v) if isinstance(v, list) else (v or "")

        result.append({
            "section": sec,
            "enabled": cfg.get("enabled", "1") == "1",
            "title": cfg.get("title", sec),
            "items": items,
            "custom": _text("custom_text"),
            "image_path": cfg.get("image_path", ""),
            "gif_path": cfg.get("gif_path", ""),
            "video_path": cfg.get("video_path", ""),
            "fit_mode": norm_fit(cfg.get("fit_mode", "cover")),
            "rotate": norm_rotate(cfg.get("rotate", 0)),
            "code_text": _text("code_text"),
            "countdown_label": cfg.get("countdown_label", ""),
            "countdown_date": cfg.get("countdown_date", ""),
        })
    return result


def read_first(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return ""


def ip_of(iface):
    try:
        out = subprocess.check_output(
            ["ubus", "-S", "call", "network.interface.%s" % iface, "status"],
            text=True, timeout=2)
        d = json.loads(out)
        addrs = d.get("ipv4-address") or []
        if addrs:
            return "%s (%s)" % (addrs[0].get("address", "?"),
                                "UP" if d.get("up") else "DOWN")
        return "UP/无地址" if d.get("up") else "DOWN"
    except Exception:
        return "离线"


def wan_ip():
    # 首选默认路由源地址（eth0 WAN / 旁路由 / pppoe 场景通吃，不依赖接口命名）；
    # ubus dump 扫描兜底
    try:
        out = subprocess.check_output(
            ["ip", "route", "get", "223.5.5.5"], text=True, timeout=2)
        m = re.search(r"\bsrc (\d+\.\d+\.\d+\.\d+)\b", out)
        if m and not m.group(1).startswith("127."):
            return m.group(1)
    except Exception:
        pass
    try:
        out = subprocess.check_output(["ubus", "-S", "call", "network.interface.dump", "status"],
                                      text=True, timeout=3)
        for itf in json.loads(out).get("interface", []):
            if itf.get("up") and "wan" in itf.get("interface", "").lower():
                for a in itf.get("ipv4-address", []):
                    return a.get("address", "?")
    except Exception:
        pass
    return "离线"


def modem_model():
    """USB sysfs 扫描模组型号（Quectel=2c7c 等）。"""
    try:
        for d in os.listdir("/sys/bus/usb/devices"):
            base = "/sys/bus/usb/devices/" + d
            try:
                with open(base + "/idVendor") as f:
                    vid = f.read().strip()
            except Exception:
                continue
            if vid == "2c7c":          # Quectel（RM520N-GL 等）
                try:
                    with open(base + "/product") as f:
                        return f.read().strip()
                except Exception:
                    return "Quectel " + vid
    except Exception:
        pass
    return None


def modem_info():
    model = modem_model()
    try:
        links = [l for l in os.listdir("/sys/class/net") if l.startswith("wwan")]
    except Exception:
        links = []
    if model:
        base = model + (" 在线" if links else " 离线")
        s = modem_signal()           # 10s 缓存，附运营商+制式
        if s and links:
            base = model + " " + ((s.get("op") + " ") if s.get("op") else "") + s["tech"]
        return base
    return ("在线 " + ", ".join(links)) if links else "未检测到"


# ---------------- 5G 模组完整信息 ----------------
_MODEM_INFO_CACHE = {"t": 0.0, "fw": None}


def _modem_sysfs():
    """USB sysfs 读 (名称, 制造商)；非 Quectel(2c7c) 返回 (None, None)。"""
    try:
        for dev in os.listdir("/sys/bus/usb/devices"):
            base = "/sys/bus/usb/devices/" + dev
            try:
                with open(base + "/idVendor") as f:
                    if f.read().strip() != "2c7c":
                        continue
                model = read_first(base + "/product")
                maker = read_first(base + "/manufacturer")
                if model or maker:
                    return model or None, maker or None
            except Exception:
                continue
    except Exception:
        pass
    return None, None


def _modem_fw():
    """固件版本（AT+CGMR）：成功永久缓存（固件运行期不变），失败 120s 退避
    ——不缓存失败结果，避免 AT 口忙时每帧重试。"""
    if _MODEM_INFO_CACHE["fw"] is not None:
        return _MODEM_INFO_CACHE["fw"]
    if time.time() - _MODEM_INFO_CACHE["t"] < 120:
        return None
    _MODEM_INFO_CACHE["t"] = time.time()
    try:
        txt = at_cmd(["AT+CGMR"])
    except Exception:
        txt = None
    if txt:
        for line in txt.splitlines():
            s = line.strip().rstrip("\r")
            # 跳过命令回显/OK/ERROR/CME 报错，取首个足够长的版本串
            if s and not s.upper().startswith("AT+") and s not in ("OK", "ERROR") \
                    and not s.startswith("+CME") and len(s) >= 6:
                _MODEM_INFO_CACHE["fw"] = s
                return s
    return None


def _modem_at_port():
    """AT 端口：uci qmodem 回写值 > 运行期已验证口 > 默认 2/3 中实际存在者。"""
    for p in _at_ports():
        if os.path.exists(p):
            return p
    return None


def modem_full():
    """模组完整信息 dict（名称/制造商/版本/AT端口/信号）。"""
    model, maker = _modem_sysfs()
    return {"model": model, "maker": maker, "fw": _modem_fw(),
            "at": _modem_at_port(), "sig": modem_signal()}


def uptime_str():
    try:
        s = int(float(read_first("/proc/uptime").split()[0]))
        d, s = divmod(s, 86400)
        h, s = divmod(s, 3600)
        m, _ = divmod(s, 60)
        return "%d天%02d时%02d分" % (d, h, m)
    except Exception:
        return "N/A"


def mem_str():
    try:
        info = {}
        for l in read_first("/proc/meminfo").splitlines():
            if l.startswith(("MemTotal", "MemAvailable")):
                info[l.split(":")[0]] = int(l.split()[1])
        total = info.get("MemTotal", 0)
        used = total - info.get("MemAvailable", 0)
        return "%dM / %dM (%d%%)" % (used // 1024, total // 1024,
                                     used * 100 // max(total, 1))
    except Exception:
        return "N/A"


def disk_str():
    # 聚合本机主要可写分区（overlay 配置 / 媒体库 / docker），全盘视角而非仅 overlay
    # （overlay 仅约 2G，媒体库与 docker 分区占大头；挂载点不存在自动跳过）
    used = total = 0.0
    n = 0
    for mntp in ("/overlay", "/mnt/mmc", "/mnt/docker"):
        try:
            st = os.statvfs(mntp)
        except Exception:
            continue
        t = st.f_blocks * st.f_frsize / 1e9
        if t <= 0:
            continue
        used += t - st.f_bfree * st.f_frsize / 1e9
        total += t
        n += 1
    if not n:
        return "--"
    return "已用 %.1fG / %.1fG" % (used, total)


def cpu_temp():
    t = read_first("/sys/class/thermal/thermal_zone0/temp")
    try:
        return "%.1f °C" % (int(t) / 1000.0)
    except Exception:
        return "N/A"


def bar_color(ratio, fg):
    """进度条阈值配色（与连接数/CPU 柱同一档：60%/85% 变黄变红）。"""
    if ratio >= 0.85:
        return (255, 80, 80)
    if ratio >= 0.6:
        return (255, 180, 0)
    return fg


def temp_color(t, fg):
    """温度阈值配色（°C）：>75 红 / >60 黄，与 bar_color 同一语义色档。"""
    if t > 75:
        return (255, 80, 80)
    if t > 60:
        return (255, 180, 0)
    return fg


def bar_ratio(item, val):
    """可量化条目的进度比例；无可视化意义返回 None（保持纯文本行）。"""
    try:
        if item == "mem":
            m = re.search(r"\((\d+)%\)", val)
            return int(m.group(1)) / 100 if m else None
        if item == "disk":
            m = re.match(r"已用 ([\d.]+)G / ([\d.]+)G", val)
            if m and float(m.group(2)) > 0:
                return max(0.0, min(1.0, float(m.group(1)) / float(m.group(2))))
            return None
        if item == "cpu_temp":
            return max(0.0, min(1.0, float(val.split()[0]) / 85))
        if item == "load":
            return max(0.0, min(1.0, float(val.split()[0]) / 4))
    except Exception:
        pass
    return None



def collect(item):
    if item == "clock":
        return time.strftime("%H:%M:%S")
    if item == "date":
        return time.strftime("%Y-%m-%d ") + "周" + "一二三四五六日"[date.today().weekday()]
    if item == "uptime":
        return uptime_str()
    if item == "hostname":
        return read_first("/proc/sys/kernel/hostname") or "?"
    if item == "ip_lan":
        return ip_of("lan")
    if item == "ip_wan":
        return wan_ip()
    if item == "cpu_temp":
        return cpu_temp()
    if item == "load":
        l = read_first("/proc/loadavg").split()[:3]
        return " ".join(l) if l else "N/A"
    if item == "mem":
        return mem_str()
    if item == "disk":
        return disk_str()
    if item == "modem":
        return modem_info()
    if item == "lunar":
        return lunar_str()
    return None


# ---------------- 网速采样线程 ----------------
def read_netdev(path="/proc/net/dev"):
    stats = {}
    try:
        with open(path) as f:
            for line in f.read().splitlines()[2:]:
                if ":" not in line:
                    continue
                name, _, rest = line.partition(":")
                fields = rest.split()
                stats[name.strip()] = (int(fields[0]), int(fields[8]))  # rx,tx
    except Exception:
        pass
    return stats


class NetMon(threading.Thread):
    """后台每秒采样，维护环形历史，供网速曲线/速率查询。"""
    HIST = 60

    def __init__(self, path="/proc/net/dev", fixed=None):
        super().__init__(daemon=True)
        self.path = path
        self.fixed = fixed                 # 固定接口（如 LAN 口 br-lan），不参与自动挑选
        self.iface = None
        self.hist = deque(maxlen=self.HIST)   # (ts, rx, tx)
        self.prev = None
        self.rates = (0.0, 0.0)               # (rx_B/s, tx_B/s)
        self._lock = threading.Lock()

    def _pick_iface(self, stats):
        want = uci_get("main.net_iface", "")
        cands = ([want] if want else []) + [i for i in NET_IFACE_CANDIDATES if i != want]
        for c in cands:
            if c in stats:
                return c
        for c in stats:
            if c != "lo":
                return c
        return None

    def sample(self):
        stats = read_netdev(self.path)
        if not stats:
            return
        if self.fixed:
            iface = self.fixed if self.fixed in stats else None
        else:
            iface = self.iface if self.iface in stats else self._pick_iface(stats)
        if not iface or iface not in stats:
            return
        self.iface = iface
        now, rx, tx = time.time(), *stats[iface]
        with self._lock:
            if self.prev:
                dt = max(0.2, now - self.prev[0])
                # 计数器回绕/重置（负增量，如模组重拨后清零）按 0 计，避免瞬时大负速率
                self.rates = (max(0, rx - self.prev[1]) / dt,
                              max(0, tx - self.prev[2]) / dt)
            self.prev = (now, rx, tx)
            self.hist.append((now, rx, tx))

    def run(self):
        while True:
            self.sample()
            time.sleep(1)

    def snapshot(self):
        with self._lock:
            return self.iface, list(self.hist), self.rates


NETMON = None
NETMON_LAN = None


def fmt_rate(bps):
    if bps >= 1048576:
        return "%.1f MB/s" % (bps / 1048576)
    if bps >= 1024:
        return "%.0f KB/s" % (bps / 1024)
    return "%.0f B/s" % bps


# ---------------- CPU 每核 ----------------
def read_cpu_per_core(path="/proc/stat"):
    cores = []
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("cpu") and line[3].isdigit():
                    parts = [int(x) for x in line.split()[1:]]
                    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
                    total = sum(parts)
                    cores.append((idle, total))
    except Exception:
        pass
    return cores


_CPU_PREV = None


def cpu_percents(cores):
    """相邻两次采样差分 -> 每核占用%列表"""
    global _CPU_PREV
    if _CPU_PREV is None or len(_CPU_PREV) != len(cores):
        _CPU_PREV = cores
        return None
    out = []
    for (i0, t0), (i1, t1) in zip(_CPU_PREV, cores):
        di, dt = i1 - i0, t1 - t0
        out.append(max(0, min(100, int(100 * (dt - di) / dt))) if dt > 0 else 0)
    _CPU_PREV = cores
    return out


# ---------------- 5G 信号 ----------------
_AT_PORT = None


def _at_ports():
    # RM520N-GL 仅 ttyUSB2/3 为 AT 口（0=diag、1=NMEA 永远无响应）。
    # 探测死口会在 daemon 忙时叠加排队超时，拖慢全局恢复，故不列入。
    # BG81: 对齐三层口径——首选 uci qmodem.6_1.at_port（modem_scand 在 USB
    # 重枚举漂移如 2/3→4/5 时会自动回写），其次运行期已验证口，兜底仍 2/3；
    # 4/5 及更高位因此被覆盖，与 SA fallback/modem_scand 口径一致。
    ports = []
    try:
        r = subprocess.run(["uci", "-q", "get", "qmodem.6_1.at_port"],
                           capture_output=True, timeout=3)
        p = r.stdout.decode().strip() if r.returncode == 0 else ""
        if p:
            ports.append(p)
    except Exception:
        pass
    if _AT_PORT and _AT_PORT not in ports:
        ports.append(_AT_PORT)
    for p in ("/dev/ttyUSB3", "/dev/ttyUSB2"):
        if p not in ports:
            ports.append(p)
    return ports


def at_cmd_daemon(cmds):
    """优先走 at-daemon 仲裁（ubus sendat），与 qmodem/SimpleAdmin 共享串行队列。
    直开 AT 口会与 daemon 的 reader 抢读同一设备，双方响应随机被对方截走
    → daemon 命令超时、面板全链路失败（真机实测口竞争，ttyUSB2 间歇失效）。
    daemon 不可用时由调用方回退直开。返回响应文本或 None。"""
    try:
        import subprocess
        import json as _json
    except Exception:
        return None
    global _AT_PORT
    for port in _at_ports():
        out = []
        try:
            r = subprocess.run(
                ["ubus", "-t", "8", "call", "at-daemon", "sendat",
                 _json.dumps({"at_port": port, "at_cmd": cmds[0], "timeout": 5})],
                capture_output=True, timeout=11)
            if r.returncode != 0:
                continue
            d = _json.loads(r.stdout.decode("utf-8", "replace"))
            if d.get("status") != "success":
                continue
            _AT_PORT = port
            out.append(d.get("response", ""))
            for c in cmds[1:]:
                r = subprocess.run(
                    ["ubus", "-t", "8", "call", "at-daemon", "sendat",
                     _json.dumps({"at_port": port, "at_cmd": c, "timeout": 5})],
                    capture_output=True, timeout=11)
                if r.returncode != 0:
                    continue
                d = _json.loads(r.stdout.decode("utf-8", "replace"))
                if d.get("status") == "success":
                    out.append(d.get("response", ""))
            return "\n".join(out)
        except Exception:
            continue
    return None


def at_cmd(cmds, per_wait=1.2):
    """对模组 AT 口执行命令返回响应文本；找不到可用 AT 口返回 None。
    MBIM 模组（RM520N-GL 等）uqmi 报 "Failed to connect to service"，AT 口是通解。"""
    txt = at_cmd_daemon(cmds)
    if txt is not None:
        return txt
    global _AT_PORT
    for port in _at_ports():
        try:
            fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            a = list(termios.tcgetattr(fd))
            a[0] = a[1] = a[3] = 0
            a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            sp = termios.B115200
            a[4] = a[5] = sp[0] if isinstance(sp, list) else sp
            termios.tcsetattr(fd, termios.TCSANOW, a)
            os.write(fd, b"AT\r")
            time.sleep(0.15)
            out = b""
            r, _, _ = select.select([fd], [], [], 0.3)
            if r:
                out += os.read(fd, 256)
            if b"OK" not in out:
                continue
            _AT_PORT = port
            for c in cmds:
                os.write(fd, c.encode() + b"\r")
                t0 = time.time()
                while time.time() - t0 < per_wait:
                    r, _, _ = select.select([fd], [], [], 0.3)
                    if r:
                        out += os.read(fd, 2048)
            return out.decode("utf-8", "replace")
        except Exception:
            continue
        finally:
            try:
                os.close(fd)
            except Exception:
                pass
    return None


def _sig_find(nums):
    """QENG/QCSQ 数值序列里按取值域定位 (rsrp, rsrq, sinr) 连续三元组。"""
    for i in range(len(nums) - 2):
        a, b, c = nums[i], nums[i + 1], nums[i + 2]
        if -140 <= a <= -44 and -23 <= b <= 0 and -10 <= c <= 60:
            return a, b, c
    return None


def _sig_find_lte(nums):
    """LTE QENG 行布局为 (rsrp, rsrq, rssi, sinr) 四连值（与 NR 行不同，
    sinr 前多一个 rssi），按取值域定位并跳过 rssi。"""
    for i in range(len(nums) - 3):
        a, b, c, dd = nums[i:i + 4]
        if (-140 <= a <= -44 and -23 <= b <= 0
                and -120 <= c <= -30 and -10 <= dd <= 60):
            return a, b, dd
    return None


OPERATORS = {"46000": "移动", "46002": "移动", "46004": "移动", "46007": "移动",
             "46008": "移动", "46001": "联通", "46006": "联通", "46009": "联通",
             "46003": "电信", "46005": "电信", "46011": "电信", "46015": "广电",
             "46016": "广电"}


_SIG_CACHE = {"t": 0.0, "v": None}

_TEMPS_CACHE = {"t": 0.0, "v": None}


def temps_info():
    """温度总览数据（CPU/GPU/模组/网卡）：共享 /usr/bin/xgp-temps 采集器，
    与网页概览卡片同一份兼容逻辑（thermal zone/hwmon 双路径、AT 多格式、
    模组 15s 缓存）。本函数再缓存 15s：走秒重绘不允许反复 fork 采集器。"""
    if time.time() - _TEMPS_CACHE["t"] < 15:
        return _TEMPS_CACHE["v"]
    v = None
    try:
        r = subprocess.run(["/usr/bin/xgp-temps"], capture_output=True, timeout=25)
        if r.returncode == 0:
            v = json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        v = None
    _TEMPS_CACHE["t"] = time.time()
    _TEMPS_CACHE["v"] = v
    return v


def modem_signal():
    """AT 口优先（QENG 主 + QCSQ 兜底，含运营商），uqmi 最后兜底（QMI 模组）。
    结果缓存 10s：走秒重绘会每秒调用，AT 一次 1-4s 不能裸打。"""
    if time.time() - _SIG_CACHE["t"] < 10:
        return _SIG_CACHE["v"]
    v = _modem_signal_uncached()
    _SIG_CACHE["t"] = time.time()
    _SIG_CACHE["v"] = v
    return v


def _modem_signal_uncached():
    """AT 口优先（QENG 主 + QCSQ 兜底，含运营商），uqmi 最后兜底（QMI 模组）。"""
    try:
        txt = at_cmd(['AT+QENG="servingcell"', "AT+COPS?", "AT+QCSQ"])
    except Exception:
        txt = None
    if txt and "+QENG:" in txt:
        # 只取 QENG 自身响应段（此前误把 COPS/QCSQ 段并入 tech 判定）
        seg = txt.split("+QENG:", 1)[1].split("OK")[0]
        op = None
        m = re.search(r'\+COPS:\s*\d+,\d+,"(\d+)"', txt)
        if m:
            op = OPERATORS.get(m.group(1))
        # NSA 时响应含 LTE 锚定 + NR5G-NSA 两行：驻留 5G 取 NR 行，纯 4G 取 LTE 行
        lines = ["+QENG:" + x for x in ("+QENG:" + seg).split("+QENG:")[1:]]
        # 先剥掉引号内含字母的 token（servingcell/NR5G-SA/LTE…），
        # "NR5G" 里的 5 不进数值序列（hex cellid 不在引号内，保留由域值过滤）
        trip = tech = None
        for line in lines:
            if "NR5G" not in line:
                continue
            clean = re.sub(r'"[^"]*[A-Za-z][^"]*"', "", line)
            trip = _sig_find([int(x) for x in re.findall(r"-?\d+", clean)])
            if trip:
                tech = "NR5G"
                break
        if not trip:
            for line in lines:
                if '"LTE"' not in line:
                    continue
                clean = re.sub(r'"[^"]*[A-Za-z][^"]*"', "", line)
                trip = _sig_find_lte(
                    [int(x) for x in re.findall(r"-?\d+", clean)])
                if trip:
                    tech = "LTE"
                    break
        if not trip:
            # WCDMA servingcell：分列取值（CI/LAC 是 hex 可能含字母，
            # 不能走数值序列）：mcc,mnc,lac,ci,uarfcn,psc,rac,rscp,ecio,...
            for line in lines:
                if '"WCDMA"' not in line:
                    continue
                cols = [c.strip().strip('"') for c in line.split(',')]
                if len(cols) < 12:
                    continue
                try:
                    rscp, ecio = int(cols[10]), int(cols[11])
                except ValueError:
                    continue
                if -120 <= rscp <= -25 and -30 <= ecio <= 0:
                    trip = (rscp, ecio, None)
                    tech = "WCDMA"
                    break
        if trip and tech:
            return {"tech": tech, "op": op,
                    "rsrp": trip[0], "rsrq": trip[1], "sinr": trip[2]}
    if txt and "+QCSQ:" in txt:
        seg = txt.split("+QCSQ:", 1)[1].split("OK")[0]
        rat = re.search(r'"(\w+)"', seg)
        # 数字从 RAT 名之后提取："NR5G" 里的 5 不能混进数值序列
        tail = seg[rat.end():] if rat else seg
        nums = [int(x) for x in re.findall(r"-?\d+", tail)]
        op = None
        m = re.search(r'\+COPS:\s*\d+,\d+,"(\d+)"', txt)
        if m:
            op = OPERATORS.get(m.group(1))
        # 本固件实测（无 bandwidth 字段）：LTE="LTE",rssi,rsrp,sinr,rsrq；
        # NR5G="NR5G",rsrp,sinr,rsrq（首值与 QENG rsrp 一致）。
        # 带 rsrq_backup 的 5 字段 LTE 形式按同位置解析（末位多余忽略）。
        # 取值域不符时不返回，落到 uqmi 兜底，绝不输出垃圾值。
        if rat and nums:
            rat_name = {"NNSA": "NR5G"}.get(rat.group(1), rat.group(1))
            if rat_name == "WCDMA" and len(nums) >= 3:
                rscp, ecio = nums[1], nums[2]
                if -120 <= rscp <= -25:
                    return {"tech": "WCDMA", "op": op,
                            "rsrp": rscp, "rsrq": ecio, "sinr": None}
            if rat_name == "LTE" and len(nums) >= 4:
                rsrp, sinr, rsrq = nums[1], nums[2], nums[3]
                if -140 <= rsrp <= -44:
                    return {"tech": rat_name, "op": op,
                            "rsrp": rsrp, "rsrq": rsrq, "sinr": sinr}
            if rat_name == "NR5G" and len(nums) >= 3 and -140 <= nums[0] <= -44:
                return {"tech": rat_name, "op": op,
                        "rsrp": nums[0], "rsrq": nums[2], "sinr": nums[1]}
    try:
        out = subprocess.check_output(
            ["uqmi", "-d", "/dev/cdc-wdm0", "--get-signal-info"],
            text=True, timeout=4)
        d = json.loads(out)
    except Exception:
        return None
    for tech in ("nr5g", "lte"):
        if tech in d and isinstance(d[tech], dict):
            s = d[tech]
            try:
                rsrp = int(s.get("rsrp"))
            except (TypeError, ValueError):
                continue
            if not -140 <= rsrp <= -44:
                continue
            return {"tech": "NR5G" if tech == "nr5g" else "LTE", "op": None,
                    "rsrp": rsrp, "rsrq": s.get("rsrq"),
                    "sinr": s.get("sinr")}
    # uqmi 的 --get-signal-info wcdma 段只有 rssi/ecio（无 rscp，源码
    # commands-nas.c signal_strength 分支）；RSCP 须查 --get-tx-rx-info umts
    # 的 rx_chain 段（blobmsg ×0.1 取负，已换算为 dBm/dB）
    try:
        out2 = subprocess.check_output(
            ["uqmi", "-d", "/dev/cdc-wdm0", "--get-tx-rx-info", "umts"],
            text=True, timeout=4)
        chains = json.loads(out2)
    except Exception:
        return None
    for key in ("rx_chain_0", "rx_chain_1"):
        ch = chains.get(key)
        if not isinstance(ch, dict):
            continue
        try:
            rscp = int(ch.get("rscp"))
        except (TypeError, ValueError):
            continue
        if -120 <= rscp <= -25:
            try:
                ecio = int(ch.get("ecio"))
            except (TypeError, ValueError):
                ecio = None
            return {"tech": "WCDMA", "op": None,
                    "rsrp": rscp, "rsrq": ecio, "sinr": None}
    return None


def rscp_bars(rscp):
    """WCDMA RSCP 档位（dBm）：与 RSRP 阈值不同，单列避免 3G 偏乐观。"""
    if rscp is None:
        return 0
    for th, bars in ((-85, 5), (-95, 4), (-105, 3), (-110, 2), (-115, 1)):
        if rscp >= th:
            return bars
    return 0


def rsrp_bars(rsrp):
    if rsrp is None:
        return 0
    for th, bars in ((-80, 5), (-90, 4), (-100, 3), (-110, 2), (-120, 1)):
        if rsrp >= th:
            return bars
    return 0


# ---------------- 在线设备 ----------------
def list_devices(leases="/tmp/dhcp.leases", maxn=8, extra_macs=()):
    """(名称, IP, MAC) 列表。在线依据 = br-lan ARP 邻居 ∪ WiFi 关联（extra_macs）；
    DHCP 租约只用来补名称/IP——静态 IP 设备无租约也计入，
    反之设备离线后租约滞留（最长 leasetime 12h）不再虚报。"""
    lease = {}   # MAC大写 -> (名称, IP)
    try:
        with open(leases) as f:
            for l in f.read().splitlines():
                p = l.split()
                if len(p) >= 4:
                    lease[p[1].upper()] = (p[3] if p[3] != "*" else p[1][-5:], p[2])
    except Exception:
        pass
    online = {}   # MAC大写 -> IP（ARP 优先；同 MAC 多 IP 取首个）
    try:
        out = subprocess.check_output(["ip", "neigh", "show", "dev", "br-lan"],
                                      text=True, timeout=2)
        for l in out.splitlines():
            p = l.split()
            # 仅 IPv4 且带 lladdr 的条目；FAILED 带 lladdr 但已失联，剔除
            if (len(p) >= 3 and p[1] == "lladdr" and "." in p[0]
                    and (len(p) < 4 or p[3] != "FAILED")):
                online.setdefault(p[2].upper(), p[0])
    except Exception:
        pass
    for mac in extra_macs:
        online.setdefault(mac.upper(), "-")
    if not online:                       # ip neigh 不可用时退回租约表兜底
        rows = [(n, ip, mac) for mac, (n, ip) in lease.items()]
        return rows[:maxn], len(rows)
    rows = [(n, ip, mac) for mac, (n, ip) in lease.items() if mac in online]
    rows += [("未知设备", ip, mac) for mac, ip in sorted(online.items())
             if mac not in lease]
    return rows[:maxn], len(rows)


def wifi_stations():
    """{MAC大写: 信号dBm}：iw station dump 扫全部无线接口（MT7922 原生栈）。"""
    out = {}
    try:
        o = subprocess.check_output(["iw", "dev"], text=True, timeout=2)
    except Exception:
        return out
    for ifn in re.findall(r"Interface (\S+)", o):
        try:
            s = subprocess.check_output(["iw", "dev", ifn, "station", "dump"],
                                        text=True, timeout=2)
            mac = None
            for line in s.splitlines():
                m = re.match(r"Station ([0-9A-Fa-f:]{17})", line)
                if m:
                    mac = m.group(1).upper()
                    continue
                m = re.search(r"signal:\s*(-?\d+)", line)
                if m and mac:
                    out[mac] = int(m.group(1))
                    mac = None
        except Exception:
            continue
    return out


# ---------------- 连接数 ----------------
def conntrack_counts():
    c = read_first("/proc/sys/net/netfilter/nf_conntrack_count")
    m = read_first("/proc/sys/net/netfilter/nf_conntrack_max")
    try:
        return int(c), int(m) if m else 0
    except Exception:
        return None, 0


# ---------------- Docker ----------------
def docker_containers(maxn=8):
    """(名称, 镜像, 状态摘要, 运行中) 列表；状态摘要如 'Up 2 hours'/'Exited (0) 3 days ago'。"""
    if not os.path.exists("/var/run/docker.sock"):
        return None
    try:
        out = subprocess.check_output(
            ["docker", "ps", "-a", "--format",
             "{{.Names}}|{{.Image}}|{{.Status}}"],
            text=True, timeout=5)
        rows = []
        for l in out.splitlines():
            parts = l.split("|")
            if len(parts) < 3:
                continue
            name, image, status = parts[0], parts[1], parts[2]
            rows.append((name, image, status, status.startswith("Up")))
        return rows[:maxn], len(rows)
    except Exception:
        return None


# ---------------- 屏幕/绘制 ----------------
def fb_size():
    try:
        with open("/sys/class/graphics/fb0/virtual_size") as f:
            w, h = f.read().split(",")
        return int(w), int(h)
    except Exception:
        return 320, 240


def hex2rgb(s):
    s = (s or "").lstrip("#")
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (255, 255, 255)


def to_rgb565(img):
    # 实测（四色带标定）：本面板（dts bgr+MADCTL_BGR）要求 R 在 bit[15:11]——
    # 即标准 RGB565 打包。此前误改为 B 高位导致红蓝互换；视频链路同理须用 rgb565le。
    rgb = img.convert("RGB").tobytes()
    n = len(rgb) // 3
    u16 = [((rgb[i] & 0xF8) << 8) | ((rgb[i + 1] & 0xFC) << 3) | (rgb[i + 2] >> 3)
           for i in range(0, n * 3, 3)]
    return struct.pack("<%dH" % n, *u16)


class Screen:
    """fbtft 为 deferred-io 驱动：脏页标记只发生在 mmap 写入路径（write() 不触发刷屏，
    LVGL 亦走 mmap）。故用 mmap 写帧；失败时回退 write()。"""

    def __init__(self, fb_fd):
        self.fd = fb_fd
        self.fb_w, self.fb_h = fb_size()          # fb 物理几何（320x240）
        self.w = self.fb_w - VIS_X0               # 内容画布 = 可见区（x 全宽）
        self.h = VIS_H
        self.off = (VIS_Y0 * self.fb_w + VIS_X0) * 2   # mmap 字节偏移
        self.mm = None
        try:
            self.mm = mmap.mmap(fb_fd, self.fb_w * self.fb_h * 2)
        except Exception as e:
            print("mmap fb 失败，回退 write():", e)

    def put(self, img, rotate=0, invert=False):
        if rotate:
            img = img.rotate(int(rotate), expand=True)
        if invert:
            img = ImageOps.invert(img.convert("RGB"))
        raw = to_rgb565(img)
        if self.mm is not None:
            self.mm.seek(self.off)
            self.mm.write(raw)
        else:
            os.lseek(self.fd, self.off, os.SEEK_SET)
            os.write(self.fd, raw)


FIT_MODES = ("cover", "stretch", "contain")


def norm_fit(mode):
    return mode if mode in FIT_MODES else "cover"


def norm_rotate(v):
    """旋转值归一：mod 360 后仅接受 90 的整数倍（UI 只发这四档，
    手改 uci 的任意值一律归 0，避免 PIL 任意角与 transpose 90° 步进的不一致）。"""
    try:
        r = int(str(v).strip()) % 360
    except (TypeError, ValueError):
        return 0
    return r if r % 90 == 0 else 0


def media_rotate(page, base):
    """媒体页最终旋转 = 全局 rotate + 页面 rotate（mod 360）。
    语义锚定 PIL：正角=逆时针（Pillow 官方文档 Image.rotate）；视频链
    transpose 同步用逆时针映射（ffmpeg transpose=2=cclock）保持三族一致。"""
    return (int(base) + norm_rotate(page.get("rotate", 0))) % 360


def fit_img(img, w, h, mode="cover", bg=(0, 0, 0)):
    """媒体整页显示比例适配（每页 fit_mode 可选）：
    cover=等比铺满居中裁切（默认，历史行为）；stretch=拉伸铺满（宽高比变形）；
    contain=等比完整显示居中留边（衬 bg 底色）。"""
    sw, sh = img.size
    if mode == "stretch":
        return img.resize((w, h))
    if mode == "contain":
        scale = min(w / sw, h / sh)
        nw, nh = max(1, int(sw * scale + 0.5)), max(1, int(sh * scale + 0.5))
        out = Image.new("RGB", (w, h), tuple(bg))
        out.paste(img.resize((nw, nh)), ((w - nw) // 2, (h - nh) // 2))
        return out
    scale = max(w / sw, h / sh)
    img = img.resize((int(sw * scale + 0.5), int(sh * scale + 0.5)))
    x = (img.width - w) // 2
    y = (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _media_files(path):
    """目录/文件 → 播放候选列表。不按扩展名白名单过滤——解码能力交给
    PIL/ffmpeg（芯片 VPU 走 rkmpp、其余软解），打不开的文件播放时自动跳过；
    只排除隐藏文件与子目录。目录不可读按无文件处理（不抛异常打断主循环）。"""
    if os.path.isdir(path):
        try:
            names = os.listdir(path)
        except OSError:
            return []
        return sorted(os.path.join(path, f) for f in names
                      if not f.startswith(".") and os.path.isfile(os.path.join(path, f)))
    if os.path.isfile(path):
        return [path]
    return []


# ---------------- 组件绘制 ----------------

_FONT_CACHE = {}


def font(sz):
    try:
        if sz not in _FONT_CACHE:
            _FONT_CACHE[sz] = ImageFont.truetype(FONT, sz)
        return _FONT_CACHE[sz]
    except Exception:
        return FONTS.get("big")


def dim(c, f=0.45):
    return tuple(int(x * f) for x in c)


def draw_icon(d, kind, x, y, c):
    """14x14 线条图标（PIL 原语，无 emoji 字体依赖）：每个类型展示配图标+名称。"""
    if kind in ("clock", "countdown"):
        d.ellipse((x + 1, y + 1, x + 13, y + 13), outline=c, width=2)
        d.line((x + 7, y + 4, x + 7, y + 8), fill=c, width=2)
        d.line((x + 7, y + 8, x + 11, y + 8), fill=c, width=2)
    elif kind in ("date", "lunar"):
        d.rectangle((x + 1, y + 3, x + 13, y + 13), outline=c, width=2)
        d.line((x + 1, y + 7, x + 13, y + 7), fill=c, width=2)
        d.line((x + 4, y, x + 4, y + 3), fill=c, width=2)
        d.line((x + 10, y, x + 10, y + 3), fill=c, width=2)
    elif kind == "uptime":
        d.line((x + 2, y + 1, x + 12, y + 1), fill=c, width=2)
        d.line((x + 2, y + 13, x + 12, y + 13), fill=c, width=2)
        d.line((x + 3, y + 2, x + 11, y + 12), fill=c, width=1)
        d.line((x + 11, y + 2, x + 3, y + 12), fill=c, width=1)
    elif kind in ("ip_lan", "ip_wan"):
        d.ellipse((x, y + 2, x + 13, y + 12), outline=c, width=2)
        d.line((x + 1, y + 7, x + 12, y + 7), fill=c, width=1)
        d.ellipse((x + 4, y + 2, x + 9, y + 12), outline=c, width=1)
    elif kind == "hostname":
        d.rectangle((x + 1, y + 1, x + 13, y + 9), outline=c, width=2)
        d.line((x + 7, y + 9, x + 7, y + 12), fill=c, width=2)
        d.line((x + 4, y + 12, x + 10, y + 12), fill=c, width=2)
    elif kind == "cpu_temp":
        d.rectangle((x + 4, y, x + 9, y + 9), outline=c, width=2)
        d.ellipse((x + 2, y + 7, x + 11, y + 14), outline=c, width=2)
    elif kind == "temps":
        # 温度计（四行总览）：管芯+液柱+球泡，与 cpu_temp 图标区分在刻度线
        d.rectangle((x + 5, y, x + 9, y + 7), outline=c, width=2)
        d.line((x + 7, y + 2, x + 7, y + 10), fill=c, width=1)
        d.line((x + 3, y + 2, x + 5, y + 2), fill=c, width=1)
        d.line((x + 3, y + 5, x + 5, y + 5), fill=c, width=1)
        d.ellipse((x + 3, y + 7, x + 11, y + 14), outline=c, width=2)
        d.ellipse((x + 5, y + 9, x + 9, y + 12), fill=c)
    elif kind in ("load", "cpugraph"):
        for i, hgt in enumerate((5, 9, 13, 7)):
            d.line((x + 1 + i * 4, y + 14 - hgt, x + 1 + i * 4, y + 14), fill=c, width=2)
    elif kind == "mem":
        d.rectangle((x + 2, y + 3, x + 12, y + 11), outline=c, width=2)
        for i in range(3):
            d.line((x + 4 + i * 3, y, x + 4 + i * 3, y + 3), fill=c, width=1)
            d.line((x + 4 + i * 3, y + 11, x + 4 + i * 3, y + 14), fill=c, width=1)
    elif kind == "disk":
        d.ellipse((x + 1, y, x + 13, y + 5), outline=c, width=2)
        d.line((x + 1, y + 2, x + 1, y + 12), fill=c, width=2)
        d.line((x + 13, y + 2, x + 13, y + 12), fill=c, width=2)
        d.ellipse((x + 1, y + 10, x + 13, y + 14), outline=c, width=2)
    elif kind == "modem":
        d.rectangle((x + 3, y + 6, x + 11, y + 14), outline=c, width=2)
        d.line((x + 7, y + 6, x + 7, y), fill=c, width=2)
    elif kind == "signal":
        for i, hgt in enumerate((4, 7, 10, 13)):
            d.line((x + 1 + i * 4, y + 14 - hgt, x + 1 + i * 4, y + 14), fill=c, width=2)
    elif kind == "netgraph":
        d.line((x + 4, y + 1, x + 4, y + 8), fill=c, width=2)
        d.polygon([(x + 1, y + 8), (x + 7, y + 8), (x + 4, y + 12)], fill=c)
        d.line((x + 10, y + 13, x + 10, y + 6), fill=c, width=2)
        d.polygon([(x + 7, y + 6), (x + 13, y + 6), (x + 10, y + 2)], fill=c)
    elif kind == "lanrate":
        d.line((x, y + 4, x + 9, y + 4), fill=c, width=2)
        d.polygon([(x + 8, y + 1), (x + 8, y + 7), (x + 13, y + 4)], fill=c)
        d.line((x + 13, y + 10, x + 4, y + 10), fill=c, width=2)
        d.polygon([(x + 5, y + 7), (x + 5, y + 13), (x, y + 10)], fill=c)
    elif kind == "topsites":
        d.ellipse((x, y + 2, x + 13, y + 12), outline=c, width=2)
        d.line((x + 1, y + 7, x + 12, y + 7), fill=c, width=1)
        for i, lw in enumerate((3, 6, 9)):
            d.line((x + 3 + lw, y + 3 + i * 4, x + 5 + lw, y + 3 + i * 4),
                   fill=c, width=2)
    elif kind == "devices":
        d.rectangle((x + 1, y + 1, x + 13, y + 9), outline=c, width=2)
        d.line((x + 7, y + 9, x + 7, y + 12), fill=c, width=2)
        d.line((x + 4, y + 12, x + 10, y + 12), fill=c, width=2)
    elif kind == "conncount":
        d.ellipse((x, y + 5, x + 4, y + 9), fill=c)
        d.ellipse((x + 10, y + 1, x + 14, y + 5), fill=c)
        d.ellipse((x + 10, y + 9, x + 14, y + 13), fill=c)
        d.line((x + 4, y + 7, x + 10, y + 3), fill=c, width=1)
        d.line((x + 4, y + 7, x + 10, y + 11), fill=c, width=1)
    elif kind == "docker":
        d.rectangle((x + 1, y + 1, x + 6, y + 6), outline=c, width=1)
        d.rectangle((x + 8, y + 1, x + 13, y + 6), outline=c, width=1)
        d.rectangle((x + 1, y + 8, x + 6, y + 13), outline=c, width=1)
        d.rectangle((x + 8, y + 8, x + 13, y + 13), outline=c, width=1)
    elif kind == "custom":
        for i in range(3):
            d.line((x + 1, y + 2 + i * 5, x + 13, y + 2 + i * 5), fill=c, width=2)
    else:
        d.rectangle((x + 2, y + 2, x + 12, y + 12), outline=c, width=2)


def widget_netgraph(d, x, y, w, h, fg):
    iface, hist, rates = NETMON.snapshot() if NETMON else (None, [], (0, 0))
    draw_icon(d, "netgraph", x, y + 2, fg)
    d.text((x + 20, y), "网速", font=FONTS["lbl"], fill=fg)
    d.text((x + w - 4, y), "▼%s ▲%s" % (fmt_rate(rates[0]), fmt_rate(rates[1])),
           font=FONTS["lbl"], fill=fg, anchor="ra")
    if iface:
        # 接口名给右侧速率文本让位：高速率(≥100KB/s)时右对齐文本左扩会压住
        # 接口名，按剩余宽度截断（带 …），放不下则不显示
        rate_w = d.textlength("▼%s ▲%s" % (fmt_rate(rates[0]), fmt_rate(rates[1])),
                              font=FONTS["lbl"])
        if_x = x + 20 + d.textlength("网速", font=FONTS["lbl"]) + 8
        nm, ell = iface, ""
        while nm and d.textlength(nm + "…", font=FONTS["lbl"]) > (x + w - 4) - rate_w - 8 - if_x:
            nm = nm[:-1]
            ell = "…"
        if nm:
            d.text((if_x, y), nm + ell, font=FONTS["lbl"], fill=dim(fg, 0.7))
    ch_area_top, ch_area_bottom = y + 24, y + h - 4
    # 网格细化：1/8 间隔 7 条，四分位为主线（亮一档）+奇八分位辅线（更暗），层次分明不糊
    for i in range(1, 8):
        gy = ch_area_top + (ch_area_bottom - ch_area_top) * i // 8
        d.line((x, gy, x + w - 4, gy),
               fill=dim(fg, 0.25) if i % 2 == 0 else dim(fg, 0.12))
    if len(hist) >= 2:
        # 逐点差分速率：恒速=水平线、停止=落零（区别于"窗口累计增量"的爬坡/平台）。
        # 计数器回绕/重置产生负增量，该点跳过；x 轴按采样时间戳均布，抖动不失真。
        def series(idx):
            vals = []
            for pv, cu in zip(hist, hist[1:]):
                dt = cu[0] - pv[0]
                delta = cu[idx] - pv[idx]
                vals.append(delta / dt if dt > 0 and delta >= 0 else None)
            return vals
        srx, stx = series(1), series(2)
        peak = max([v for v in srx + stx if v is not None] or [0.0]) or 1.0
        t0, span = hist[0][0], max(1e-6, hist[-1][0] - hist[0][0])

        def poly(vals, color):
            pts = []
            for i, v in enumerate(vals):
                if v is None:
                    continue
                px = x + (w - 4) * (hist[i + 1][0] - t0) / span
                py = ch_area_bottom - (ch_area_bottom - ch_area_top) * min(1.0, v / peak)
                pts.append((px, py))
            if len(pts) >= 2:
                d.line(pts, fill=color, width=2)
        poly(srx, dim(fg, 0.55))  # rx：与内容同色系的暗一档，便于区分上下行
        poly(stx, fg)               # tx
    return h


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.0f %s" % (n, unit) if unit in ("B", "KB") else "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


def widget_lanrate(d, x, y, w, h, fg):
    """LAN 口总流量（累计上传/下载，br-lan 计数器直读）——用户明确要总量非实时。"""
    stats = read_netdev()
    rx, tx = stats.get("br-lan", (0, 0))
    draw_icon(d, "lanrate", x, y + 2, fg)
    d.text((x + 20, y), "LAN 总流量", font=FONTS["lbl"], fill=fg)
    d.text((x + w - 4, y), "br-lan", font=FONTS["lbl"], fill=dim(fg, 0.7), anchor="ra")
    d.text((x, y + 32), "▼ 累计下载", font=FONTS["val"], fill=dim(fg, 0.55))
    d.text((x + w - 4, y + 28), fmt_bytes(rx), font=FONTS["title"],
           fill=dim(fg, 0.55), anchor="ra")
    d.text((x, y + 70), "▲ 累计上传", font=FONTS["val"], fill=fg)
    d.text((x + w - 4, y + 66), fmt_bytes(tx), font=FONTS["title"],
           fill=fg, anchor="ra")
    return h


def top_sites(maxn=5):
    """按字节聚合外网目的地址 top N（/proc/net/nf_conntrack，含双向 bytes）。"""
    agg = {}
    try:
        with open("/proc/net/nf_conntrack") as f:
            for line in f:
                if " bytes=" not in line:
                    continue
                m = re.search(r"dst=((?:\d{1,3}\.){3}\d{1,3})", line)
                if not m:
                    continue
                ip = m.group(1)
                o1 = int(ip.split(".")[0])
                if ip.startswith(("192.168.", "10.", "127.", "169.254.")) \
                        or re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip) \
                        or 224 <= o1 <= 239 or o1 == 255:
                    continue
                agg[ip] = agg.get(ip, 0) + sum(
                    int(x) for x in re.findall(r"bytes=(\d+)", line))
    except Exception:
        return []
    return sorted(agg.items(), key=lambda kv: -kv[1])[:maxn]


_RDNS_CACHE = {}


def rdns(ip):
    """IP→域名（dnsmasq 反解，缓存 5 分钟；失败回退显示 IP）。"""
    now = time.time()
    c = _RDNS_CACHE.get(ip)
    if c and now - c[1] < 300:
        return c[0]
    name = None
    try:
        out = subprocess.check_output(["nslookup", ip, "127.0.0.1"],
                                      text=True, timeout=2)
        for line in out.splitlines():
            if "name =" in line or "name=" in line:
                name = line.split("=", 1)[-1].strip().rstrip(".").split()[-1]
                if name.endswith(".in-addr.arpa"):
                    name = None
                break
    except Exception:
        pass
    if not name:
        name = ip
    _RDNS_CACHE[ip] = (name, now)
    return name


def widget_topsites(d, x, y, w, h, fg):
    # 行数按可用高度自适应（标题 26 + 每行 24）：放不下 5 行自动少显示，
    # 避免第 5 行贴出帧底（内容区实际高常为 126 = 4 行）
    nrows = max(1, min(5, (h - 26) // 24))
    rows = top_sites(nrows)
    draw_icon(d, "topsites", x, y + 2, fg)
    d.text((x + 20, y), "热门网址 TOP%d" % nrows, font=FONTS["lbl"], fill=fg)
    if not rows:
        d.text((x, y + 30), "无外网连接数据", font=FONTS["lbl"], fill=dim(fg))
        return h
    yy = y + 26
    for i, (ip, b) in enumerate(rows):
        nm = rdns(ip)
        while nm and d.textlength(nm, font=FONTS["lbl"]) > w - 120:
            nm = nm[:-1]
        d.text((x, yy), "%d. %s" % (i + 1, nm), font=FONTS["lbl"], fill=fg)
        d.text((x + w - 4, yy), fmt_bytes(b), font=FONTS["lbl"],
               fill=dim(fg, 0.8), anchor="ra")
        yy += 24
    return h


def widget_cpugraph(d, x, y, w, h, fg):
    """四核柱状图：图标标题行 + 满宽粗柱 + 12.5% 间隔主辅网格线 + 大号百分比标注。"""
    pcts = cpu_percents(read_cpu_per_core())
    draw_icon(d, "cpugraph", x, y + 2, fg)
    d.text((x + 20, y), "CPU 四核", font=FONTS["lbl"], fill=fg)
    bh = h - 64
    if pcts is None:
        d.text((x, y + 30), "采样中…", font=FONTS["lbl"], fill=dim(fg))
        return h
    n = max(1, len(pcts))
    gap = 12
    bw = (w - 8 - (n - 1) * gap) // n
    # 网格细化：12.5% 间隔，四分位主线（亮一档）+奇八分位辅线（更暗）；
    # 组件高度提到 126（柱区 62px）后辅线间距 ~7.8px，细而不糊
    for frac in (0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875):
        gy = y + 24 + int(bh * (1 - frac))
        d.line((x + 2, gy, x + w - 6, gy),
               fill=dim(fg, 0.2) if frac in (0.25, 0.5, 0.75) else dim(fg, 0.1))
    for i, p in enumerate(pcts):
        bx = x + 4 + i * (bw + gap)
        c = (80, 200, 120) if p < 60 else (255, 180, 0) if p < 90 else (255, 80, 80)
        hh = max(3, int(bh * p / 100))
        d.rectangle((bx, y + 24 + bh - hh, bx + bw, y + 24 + bh), fill=c)
        d.text((bx + bw // 2, y + 24 + bh + 6), "%d%%" % p, font=FONTS["val"],
               fill=fg, anchor="ma")
    return h


def widget_signal(d, x, y, w, h, fg):
    s = modem_signal()
    draw_icon(d, "signal", x, y + 2, fg)
    t = (s or {}).get("tech") or ""
    lbl = ("5G 信号" if ("5G" in t or "NR" in t)
           else "3G 信号" if t == "WCDMA"
           else "4G 信号" if t else "信号")
    d.text((x + 20, y), lbl, font=FONTS["lbl"], fill=fg)
    if s:
        right = (s["tech"] + " " + s["op"]) if s.get("op") else s["tech"]
    else:
        right = "无服务"
    d.text((x + w - 4, y), right, font=FONTS["lbl"], fill=dim(fg, 0.8), anchor="ra")
    if not s:
        d.text((x, y + 28), "无信号数据", font=FONTS["lbl"], fill=dim(fg))
        return h
    bars = (rscp_bars if s.get("tech") == "WCDMA" else rsrp_bars)(s["rsrp"])
    for i in range(5):
        bh2 = 18 + i * 12
        bx = x + 6 + i * 22
        color = fg if i < bars else dim(fg, 0.25)
        d.rectangle((bx, y + 86 - bh2, bx + 14, y + 86), fill=color)
    vals = []
    for k, unit in (("rsrp", "dBm"), ("rsrq", "dB"), ("sinr", "dB")):
        v = s.get(k)
        if v is not None:
            vals.append("%s %s%s" % (k.upper(), v, unit))
    for i, t in enumerate(vals[:3]):
        d.text((x + 130, y + 22 + i * 22), t, font=FONTS["val"], fill=fg)
    return h


def widget_modem(d, x, y, w, h, fg):
    """5G 模组完整信息：名称/制造商/版本(AT+CGMR)/AT端口 四行，
    表头右侧带运营商+制式（modem_signal 10s 缓存）。"""
    info = modem_full() or {}
    draw_icon(d, "modem", x, y + 2, fg)
    d.text((x + 20, y), "5G 模组", font=FONTS["lbl"], fill=fg)
    s = info.get("sig") or {}
    right = ""
    if s:
        right = ((s.get("op") + " ") if s.get("op") else "") + s.get("tech", "")
    d.text((x + w - 4, y), right or "--", font=FONTS["lbl"],
           fill=dim(fg, 0.8), anchor="ra")
    rows = [("名称", info.get("model")), ("制造商", info.get("maker")),
            ("版本", info.get("fw")), ("AT端口", info.get("at"))]
    pitch = max(22, (h - 32) // 4)
    avail = w - 70                     # 标签列最宽 62px("AT端口")+8px 气口
    yy = y + 26
    for name, v in rows:
        d.text((x, yy), name, font=FONTS["val"], fill=dim(fg, 0.8))
        if v:
            vv, fnt, dy = str(v), FONTS["val"], 0
            if d.textlength(vv, font=fnt) > avail:
                # 长版本号(如 RM520NGLAAR03A04M4G=235px@20px)降一档字宽免截断
                fnt, dy = FONTS["lbl"], 1
            ell = ""
            while vv and d.textlength(vv + ell, font=fnt) > avail:
                vv = vv[:-1]
                ell = "…"
            d.text((x + 70, yy + dy), vv + ell, font=fnt, fill=fg)
        else:
            d.text((x + 70, yy), "--", font=FONTS["val"], fill=dim(fg, 0.5))
        yy += pitch
    return h


def widget_devices(d, x, y, w, h, fg):
    # 行距 46：两行内容(名称+WiFi/MAC)占 ~38px，设备块间留 ~13px 呼吸空隙
    pitch = 46
    sta = wifi_stations()
    rows, total = list_devices(maxn=(h - 26) // pitch, extra_macs=sta.keys())
    draw_icon(d, "devices", x, y + 2, fg)
    d.text((x + 20, y), "在线设备", font=FONTS["lbl"], fill=fg)
    d.text((x + w - 4, y), "共 %d 台" % total, font=FONTS["lbl"],
           fill=dim(fg), anchor="ra")
    yy = y + 24
    for name, ip, mac in rows:
        nm = name
        ell = ""
        while nm and d.textlength(nm + "…", font=FONTS["val"]) > w - 146:
            nm = nm[:-1]
            ell = "…"
        d.text((x, yy), nm + ell, font=FONTS["val"], fill=fg)
        d.text((x + w - 4, yy), ip, font=FONTS["val"], fill=dim(fg, 0.8), anchor="ra")
        sig = sta.get(mac)
        if sig is not None:
            # WiFi 信号按强弱着色（好绿/中黄/差红）
            c = (60, 220, 90) if sig > -60 else (255, 180, 0) if sig > -72 else (255, 90, 90)
            d.text((x, yy + 22), "WiFi %ddBm" % sig, font=FONTS["lbl"], fill=c)
        else:
            d.text((x, yy + 22), "有线", font=FONTS["lbl"], fill=dim(fg, 0.7))
        d.text((x + w - 4, yy + 22), mac, font=FONTS["lbl"],
               fill=dim(fg, 0.55), anchor="ra")
        yy += pitch
    return h


def widget_conncount(d, x, y, w, h, fg):
    c, m = conntrack_counts()
    draw_icon(d, "conncount", x, y + 2, fg)
    d.text((x + 20, y), "连接数", font=FONTS["lbl"], fill=fg)
    if c is None:
        d.text((x, y + 28), "无 conntrack", font=FONTS["lbl"], fill=dim(fg))
        return h
    ratio = c / m if m else 0
    color = fg if ratio < 0.6 else (255, 180, 0) if ratio < 0.85 else (255, 80, 80)
    d.text((x, y + 20), "%d" % c, font=FONTS["big"], fill=color)
    d.text((x + 130, y + 34), "/ %d" % m, font=FONTS["lbl"], fill=dim(fg))
    d.rectangle((x, y + h - 14, x + w - 4, y + h - 8), fill=dim(fg, 0.25))
    d.rectangle((x, y + h - 14, x + int((w - 4) * min(1, ratio)), y + h - 8), fill=color)
    return h


def _docker_status(status, up):
    """'Up 2 hours (healthy)' → '运行 2小时'；'Exited (0) 3 days ago' → '停止 3天'。"""
    import re as _re
    if not up:
        m = _re.search(r"(\d+)\s+(second|minute|hour|day|week|month)", status)
        unit = {"second": "秒", "minute": "分", "hour": "小时", "day": "天",
                "week": "周", "month": "月"}
        return "停止" + ((" " + m.group(1) + unit[m.group(2)]) if m else "")
    m = _re.search(r"Up\s+(?:\d+\s+)?(\d+)\s+(second|minute|hour|day|week|month)s?",
                   status)
    unit = {"second": "秒", "minute": "分", "hour": "小时", "day": "天",
            "week": "周", "month": "月"}
    if m:
        return "运行 " + m.group(1) + unit[m.group(2)]
    return "运行中"


def widget_docker(d, x, y, w, h, fg):
    # 行距 42：名称/状态+镜像两行占 ~34px，容器块间留 ~12px 呼吸空隙
    pitch = 42
    res = docker_containers(maxn=(h - 26) // pitch)
    draw_icon(d, "docker", x, y + 2, fg)
    d.text((x + 20, y), "Docker 容器", font=FONTS["lbl"], fill=fg)
    if res is None:
        d.text((x + w - 4, y), "未运行", font=FONTS["lbl"], fill=dim(fg), anchor="ra")
        return h
    rows, total = res
    d.text((x + w - 4, y), "共 %d 个" % total, font=FONTS["lbl"],
           fill=dim(fg), anchor="ra")
    yy = y + 24
    for name, image, status, up in rows:
        c = (60, 220, 90) if up else (255, 90, 90)
        d.ellipse((x + 2, yy + 5, x + 10, yy + 13), fill=c)
        nm = name
        while nm and d.textlength(nm, font=FONTS["val"]) > w - 120:
            nm = nm[:-1]
        d.text((x + 18, yy), nm, font=FONTS["val"], fill=fg)
        st = _docker_status(status, up)
        d.text((x + w - 4, yy + 2), st, font=FONTS["lbl"], fill=c, anchor="ra")
        im_ = image
        while im_ and d.textlength(im_, font=FONTS["lbl"]) > w - 30:
            im_ = im_[:-1]
        d.text((x + 18, yy + 22), im_, font=FONTS["lbl"], fill=dim(fg, 0.7))
        yy += pitch
    return h


def widget_calendar(d, x, y, w, h, fg, tc, bg):
    """当月日历表：周一为首列，今日反色高亮，农历节日打点，表头右侧今日农历/节日。"""
    import calendar as _cal
    today = date.today()
    draw_icon(d, "lunar", x + 2, y + 1, fg)
    d.text((x + 22, y), "%d年%d月" % (today.year, today.month), font=FONTS["lbl"], fill=fg)
    ly, lm, leap, ld = solar_to_lunar(today)
    fest = LUNAR_FEST.get((lm, ld)) or SOLAR_FEST.get(today.strftime("%m%d"))
    right = ("·" + fest) if fest else "农历%s月%s" % (
        ("闰" if leap else "") + CN_MONTH[lm], CN_DAY[ld - 1])
    d.text((x + w - 2, y), right, font=FONTS["lbl"], fill=tc if fest else dim(fg),
           anchor="ra")
    colw = (w - 8) / 7.0
    for i, ch in enumerate("一二三四五六日"):
        d.text((x + 4 + colw * i + colw / 2, y + 24), ch, font=font(13),
               fill=dim(fg), anchor="ma")
    weeks = _cal.Calendar(firstweekday=0).monthdatescalendar(today.year, today.month)
    fday = font(15)
    for r, week in enumerate(weeks[:6]):
        for c, dt in enumerate(week):
            if dt.month != today.month:
                continue
            cx = x + 4 + colw * c + colw / 2
            cy = y + 44 + r * 16
            _, lmm, _, ldd = solar_to_lunar(dt)
            fest2 = LUNAR_FEST.get((lmm, ldd)) or SOLAR_FEST.get(dt.strftime("%m%d"))
            col = fg
            if dt == today:
                d.rectangle((cx - 11, cy - 2, cx + 11, cy + 14), fill=fg)
                col = bg
            elif c >= 5:
                col = dim(fg)
            elif fest2:
                col = tc            # 节日日期用标题色，醒目
            d.text((cx, cy), "%d" % dt.day, font=fday, fill=col, anchor="ma")
            if fest2 and dt != today:
                # 节日标记点：6px 标题色（4px 太不起眼）
                d.ellipse((cx - 3, cy + 13, cx + 3, cy + 19), fill=tc)
    return h


def widget_countdown(d, x, y, w, h, fg, page):
    label = page.get("countdown_label") or "目标日"
    ds = page.get("countdown_date") or ""
    draw_icon(d, "countdown", x, y + 8, dim(fg))
    try:
        target = datetime.strptime(ds, "%Y-%m-%d").date()
    except ValueError:
        d.text((x + 22, y + 8), "日期无效(YYYY-MM-DD)", font=FONTS["lbl"], fill=(255, 120, 120))
        return h
    days = (target - date.today()).days
    diff = (datetime.combine(target, datetime.min.time()) - datetime.now())
    fnum = font(48)
    if diff.total_seconds() >= 0:
        d_, rem = divmod(int(diff.total_seconds()), 86400)
        h_, rem = divmod(rem, 3600)
        mi_, s_ = divmod(rem, 60)
        d.text((x + 22, y), "距 %s(%s)" % (label, ds), font=FONTS["lbl"], fill=dim(fg))
        num = "%d" % d_
        dw = int(d.textlength(num, font=fnum))
        tw = int(d.textlength("%02d:%02d:%02d" % (h_, mi_, s_), font=FONTS["title"]))
        bx = x + max(10, (w - dw - 34 - tw) // 2)
        d.text((bx, y + 24), num, font=fnum, fill=fg)
        d.text((bx + dw + 8, y + 44), "天", font=FONTS["title"], fill=dim(fg))
        d.text((bx + dw + 34, y + 44), "%02d:%02d:%02d" % (h_, mi_, s_),
               font=FONTS["title"], fill=fg)
    else:
        d.text((x + 22, y), "%s 已过" % label, font=FONTS["lbl"], fill=dim(fg))
        num = "%d" % (-days if days < 0 else 0)
        dw = int(d.textlength(num, font=fnum))
        bx = x + max(10, (w - dw - 34) // 2)
        d.text((bx, y + 24), num, font=fnum, fill=fg)
        d.text((bx + dw + 8, y + 44), "天", font=FONTS["title"], fill=fg)
    return h


def disk_parts():
    """主要可写分区明细：[(标签, 已用G, 总量G), ...]，挂载点缺失自动跳过。"""
    parts = []
    for label, mntp in (("系统", "/overlay"), ("媒体库", "/mnt/mmc"),
                        ("Docker", "/mnt/docker")):
        try:
            st = os.statvfs(mntp)
        except Exception:
            continue
        t = st.f_blocks * st.f_frsize / 1e9
        if t <= 0:
            continue
        parts.append((label, t - st.f_bfree * st.f_frsize / 1e9, t))
    return parts


def widget_diskdetail(d, x, y, w, h, fg):
    """存储分区明细：无标题行，分区行自适应铺满内容区
    （带标题行+聚合总量时用户反馈拥挤，已去）。"""
    parts = disk_parts()
    if not parts:
        draw_icon(d, "disk", x, y + 2, fg)
        d.text((x + 20, y), "无分区数据", font=FONTS["lbl"], fill=dim(fg))
        return h
    rowh = max(30, (h - 4) // len(parts))
    yy = y + 2
    for label, u, t in parts:
        ratio = max(0.0, min(1.0, u / t)) if t else 0
        d.text((x, yy + 2), label, font=FONTS["val"], fill=fg)
        d.text((x + w - 4, yy + 2), "%.1f/%.1fG" % (u, t), font=FONTS["val"],
               fill=dim(fg, 0.8), anchor="ra")
        # bar 下移：文字 ink 底约 yy+18，bar yy+29 起——行内间隙 ~11px、
        # bar 底到下一行文字 ~9px，两侧均衡（原 yy+24 文字贴 bar 拥挤）
        d.rectangle((x, yy + 29, x + w, yy + 35), fill=dim(fg, 0.15))
        d.rectangle((x, yy + 29, x + int(w * ratio), yy + 35),
                    fill=bar_color(ratio, fg))
        yy += rowh
    return h


def widget_temps(d, x, y, w, h, fg):
    """温度总览：CPU / GPU / 5G 模组 / 无线网卡 四行，数值阈值变色
    （>60 黄 / >75 红，temp_color）。多传感器（DBDC 双 phy、模组多路）
    取最高值；数据缺失该行显示 --，标题右侧常显全局最高。"""
    t = temps_info() or {}
    draw_icon(d, "temps", x, y + 2, fg)
    d.text((x + 20, y), "温度", font=FONTS["lbl"], fill=fg)
    wmax = None
    for s in (t.get("wifi") or []):
        if isinstance(s.get("temp"), int) and (wmax is None or s["temp"] > wmax):
            wmax = s["temp"]
    mmax = t.get("modem", {}).get("max") if isinstance(t.get("modem"), dict) else None
    gmax = None
    for v in [t.get("cpu"), t.get("gpu"), wmax, mmax]:
        if isinstance(v, int) and (gmax is None or v > gmax):
            gmax = v
    d.text((x + w - 4, y), ("最高 %d°C" % gmax) if gmax is not None else "--",
           font=FONTS["lbl"], fill=dim(fg, 0.8), anchor="ra")
    rows = [("CPU", t.get("cpu")), ("GPU", t.get("gpu")),
            ("模组", mmax), ("网卡", wmax)]
    yy = y + 24
    step = max(24, (h - 26) // 4)
    for name, v in rows:
        d.text((x, yy), name, font=FONTS["val"], fill=dim(fg, 0.8))
        if isinstance(v, int):
            d.text((x + w - 4, yy), "%d°C" % v, font=FONTS["val"],
                   fill=temp_color(v, fg), anchor="ra")
        else:
            d.text((x + w - 4, yy), "--", font=FONTS["val"],
                   fill=dim(fg, 0.5), anchor="ra")
        yy += step
    return h


WIDGETS = {
    "netgraph": widget_netgraph,
    "lanrate": widget_lanrate,
    "topsites": widget_topsites,
    "cpugraph": widget_cpugraph,
    "signal": widget_signal,
    "modem": widget_modem,
    "devices": widget_devices,
    "conncount": widget_conncount,
    "docker": widget_docker,
    "diskdetail": widget_diskdetail,
    "temps": widget_temps,
}
WIDGET_HEIGHT = {"netgraph": 100, "lanrate": 104, "topsites": 152, "cpugraph": 126,
                 "signal": 88, "modem": 126, "devices": 128, "conncount": 84,
                 "docker": 128, "diskdetail": 128, "temps": 128}


# ---------------- 整页类型 ----------------
def page_image(scr, page, rotate, invert, bg):
    files = _media_files(page.get("image_path", ""))
    if not files:
        return False
    if not hasattr(page_image, "idx"):
        page_image.idx = 0
    img = None
    for _ in range(len(files)):
        f = files[page_image.idx % len(files)]
        page_image.idx += 1
        try:
            im = Image.open(f)
            if im.format == "JPEG":
                # draft：JPEG DCT 降采样解码——大图按目标尺寸量级（1/2^n）解码，
                # 数千万像素照片解码快一个量级，后续 fit_img 再精确缩放
                im.draft("RGB", (scr.w, scr.h))
            img = im.convert("RGB")
            break
        except Exception:
            continue           # 目录混入非图片文件：轮播自动跳过
    if img is None:
        return False
    # 旋转语义与信息页一致（draw_items 同构）：90/270 先在换轴画布上适配，
    # put() 旋转回横屏再写 mmap——直接横屏适配后旋转会把竖版数据按横屏
    # 步长写入（行错位花屏，BG146d 前的潜伏缺陷）
    rot = media_rotate(page, rotate)
    cw, ch = canvas_dims(scr, rot)
    scr.put(fit_img(img, cw, ch, norm_fit(page.get("fit_mode")), bg),
            rot, invert)
    return True


def page_gif(scr, page, rotate, invert, duration, bg):
    """GIF：视频同款节拍——名义时间表推进，解码/缩放耗时不再拖慢帧距；
    帧率钳到 video_fps（面板 SPI ~20fps 上限，更快的 GIF 写了也被 defio 合并）。"""
    path = page.get("gif_path", "")
    if not os.path.isfile(path):
        return False
    mode = norm_fit(page.get("fit_mode"))
    rot = media_rotate(page, rotate)
    cw, ch = canvas_dims(scr, rot)   # 90/270 换轴适配（与 page_image 同构）
    try:
        gif = Image.open(path)
        fps_cap = max(10.0, min(25.0, float(uci_get("main.video_fps", "20") or 20)))
        min_step = 1.0 / fps_cap
        end = time.time() + max(2, duration)
        next_t = time.time()
        frames = 0
        while True:
            try:
                # 先等到名义帧时刻（分片睡，可随时停），再解码写屏
                now = time.time()
                while now < next_t and _RUNNING:
                    time.sleep(min(0.1, max(0.001, next_t - now)))
                    now = time.time()
                if not _RUNNING:
                    break
                frame = gif.copy().convert("RGB")
                scr.put(fit_img(frame, cw, ch, mode, bg), rot, invert)
                frames += 1
                d = gif.info.get("duration", 80) / 1000.0
                next_t += max(min_step, min(d, 0.5))
                gif.seek(gif.tell() + 1)
            except EOFError:
                if time.time() >= end:
                    break
                gif.seek(0)
            if time.time() >= end or frames > 2000:
                break
    except Exception:
        return False
    return True


VIDEO_CODEC_CACHE = {}


def probe_video(path):
    """ffprobe 探测 (codec_name, has_video)，带缓存（键含 mtime/size，同名
    文件被替换后不残留旧结论）。
    has_video：True=有视频流 / False=明确无视频流（纯音频/图片，目录轮播跳过）/
    None=探测不出（交由解码尝试兜底）。
    真机实测两条铁律：①不能用 -select_streams v:0——纯音频文件该形式输出
    为空 rc=0，与"探测不出"无法区分，跳过逻辑会失效；须列出全部流再找
    video 行。②本机 ffmpeg-mpp 对个别编码（如 mpeg4）ffprobe 会在初始化
    rkmpp 解码器时连带失败退出——退回 `ffmpeg -i` 的流信息行（在解码器
    初始化之前打印，仍能拿到编码名），拿不到才真返回 None。"""
    try:
        st = os.stat(path)
        ckey = (path, st.st_mtime, st.st_size)
    except OSError:
        return None, None
    if ckey in VIDEO_CODEC_CACHE:
        return VIDEO_CODEC_CACHE[ckey]
    codec, has = None, None
    try:
        r = subprocess.run(
            ["/usr/bin/ffprobe", "-v", "quiet",
             "-show_entries", "stream=codec_type,codec_name", "-of", "csv=p=0", path],
            capture_output=True, timeout=8)
        if r.returncode == 0:
            out = r.stdout.decode("utf-8", "replace").strip()
            for line in out.splitlines():
                # csv 字段顺序随 ffprobe 版本/请求顺序而变（本机实测输出
                # "h264,video"），按值识别而非按位解析
                parts = [p.strip() for p in line.strip().split(",")]
                if "video" in parts:
                    codec = next((p for p in parts if p and p != "video"), None)
                    has = True
                    break
            else:
                has = False if out else None
        else:
            # ffprobe 失败时 stderr 只含报错；用 ffmpeg -i 的流信息行兜底识别
            r2 = subprocess.run(["/usr/bin/ffmpeg", "-i", path],
                                capture_output=True, timeout=8)
            m = re.search(r"Video:\s*([A-Za-z0-9_]+)",
                          r2.stderr.decode("utf-8", "replace"))
            if m:
                codec, has = m.group(1).lower(), True
    except Exception:
        pass
    if len(VIDEO_CODEC_CACHE) >= 64:
        VIDEO_CODEC_CACHE.clear()
    VIDEO_CODEC_CACHE[ckey] = (codec, has)
    return codec, has


# ffmpeg-mpp 携带的 rkmpp 硬解族；能否真走 VPU 由运行时决定，失败自动回退同名软解
RKMPP_CODECS = ("h264", "hevc", "vp9", "vp8", "mjpeg", "mpeg4", "mpeg2",
                "mpeg1video", "h263", "av1")


def _video_pick(page):
    """视频页候选文件：目录/文件（不按扩展名过滤），ffprobe 可用时跳过
    「明确无视频流」的文件（图片/音频/字幕混目录）；探测工具失败的文件
    不跳过（交由解码尝试兜底）。全跳过返回 None。"""
    files = _media_files(page.get("video_path", ""))
    if not files or not shutil.which("ffmpeg"):
        return None
    if not hasattr(_video_pick, "idx"):
        _video_pick.idx = 0
    have_probe = shutil.which("ffprobe")
    for _ in range(len(files)):
        cand = files[_video_pick.idx % len(files)]
        _video_pick.idx += 1
        if have_probe and probe_video(cand)[1] is False:
            continue
        return cand
    return None


def media_vf_chain(w, h, rotate, invert, mode="cover", hw=False,
                   pixfmt="rgb565le", speed=None, fps=None):
    """媒体视频滤镜链（播放与预览共用）：显示比例/旋转/反色/倍速/帧率。
    hw=硬解路径必须把 hwdownload,format=nv12 放在链首（含 transpose 之前）——
    rkmpp 输出 DRM 帧，任何 sw 滤镜（含 transpose）都不能直接吃，先落回 nv12
    再变换；真机实测 transpose 在 hwdownload 前会滤镜图直接报错（三种比例全炸，
    BG141 起的潜伏 bug，本轮回修）。contain 的留边统一黑色（播放器惯例，
    图片/GIF 的 contain 才衬页面底色）。"""
    vf = []
    if hw:
        vf.append("hwdownload,format=nv12")
    # 旋转方向锚定 PIL 逆时针语义（Pillow 文档：Image.rotate 正角=逆时针）：
    # 90°→transpose=2(cclock)、270°→transpose=1(clock)、180°→cclock 两次
    # （ffmpeg-filters 官方文档的 transpose 取值表）。BG141 旧代码 90° 用
    # transpose=1 与图片族方向相反，且 180° 完全未实现——本轮回修
    if rotate == 90:
        vf.append("transpose=2")
    elif rotate == 270:
        vf.append("transpose=1")
    elif rotate == 180:
        vf.append("transpose=2,transpose=2")
    if mode == "stretch":
        # 拉伸铺满：忽略宽高比（BG141 之前的旧版行为）
        vf.append("scale=%d:%d" % (w, h))
    elif mode == "contain":
        # 等比完整显示：缩小放进屏幕，黑边补齐（pad 尺寸恒定输出无黑场；
        # pad 对 nv12 实测可用，滤镜框架自动协商中间格式）
        vf.append("scale=%d:%d:force_original_aspect_ratio=decrease" % (w, h))
        vf.append("pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black" % (w, h))
    else:
        # cover：与图片/GIF 的 fit_img 同语义：等比缩放盖满屏幕（宽高比宁可超出
        # 不可不足），再居中裁切到精确屏寸——非 1.86:1 视频不再拉伸变形
        vf.append("scale=%d:%d:force_original_aspect_ratio=increase" % (w, h))
        vf.append("crop=%d:%d" % (w, h))
    vf.append("format=%s" % pixfmt)
    if invert:
        vf.append("negate")
    if speed is not None and speed != 1.0:
        # 倍速：压缩时间戳 → 每显示帧采样更靠后的内容（无重复无漏拍的流畅快放）
        vf.append("setpts=PTS/%s" % ("%.4g" % speed))
    if fps:
        # 供给 25fps 略超面板节拍(video_fps)：缓冲队列恒有新帧可取，供给端不欠载。
        # 另一层作用：rkmpp 解码输出带异常（巨负）PTS，fps 滤镜按帧序重建时间戳，
        # 不带它时 -t/-ss 类时间裁剪会一帧不剩（真机实测）
        vf.append("fps=25")
    return ",".join(vf)


def video_first_frame(path, w, h, rotate=0, invert=False, mode="cover"):
    """视频首帧离屏渲染（预览用）：与 page_video 同一回退链（rkmpp 硬解 →
    同名软解 → 原生自动——本机 ffmpeg-mpp 对 h264 等默认即选 rkmpp，原生自动
    路径缺 hwdownload 会让滤镜图直接报错，必须逐档带 hw 标志构造链）。
    优先 -ss 1 取第 1 秒画面（首帧常为纯黑场），拿不到再回退第 0 帧。"""
    if not shutil.which("ffmpeg"):
        return None
    codec = probe_video(path)[0]
    attempts = []
    if codec and codec in RKMPP_CODECS:
        attempts.append((codec + "_rkmpp", True))
    if codec:
        attempts.append((codec, False))
    attempts.append((None, False))
    for decoder, hw in attempts:
        vf = media_vf_chain(w, h, rotate, invert, mode, hw=hw, pixfmt="rgb24")
        for ss in (1.0, 0.0):
            cmd = ["/usr/bin/ffmpeg", "-loglevel", "quiet"]
            if decoder:
                cmd += ["-c:v", decoder]
            if ss > 0:
                cmd += ["-ss", str(ss)]
            cmd += ["-an", "-i", path, "-vf", vf, "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
            try:
                out = subprocess.check_output(cmd, timeout=25)
            except Exception:
                continue
            if len(out) >= w * h * 3:
                return Image.frombytes("RGB", (w, h), out[:w * h * 3])
    return None


def page_video(scr, page, rotate, invert, duration):
    """视频页：ffprobe 探测编码 → 对应 rkmpp 硬解优先 → 同名软解兜底 → 原生自动兜底。
    ffmpeg 输出到管道，逐帧写入 mmap（fbtft defio 只认 mmap 脏页）。"""
    path = _video_pick(page)
    if not path:
        return False

    codec = probe_video(path)[0]
    attempts = []
    if codec and codec in RKMPP_CODECS:
        attempts.append(codec + "_rkmpp")
    if codec:
        attempts.append(codec)      # 同名软解码器
    attempts.append(None)           # 原生自动

    frame_bytes = scr.w * scr.h * 2
    # 视频页以"自然播完"为主；duration 仅作超长兜底（interval*60s，≥5 分钟）
    end = time.time() + max(300, duration * 6)

    try:
        speed = max(0.5, min(4.0, float(uci_get("main.video_speed", "1") or 1)))
    except ValueError:
        speed = 1.0
    # 写屏节拍：略低于面板 SPI 刷新上限（~20fps）。解码供给 25fps 经帧缓冲后按此匀速消费
    try:
        fps = max(10.0, min(25.0, float(uci_get("main.video_fps", "20") or 20)))
    except ValueError:
        fps = 20.0

    def attempt(decoder):
        hw = decoder is not None and decoder.endswith("_rkmpp")
        rot = media_rotate(page, rotate)
        cmd = ["/usr/bin/ffmpeg", "-re", "-loglevel", "quiet"]  # -re 是唯一实时 pacing 源（fps 滤波只重采样时间戳不控速）
        if decoder:
            cmd += ["-c:v", decoder]
        cmd += ["-an", "-i", path,
                "-vf", media_vf_chain(scr.w, scr.h, rot, invert,
                                      norm_fit(page.get("fit_mode")),
                                      hw=hw, speed=speed, fps=True),
                "-f", "rawvideo", "-pix_fmt", "rgb565le", "-"]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=frame_bytes)
        except Exception:
            return False
        _CHILD_PROCS.append(p)

        # 帧缓冲：读写双线程 + 有界队列，解耦两套时钟——
        #   供给侧：ffmpeg -re 25fps 到达（解码输出有突发抖动）
        #   消费侧：面板 SPI 刷新上限 ~20fps（video_fps 节拍匀速写出）
        # 队列满丢最旧（延迟有界）；欠载时保持上一帧等待；写出恒为完整新帧，
        # defio 每拍刷的恰是一帧，消除随机合并/漏刷造成的卡顿。
        cap = 4
        cond = threading.Condition()
        q, qeof = [], [False]

        def reader():
            while True:
                frame = p.stdout.read(frame_bytes)
                if not frame or len(frame) < frame_bytes:
                    break
                with cond:
                    if len(q) >= cap:
                        q.pop(0)        # 供给>消费：丢最旧帧，防延迟累积
                    q.append(frame)
                    cond.notify()
            with cond:
                qeof[0] = True
                cond.notify()

        rt = threading.Thread(target=reader, daemon=True)
        rt.start()

        period = 1.0 / fps
        frames = 0
        start_deadline = time.monotonic() + 0.5   # 仅起播预滚用：0.5s 攒不出帧=解码失败走回退
        next_t = 0.0
        while _RUNNING and time.time() < end:
            with cond:
                need = 1 if frames else min(2, cap)   # 首拍前先攒 2 帧（吸收起播突发）
                while _RUNNING and not qeof[0] and len(q) < need:
                    if frames == 0 and time.monotonic() > start_deadline:
                        break
                    cond.wait(0.1)
                if not q:
                    if qeof[0] or (frames == 0 and time.monotonic() > start_deadline):
                        break
                    continue
                frame = q.pop(0)
            scr.mm.seek(scr.off)     # 可见区窗口（x0=0 → 帧字节连续）
            scr.mm.write(frame)
            frames += 1
            if frames == 1:
                next_t = time.monotonic()   # 首帧落笔=节拍零点
            next_t += period
            lag = next_t - time.monotonic()
            if lag > 0:
                time.sleep(lag)
            elif lag < -period:
                next_t = time.monotonic()   # 欠一拍以上（长欠载后）：重置节拍，不追赶连写
        rt.join(1)
        p.terminate()
        try:
            p.wait(timeout=3)
        except Exception:
            p.kill()
        try:
            _CHILD_PROCS.remove(p)
        except ValueError:
            pass
        return frames > 0   # 零帧=该解码器失败，继续回退下一档

    gov = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
    old_gov = ""
    try:
        if os.path.exists(gov):
            old_gov = open(gov).read().strip()
            if old_gov != "performance":
                open(gov, "w").write("performance")
    except Exception:
        old_gov = ""
    try:
        for decoder in attempts:
            if attempt(decoder):
                return True
        return False
    finally:
        try:
            if old_gov and os.path.exists(gov):
                open(gov, "w").write(old_gov)
        except Exception:
            pass


def page_code(scr, page, rotate, invert, bg, fonts):
    code = page.get("code_text", "")
    if not code.strip():
        return False
    cw, ch = canvas_dims(scr, rotate)
    img = Image.new("RGB", (cw, ch), bg)
    d = ImageDraw.Draw(img)
    env = {
        "img": img, "d": d, "w": cw, "h": ch,
        "f1": fonts["big"], "f2": fonts["title"], "f3": fonts["lbl"], "f4": fonts["val"],
        "collect": collect, "ITEM_NAMES": ITEM_NAMES,
        "lunar_str": lunar_str, "time": time, "os": os,
    }

    def draw_err(msg):
        d.text((8, 8), "代码错误:", font=fonts["title"], fill=(255, 60, 60))
        # 先按换行拆再 26 字符折行，最多 6 行（单行 220 字符会溢出画布）
        chunks = []
        for ln in msg[:400].splitlines() or [""]:
            chunks += [ln[i:i + 26] for i in range(0, len(ln), 26)] or [""]
        for i, chunk in enumerate(chunks[:6]):
            d.text((8, 34 + i * 22), chunk + ("…" if i == 5 and len(chunks) > 6 else ""),
                   font=fonts["lbl"], fill=(255, 120, 120))

    # 死循环防护：墙钟 10s 上限（线程无法强杀，settrace 是唯一能打断 exec 内
    # 死循环的手段）。每 256 个 trace 事件查一次表——time.sleep 型循环每迭代
    # 仅 2 事件，256 一查≈1.3s 内必查到；查表开销可忽略（常规绘制远早于限值）
    cnt = [0]
    deadline = time.time() + 10

    def _guard(frame, event, arg):
        cnt[0] += 1
        if cnt[0] >= 256:
            cnt[0] = 0
            if time.time() > deadline:
                raise RuntimeError("执行超时 >10s（疑似死循环），已中止")
        return _guard

    try:
        sys.settrace(_guard)
        exec(compile(code, "<xgpscreen-code>", "exec"), env)
    except KeyboardInterrupt:
        raise                     # procd 停止信号，正常退出路径
    except BaseException as e:    # 含 SystemExit：sys.exit() 不许杀掉整个屏幕服务
        draw_err("%s: %s" % (type(e).__name__, e))
    finally:
        sys.settrace(None)
    scr.put(img, rotate, invert)
    return True


def canvas_dims(scr, rotate):
    """rotate 90/270 时画布换轴（竖屏绘制），put() 旋转后回到 fb 物理尺寸。"""
    return (scr.h, scr.w) if rotate in (90, 270) else (scr.w, scr.h)


# 内容区起始 y：分割线 y=27 下方留 13px 气口（渲染与预览切帧共用）
CONTENT_TOP = 40

# custom 折行缓存：折行只依赖 (文本, 宽度)，进程内不变。巨文本（100KB）
# 每帧重折 0.9s 是纯浪费——draw_items 每 5s/走秒每 1s 都会经 layout 再算一遍
_CUSTOM_WRAP_CACHE = {}


def wrap_custom_lines(d, txt, maxw):
    """custom 文本按像素宽折行（CJK/ASCII 混排逐字符贪心）。
    渲染与布局测量共用同一实现（结果缓存），保证折行结果/分帧一致。
    返回缓存列表——调用方不得原地修改（需要裁剪请切片拷贝）。"""
    key = (txt, maxw)
    hit = _CUSTOM_WRAP_CACHE.get(key)
    if hit is not None:
        return hit
    lines = []
    for raw in txt.splitlines():
        cur = ""
        for ch in raw:
            if cur and d.textlength(cur + ch, font=FONTS["val"]) > maxw:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    lines = lines or [""]
    if len(_CUSTOM_WRAP_CACHE) >= 8:      # 不同文本种类很少，防极端撑内存
        _CUSTOM_WRAP_CACHE.clear()
    _CUSTOM_WRAP_CACHE[key] = lines
    return lines


def item_render_h(item, d, W, page, vals):
    """条目精确渲染高度——与 draw_items 渲染推进完全同源（单一事实源）：
    布局切帧用的高度即渲染时 y 的推进量，杜绝"估算<实画"导致的溢出/挤帧。
    vals 为 collect 预取缓存（普通条目布局与渲染共用，避免重复系统调用）。
    行距设计：单行文本 40 / 单行+bar 58（bar 到 y+42）/ 两行文本 60
    （val 到 y+46）/ 两行+bar 68（bar 下移至 y+48..56）/ custom 按完整
    折行行数（行×26+10，多行自然独立成帧）。"""
    if item == "clock":
        return 70
    if item in WIDGETS:
        return WIDGET_HEIGHT[item] + 8
    if item == "countdown":
        return 116
    if item == "lunar":
        return 146
    if item == "custom":
        # 按完整折行行数估高（行数×26 + 10px 底部余量，与渲染
        # nlines=(H-y-10)//26 公式对齐）：多行 custom 自然超预算推到独立
        # 子帧完整展示；曾按 1 行(26)估导致 custom 被前序条目挤进帧底
        # 只剩一行空间（独立分帧丢失+内容截断）
        lines = wrap_custom_lines(d, page.get("custom", ""), W - 20)
        return len(lines) * 26 + 10
    val = vals.get(item)
    if val is None:
        # collect 失败渲染同样跳过（不画不推进）
        return 0
    lbl = ITEM_NAMES.get(item, item) + ":"
    ratio = bar_ratio(item, val)
    two_line = d.textlength(lbl, font=FONTS["lbl"]) + \
        d.textlength(val, font=FONTS["val"]) + 50 > W - 20
    if ratio is not None:
        return 68 if two_line else 58
    return 60 if two_line else 40


def custom_chunk_lines(H):
    """custom 每子帧行数：整帧可用高（CONTENT_TOP 起、去 8px 底隙 10px 余量）
    按行高 26 折算。布局切块与渲染取块共用，保证块边界一致。"""
    return max(1, (H - CONTENT_TOP - 8 - 10) // 26)


def layout_page(page, W, H, fonts):
    """页面布局（渲染与预览共用）：预取 val、精确测高、按高度切子帧。
    custom 按帧容量切块成 custom#i（每块独立子帧轮播）——超长文本逐帧
    翻页全部行可见，不再"独立成帧却只显示前几行+…"。返回 (subs, vals, heights)。"""
    global FONTS
    FONTS = fonts
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    vals = {}
    for it in page["items"]:
        if it in vals or it == "clock" or it in WIDGETS or \
           it in ("countdown", "lunar", "custom"):
            continue
        vals[it] = collect(it)
    budget = H - CONTENT_TOP - 8
    expanded = []      # (子帧条目名, custom 块行列表；非 custom 为 None)
    for it in page["items"]:
        if it == "custom":
            lines = wrap_custom_lines(probe, page.get("custom", ""), W - 20)
            k = custom_chunk_lines(H)
            for ci in range(0, max(1, len(lines)), k):
                expanded.append(("custom#%d" % (ci // k), lines[ci:ci + k]))
        else:
            expanded.append((it, None))
    heights = {}
    for key, chunk in expanded:
        heights[key] = (len(chunk) * 26 + 10) if chunk is not None \
            else item_render_h(key, probe, W, page, vals)
    subs, cur, used = [], [], 0
    for key, _ in expanded:
        h = heights[key]
        if cur and used + h > budget:
            subs.append(cur)
            cur, used = [], 0
        cur.append(key)
        used += h
    if cur:
        subs.append(cur)
    return subs or [[]], vals, heights


def draw_items(scr, page, cfg, bg, fg, tc, fonts, sub_idx=None):
    """普通条目页：条目超高自动分页（子帧轮播，标题角标 n/m）。
    sub_idx：指定渲染某子帧（预览用）；None=按轮播状态推进。
    布局与渲染共用 layout_page 的精确高度（单一事实源）：渲染 y 推进=布局
    测高，不存在估算≠实画导致的溢出或"下帧内容挤进本帧"。"""
    global FONTS
    FONTS = fonts
    rd = int(cfg.get("rotate", "0") or 0)
    W, H = canvas_dims(scr, rd)

    subs, vals, heights = layout_page(page, W, H, fonts)
    key = page["title"]
    if sub_idx is None:
        # 先画当前子帧、画完再后移。曾为先加后画：整页槽从状态2起播
        # （2,3,1），下一页被观感错位成"插在状态1和状态2之间"
        PAGE_STATE[key] = PAGE_STATE.get(key, 0) % len(subs)
    else:
        PAGE_STATE[key] = min(sub_idx, len(subs) - 1)
    items = subs[PAGE_STATE[key]]

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    # 无色块标题：仅顶部一行小字（show_title 留空则完全无标题）
    st = cfg.get("show_title", "XGP-V3")
    if st:
        d.text((12, 2), st, font=fonts["lbl"], fill=tc)
    badge = page["title"] + (" %d/%d" % (PAGE_STATE[key] + 1, len(subs)) if len(subs) > 1 else "")
    d.text((W - 12, 2), badge, font=fonts["lbl"], fill=tc, anchor="ra")
    # 标题栏分隔细线：内缩留边（避免满幅贴边像扫描线）；线上 7px/线下 6px 气口均衡
    d.line((8, 27, W - 8, 27), fill=dim(fg, 0.18))

    y = CONTENT_TOP
    clock_done = False
    for item in items:
        if y > H - 26:
            break
        if item == "clock" and not clock_done:
            ts = time.strftime("%H:%M")
            draw_icon(d, "clock", int(W // 2 - d.textlength(ts, font=fonts["big"]) / 2 - 30),
                      y + 28, dim(fg))
            d.text((W // 2, y + 8), ts, font=fonts["big"],
                   fill=fg, anchor="ma")
            y += 70
            clock_done = True
            continue
        if item in WIDGETS:
            wh = min(WIDGET_HEIGHT[item], H - y - 6)
            if wh >= 40:
                WIDGETS[item](d, 10, y, W - 20, wh, fg)
                y += wh + 8
            continue
        if item == "countdown":
            wh = min(108, H - y - 6)
            if wh >= 60:
                widget_countdown(d, 10, y, W - 20, wh, fg, page)
                y += wh + 8
            continue
        if item == "lunar":
            wh = min(146, H - y - 6)
            if wh >= 120:
                widget_calendar(d, 10, y, W - 20, wh, fg, tc, bg)
                y += wh + 8
            continue
        if item.startswith("custom#") or item == "custom":
            # 分帧后的 custom 块只画本块行（块边界与 layout 切块一致）；
            # 裸 "custom"（异常路径兜底）按剩余可视行数截断加 …
            txt = page.get("custom", "")
            maxw = W - 20
            lines = wrap_custom_lines(d, txt, maxw)
            avail = max(1, (H - y - 10) // 26)
            if item.startswith("custom#"):
                k = custom_chunk_lines(H)
                show = lines[int(item[7:]) * k:][:min(k, avail)]
            else:
                show = lines[:avail]
                if len(lines) > avail and show:
                    last = show[-1]
                    while last and d.textlength(last + "…", font=fonts["val"]) > maxw:
                        last = last[:-1]
                    show[-1] = last + "…"
            for line in show:
                d.text((10, y), line, font=fonts["val"], fill=fg)
                y += 26
            continue
        val = vals.get(item)
        if val is None:
            continue
        lbl = ITEM_NAMES.get(item, item) + ":"
        draw_icon(d, item, 10, y + 1, fg)
        d.text((30, y), lbl, font=fonts["lbl"], fill=dim(fg))
        ratio = bar_ratio(item, val)
        # 统一两列样式：图标+标签左、数值右对齐；放不下自动回退上下两行
        two_line = d.textlength(lbl, font=fonts["lbl"]) + \
            d.textlength(val, font=fonts["val"]) + 50 > W - 20
        if two_line:
            # 两行布局：标签 y、数值 y+26（标签文字底约 y+16 与数值顶留 10px 行隙，
            # 原始 y+18 约 2px / 首修 y+22 约 6px 观感仍偏紧）
            d.text((30, y + 26), val, font=fonts["val"], fill=fg)
            bar_y = y + 48
        else:
            d.text((W - 12, y), val, font=fonts["val"], fill=fg, anchor="ra")
            bar_y = y + 34
        if ratio is not None:
            bw2 = W - 20
            d.rectangle((10, bar_y, 10 + bw2, bar_y + 8), fill=dim(fg, 0.15))
            d.rectangle((10, bar_y,
                         10 + int(bw2 * max(0.0, min(1.0, ratio))), bar_y + 8),
                        fill=bar_color(ratio, fg))
        # 行进=布局测高（item_render_h 同公式）：单行 40/两行 58/带 bar 58/66
        y += heights[item]
    scr.put(img, rd, cfg.get("invert", "0") == "1")
    # 统一不变量：函数返回后 PAGE_STATE 恒为"下一帧"索引（sub_idx 走秒重绘若不后移，
    # 会把 state 改写回"刚画的帧"，主循环推进绘制随之原地踏步/倒退）
    PAGE_STATE[key] = (PAGE_STATE[key] + 1) % len(subs)
    return len(subs)


PAGE_STATE = {}


def read_cfg_main():
    keys = ("rotate", "invert", "interval", "bg_color", "fg_color",
            "title_color", "show_title", "net_iface", "video_speed", "video_fps")
    return {k: uci_get("main." + k, "") for k in keys}


# ---------------- 页面预览（LuCI 缩略图，不写 fb）----------------

class PreviewScreen:
    """离屏 Screen：与 Screen 相同的可见区几何/旋转/反色/打包，只留存图像。"""

    def __init__(self):
        fbw, fbh = fb_size()
        self.w, self.h = fbw - VIS_X0, VIS_H
        self.img = None

    def put(self, img, rotate=0, invert=False):
        if rotate:
            img = img.rotate(int(rotate), expand=True)
        if invert:
            img = ImageOps.invert(img.convert("RGB"))
        self.img = img
        return True


def _preview_placeholder(w, h, bg, icon, text):
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    try:
        d.text((w // 2, h // 2 - 18), icon, font=font(42), fill=(190, 190, 190), anchor="mm")
        d.text((w // 2, h // 2 + 26), (text or "")[:26], font=font(15), fill=(150, 150, 150), anchor="mm")
    except TypeError:   # 老 PIL 无 anchor
        d.text((12, h // 2), icon + " " + (text or "")[:20], font=font(18), fill=(190, 190, 190))
    return img


def run_preview(section):
    """--preview <section>：离屏渲染该页面，PNG 写 stdout（供 LuCI 缩略图）。"""
    if not re.match(r"^[A-Za-z0-9_]+$", section or ""):
        sys.exit(2)
    page = None
    for p in uci_pages(True):
        if p.get("section") == section:
            page = p
            break
    if not page:
        sys.exit(3)

    cfg = read_cfg_main()
    fonts = {
        "big": ImageFont.truetype(FONT, 44),
        "title": ImageFont.truetype(FONT, 24),
        "lbl": ImageFont.truetype(FONT, 18),
        "val": ImageFont.truetype(FONT, 20),
    }
    # 网速类组件预览需要采样历史：起双采样器等 2.5s 攒曲线
    global NETMON, NETMON_LAN
    if any(i in ("netgraph", "lanrate") for i in page["items"]):
        NETMON = NetMon()
        NETMON.start()
        NETMON_LAN = NetMon(fixed="br-lan")
        NETMON_LAN.start()
        time.sleep(2.5)
    scr = PreviewScreen()
    rotate = int(cfg.get("rotate", "0") or 0)
    invert = cfg.get("invert", "0") == "1"
    bg = hex2rgb(cfg.get("bg_color", "#000000"))
    fg = hex2rgb(cfg.get("fg_color", "#00FF88"))
    tc = hex2rgb(cfg.get("title_color", "#FFAA00"))
    kind = page["items"][0] if page["items"] else ""

    if kind == "image":
        path = page.get("image_path", "")
        img = None
        for f in _media_files(path):
            try:
                im = Image.open(f)
                if im.format == "JPEG":
                    im.draft("RGB", (scr.w, scr.h))
                img = im.convert("RGB")
                break
            except Exception:
                continue       # 与实机同策略：非图片文件跳过
        if img is not None:
            rot = media_rotate(page, rotate)
            cw, ch = canvas_dims(scr, rot)   # 与实机 page_image 同构（90/270 换轴）
            scr.put(fit_img(img, cw, ch, page.get("fit_mode", "cover"), bg),
                    rot, invert)
        if scr.img is None:
            scr.img = _preview_placeholder(scr.w, scr.h, bg, "🖼", "无图片: " + (path or "未配置"))
    elif kind == "gif":
        path = page.get("gif_path", "")
        try:
            gif = Image.open(path)
            frame = gif.convert("RGB")
            rot = media_rotate(page, rotate)
            cw, ch = canvas_dims(scr, rot)
            scr.put(fit_img(frame, cw, ch, page.get("fit_mode", "cover"), bg),
                    rot, invert)
        except Exception:
            scr.img = _preview_placeholder(scr.w, scr.h, bg, "GIF", os.path.basename(path or "未配置"))
    elif kind == "video":
        # 真实首帧（与实机同一 vf 链：显示比例/旋转/反色一致），失败才占位；
        # 该文件解不出首帧时换下一个候选（与实机目录轮播跳过语义一致）
        frame = None
        have_probe = shutil.which("ffprobe")
        vrot = media_rotate(page, rotate)
        for f in _media_files(page.get("video_path", "")):
            if have_probe and probe_video(f)[1] is False:
                continue
            frame = video_first_frame(f, scr.w, scr.h, vrot, invert,
                                      page.get("fit_mode", "cover"))
            if frame is not None:
                break
        if frame is not None:
            scr.img = frame
        else:
            scr.img = _preview_placeholder(scr.w, scr.h, bg, "▶ 视频",
                                           os.path.basename(page.get("video_path", "") or "未配置"))
    elif kind == "code":
        # 预览直接离屏执行用户代码（与实机同一 page_code：同样的防死循环/防 exit
        # 防护与错误上屏）——保存前即可所见即所得；空代码显示占位
        if not page_code(scr, page, rotate, invert, bg, fonts):
            scr.img = _preview_placeholder(scr.w, scr.h, bg, "{}", "代码页（空代码）")
    else:
        # 信息页：渲染全部轮播子帧并纵向拼接（预览=该页所有状态的完整视图）。
        # 切帧与渲染共用 layout_page（曾用 top=28 旧值导致预览帧划分与真机轮播不一致）
        rd = int(cfg.get("rotate", "0") or 0)
        pw, ph = canvas_dims(scr, rd)
        subs, _, _ = layout_page(page, pw, ph, fonts)
        frames = []
        for i in range(len(subs)):
            sub_scr = PreviewScreen()
            draw_items(sub_scr, page, cfg, bg, fg, tc, fonts, sub_idx=i)
            if sub_scr.img is not None:
                frames.append(sub_scr.img)
        if frames:
            # custom 分帧后子帧数可到数百（100KB 文本≈825 帧），全量拼接
            # 会生成百 MB 级 PNG——预览封顶 60 帧，超出加提示条
            if len(frames) > 60:
                cap = Image.new("RGB", (frames[0].width, 40), (64, 64, 64))
                cd = ImageDraw.Draw(cap)
                cd.text((8, 10), "共 %d 子帧，预览仅显示前 60 帧" % len(frames),
                        font=fonts["lbl"], fill=(255, 200, 80))
                frames = frames[:60] + [cap]
            sep = 6
            total_h = sum(f.height for f in frames) + sep * (len(frames) - 1)
            comp = Image.new("RGB", (frames[0].width, total_h), (64, 64, 64))
            yy = 0
            for f in frames:
                comp.paste(f, (0, yy))
                yy += f.height + sep
            scr.img = comp

    if scr.img is None:
        scr.img = _preview_placeholder(scr.w, scr.h, bg, "?", page.get("title", ""))
    scr.img.save(sys.stdout.buffer, "PNG")


def _cfg_mtime():
    try:
        return os.path.getmtime("/etc/config/xgpscreen")
    except Exception:
        return 0


def main():
    global NETMON, NETMON_LAN
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    if not os.path.exists(FB):
        print("no fb0, exit")
        time.sleep(5)
        sys.exit(1)

    fonts = {
        "big": ImageFont.truetype(FONT, 44),
        "title": ImageFont.truetype(FONT, 24),
        "lbl": ImageFont.truetype(FONT, 18),
        "val": ImageFont.truetype(FONT, 20),
    }
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)
    NETMON = NetMon()
    NETMON.start()
    NETMON_LAN = NetMon(fixed="br-lan")
    NETMON_LAN.start()
    fb_fd = os.open(FB, os.O_RDWR)
    scr = Screen(fb_fd)
    # 启动先整屏清一次：可见区窗口外的历史残留（测试图/旧帧）会永久可见
    try:
        scr.mm.seek(0)
        scr.mm.write(b"\x00" * (scr.fb_w * scr.fb_h * 2))
    except Exception:
        pass
    pages = uci_pages()
    cfg = read_cfg_main()

    while _RUNNING:
        if uci_get("main.enabled", "1") != "1":
            # 禁用：黑屏释放内容并退出（procd 不再 respawn？——respawn 会拉起，
            # 但主循环再次读 enabled 仍退出 → 平稳空转一次即退，由用户显式 start 恢复）
            try:
                scr.put(Image.new("RGB", (scr.w, scr.h), (0, 0, 0)))
            except Exception:
                pass
            print("disabled, exiting (screen cleared)")
            return
        try:
            rotate = int(cfg.get("rotate", "0") or 0)
            invert = cfg.get("invert", "0") == "1"
            bg = hex2rgb(cfg.get("bg_color", "#000000"))
            fg = hex2rgb(cfg.get("fg_color", "#00FF88"))
            tc = hex2rgb(cfg.get("title_color", "#FFAA00"))
            try:
                interval = max(1, int(cfg.get("interval", "5") or 5))
            except ValueError:
                interval = 5

            # 槽位边界热重载：配置 mtime 变化（拖拽排序/编辑/增删页）后，
            # 下一槽位即采用新顺序——不必等整轮播完（用户拖拽后屏上迟迟不变曾像"没生效"）
            cfg_mtime = _cfg_mtime()
            pi = 0
            while pi < len(pages):
                page = pages[pi]
                pi += 1
                if not _RUNNING or not page["items"]:
                    continue
                if _cfg_mtime() != cfg_mtime:
                    pages = uci_pages()
                    cfg = read_cfg_main()
                    cfg_mtime = _cfg_mtime()
                    rotate = int(cfg.get("rotate", "0") or 0)
                    invert = cfg.get("invert", "0") == "1"
                    bg = hex2rgb(cfg.get("bg_color", "#000000"))
                    fg = hex2rgb(cfg.get("fg_color", "#00FF88"))
                    tc = hex2rgb(cfg.get("title_color", "#FFAA00"))
                    interval = max(1, int(cfg.get("interval", "5") or 5))
                    pi = 0
                    continue
                kind = page["items"][0]
                media_failed = False
                if kind == "image":
                    if page_image(scr, page, rotate, invert, bg):
                        for _ in range(interval):
                            if not _RUNNING:
                                break
                            time.sleep(1)
                    else:
                        media_failed = True
                elif kind == "gif":
                    if not page_gif(scr, page, rotate, invert, interval * 3, bg):
                        media_failed = True
                elif kind == "video":
                    if not page_video(scr, page, rotate, invert, interval * 10):
                        media_failed = True
                elif kind == "code":
                    if page_code(scr, page, rotate, invert, bg, fonts):
                        for _ in range(interval):
                            if not _RUNNING:
                                break
                            time.sleep(1)
                    else:
                        media_failed = True
                else:
                    # 页槽内轮播该页全部子帧（每子帧停 interval 秒），轮完再切下一页；
                    # 含倒计时的页每秒重绘走秒：sub_idx=(state-1) 恒取"当前展示帧"
                    # （draw_items 尾部统一后移保证 state 不被重绘污染）
                    subs_n = max(1, draw_items(scr, page, cfg, bg, fg, tc, fonts) or 1)
                    live = "countdown" in page["items"]
                    for _s in range(subs_n):
                        for _ in range(interval):
                            if not _RUNNING:
                                break
                            time.sleep(1)
                            if live and _RUNNING:
                                draw_items(scr, page, cfg, bg, fg, tc, fonts,
                                           sub_idx=(PAGE_STATE.get(page["title"], 0) - 1) % subs_n)
                        if not _RUNNING or _s + 1 >= subs_n:
                            break
                        draw_items(scr, page, cfg, bg, fg, tc, fonts)
                if media_failed:
                    # 渲染失败（路径失效/空内容/无解码器）：退避一个 dwell 再切下一页。
                    # 此前该分支无任何 sleep——媒体 U 盘一拔，主循环空转 +
                    # uci show 子进程风暴打满 CPU
                    for _ in range(interval):
                        if not _RUNNING:
                            break
                        time.sleep(1)
            pages = uci_pages()
            cfg = read_cfg_main()
        except Exception as e:
            print("render error:", e)
            time.sleep(5)
            pages = uci_pages()
            cfg = read_cfg_main()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--preview":
        run_preview(sys.argv[2])
    else:
        main()
