#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPTV 直播源聚合脚本（TVBox / 各类 IPTV 播放器通用）

流程：
  1. 读取 sources.txt 中的公开 M3U 播放列表地址；
  2. 逐个抓取（单源超时 20 秒，失败跳过不影响其它源）；
  3. 解析 #EXTINF 频道名与播放地址（含 #EXTBURL 备用地址、
     以及一条 #EXTINF 下多条地址的写法）；
  4. 只保留 CCTV / 各省卫视 / CHC，过滤购物、成人、境外、广告、测试频道；
  5. 频道名归一化（兼容中英文源），去重，每频道最多保留 3 条不同地址；
  6. 生成 tv.m3u 与 tv.txt，打印统计。

只用 Python 标准库，无第三方依赖。幂等：相同输入必然产生相同输出。

用法：
  python3 iptv_update.py [--out-dir DIR] [--sources FILE]
"""

import argparse
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.request

FETCH_TIMEOUT = 20          # 单次抓取超时（秒）
FETCH_ATTEMPTS = 2          # urllib 抓取重试次数（应对出口代理冷连接）
USE_CURL_FALLBACK = True    # urllib 失败后是否尝试 curl（若系统有 curl）
MAX_URLS_PER_CHANNEL = 3    # 每个频道最多保留的地址数

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ----------------------------------------------------------------------------
# 黑名单：命中即丢弃（大小写不敏感）
# ----------------------------------------------------------------------------
BLOCK_KEYWORDS = [
    "购物", "shopping", "快乐购", "家有购物", "优购物", "风尚购物",
    "中视购物", "环球购物", "好享购物", "东方购物", "央广购物",
    "成人", "adult", "激情", "午夜", "写真", "私密",
    "测试", "试播", "试看", "demo", "sample", "备用", "备播",
    "维护", "即将上线", "招商", "彩条",
    "广告", "adshow",
    "cgtn",                      # 外语频道
    "中央电视塔", "电视指南",    # 摄像头/导视频道
    "hbo", "cnn", "bbc", "nhk", "tvb", "凤凰", "澳亚", "华娱",
    "discovery", "espn", "fox", "mtv", "animax", "cartoon",
    "arirang", "france 24", "al jazeera", "半岛",
    "星空", "香港卫视", "人间",       # 已停播 / 境外频道
    "上海卫视",                        # 并无此频道，系来源误标
]

# 中文别名 -> 规范名
CN_ALIASES = {
    "福建海峡卫视": "海峡卫视",
}

# 英文卫视名 -> 中文规范名（按特异性排序，先匹配长的）
EN_SATELLITES = [
    ("inner mongolia", "内蒙古卫视"),
    ("heilongjiang", "黑龙江卫视"),
    ("shaanxi", "陕西卫视"),
    ("zhejiang", "浙江卫视"),
    ("jiangsu", "江苏卫视"),
    ("jiangxi", "江西卫视"),
    ("greater bay", "大湾区卫视"),
    ("guangxi", "广西卫视"),
    ("guangdong", "广东卫视"),
    ("dongfang", "东方卫视"),
    ("oriental", "东方卫视"),
    ("dragon", "东方卫视"),
    ("shanghai", "东方卫视"),
    ("southeast", "东南卫视"),
    ("dongnan", "东南卫视"),
    ("beijing", "北京卫视"),
    ("tianjin", "天津卫视"),
    ("hebei", "河北卫视"),
    ("shanxi", "山西卫视"),
    ("liaoning", "辽宁卫视"),
    ("jilin", "吉林卫视"),
    ("anhui", "安徽卫视"),
    ("fujian", "东南卫视"),
    ("shandong", "山东卫视"),
    ("henan", "河南卫视"),
    ("hubei", "湖北卫视"),
    ("hunan", "湖南卫视"),
    ("hainan", "海南卫视"),
    ("chongqing", "重庆卫视"),
    ("sichuan", "四川卫视"),
    ("guizhou", "贵州卫视"),
    ("yunnan", "云南卫视"),
    ("tibet", "西藏卫视"),
    ("xizang", "西藏卫视"),
    ("gansu", "甘肃卫视"),
    ("qinghai", "青海卫视"),
    ("ningxia", "宁夏卫视"),
    ("xinjiang", "新疆卫视"),
    ("shenzhen", "深圳卫视"),
    ("yanbian", "延边卫视"),
    ("haixia", "海峡卫视"),
    ("strait", "海峡卫视"),
    ("bingtuan", "兵团卫视"),
    ("corps", "兵团卫视"),
    ("sansha", "三沙卫视"),
    ("xiamen", "厦门卫视"),
]

# 输出时的频道顺序（不在表中的频道排最后，按名称排序）
CHANNEL_ORDER = (
    [f"CCTV-{i}" for i in range(1, 18)]
    + ["CCTV-5+", "CCTV-4K", "CCTV-8K"]
    + ["CHC-家庭影院", "CHC-动作电影", "CHC-影迷电影"]
    + ["北京卫视", "天津卫视", "河北卫视", "山西卫视", "内蒙古卫视",
       "辽宁卫视", "吉林卫视", "黑龙江卫视", "东方卫视", "江苏卫视",
       "浙江卫视", "安徽卫视", "东南卫视", "江西卫视", "山东卫视",
       "河南卫视", "湖北卫视", "湖南卫视", "广东卫视", "广西卫视",
       "海南卫视", "重庆卫视", "四川卫视", "贵州卫视", "云南卫视",
       "西藏卫视", "陕西卫视", "甘肃卫视", "青海卫视", "宁夏卫视",
       "新疆卫视", "深圳卫视", "大湾区卫视", "海峡卫视", "延边卫视",
       "兵团卫视", "三沙卫视", "厦门卫视"]
)
_ORDER_INDEX = {name: i for i, name in enumerate(CHANNEL_ORDER)}

CCTV_DESCRIPTORS = (
    "综合|财经|综艺|中文国际|体育赛事|体育|电影|国防军事|电视剧|纪录|科教|"
    "戏曲|社会与法|新闻|少儿|音乐|奥林匹克|农业农村|高清|超清|标清|高网"
)


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def load_sources(path):
    """读取 sources.txt，返回 URL 列表（跳过空行与注释）。"""
    urls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def _fetch_urllib(url):
    """用标准库抓取，返回文本；失败抛异常。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        raw = resp.read()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _fetch_curl(url):
    """用系统 curl 抓取（urllib 兜底），返回文本；失败抛异常。"""
    out = subprocess.run(
        ["curl", "-sSL", "--max-time", str(FETCH_TIMEOUT),
         "-A", USER_AGENT, url],
        capture_output=True, timeout=FETCH_TIMEOUT + 5, check=True,
    )
    raw = out.stdout
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def fetch(url):
    """抓取单个源，返回文本；失败返回 None。

    先用 urllib 重试 FETCH_ATTEMPTS 次（冷连接偶发超时），
    仍失败且系统有 curl 时再用 curl 试一次。
    """
    last_err = None
    for _ in range(FETCH_ATTEMPTS):
        try:
            return _fetch_urllib(url)
        except Exception as e:  # noqa: BLE001
            last_err = e
    if USE_CURL_FALLBACK and shutil.which("curl"):
        try:
            return _fetch_curl(url)
        except Exception as e:  # noqa: BLE001
            last_err = e
    print(f"[跳过] {url} 抓取失败: {last_err}", file=sys.stderr)
    return None


def parse_m3u(text):
    """解析 M3U 文本，产出 (频道 raw 名, 播放地址) 元组。

    兼容写法：
      - 标准 #EXTINF + 地址
      - 一条 #EXTINF 下跟多条地址（122566 风格）
      - #EXTBURL: 备用地址（cs3306 风格）
    """
    entries = []
    pending_name = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            # 显示名在最后一个逗号之后；为空则退回 tvg-name 属性
            name = line.rsplit(",", 1)[-1].strip()
            if not name:
                m = re.search(r'tvg-name="([^"]*)"', line)
                name = m.group(1).strip() if m else ""
            pending_name = name or None
        elif line.startswith("#EXTBURL:"):
            if pending_name:
                entries.append((pending_name, line[len("#EXTBURL:"):].strip()))
        elif line.startswith("#"):
            continue
        elif line.startswith(("http://", "https://")):
            if pending_name:
                entries.append((pending_name, line))
    return entries


# ----------------------------------------------------------------------------
# 频道名归一化：返回规范名；不保留的频道返回 None
# ----------------------------------------------------------------------------
def normalize(name):
    if not name:
        return None
    n = unicodedata.normalize("NFKC", name).strip()
    if not n:
        return None
    low = n.lower()
    if any(k in low for k in BLOCK_KEYWORDS):
        return None

    # ---- CHC ----
    if "chc" in low:
        if "家庭" in n or "family" in low:
            return "CHC-家庭影院"
        if "动作" in n or "action" in low:
            return "CHC-动作电影"
        if "影迷" in n or "movie" in low:
            return "CHC-影迷电影"
        return None

    # ---- CCTV ----
    c = n.upper().replace(" ", "").replace("_", "-")
    c = re.sub(r"[\(\[（].*?[\)\]）]", "", c)          # 去 (1080p) / [HD] 等
    c = re.sub(rf"({CCTV_DESCRIPTORS})+$", "", c)       # 去 综合/财经/高清 等后缀
    c = c.replace("PLUS", "+")
    m = re.fullmatch(r"CCTV-?(\d{1,2})(\+?)", c)
    if m:
        return f"CCTV-{m.group(1)}{m.group(2)}"
    m = re.fullmatch(r"CCTV-?(4K|8K)", c)
    if m:
        return f"CCTV-{m.group(1)}"

    # ---- 中文卫视 ----
    if n.endswith("卫视") and len(n) <= 8:
        base = re.sub(r"(高清|超清|标清|HD|SD)+$", "", n[:-2])
        if base and not any(k in base for k in ("购物", "测试", "广告")):
            canon = base + "卫视"
            return CN_ALIASES.get(canon, canon)
        return None

    # ---- 英文卫视名 ----
    e = re.sub(r"[\(\[].*?[\)\]]", "", low)
    e = re.sub(r"\b(1080p|720p|4k|uhd|fhd|hd|sd|高清|超清)\b", "", e)
    for keyword, canonical in EN_SATELLITES:
        if keyword in e:
            return canonical

    return None


def channel_group(name):
    if name.startswith("CCTV-"):
        return "央视频道"
    if name.startswith("CHC-"):
        return "电影频道"
    return "卫视频道"


def sort_key(name):
    return (_ORDER_INDEX.get(name, len(_ORDER_INDEX)), name)


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="聚合公开 IPTV 源，生成 TVBox 可用的 tv.m3u / tv.txt")
    ap.add_argument("--out-dir", default=".", help="输出目录（默认当前目录）")
    ap.add_argument("--sources", default="sources.txt", help="来源列表文件")
    args = ap.parse_args()

    urls = load_sources(args.sources)
    if not urls:
        print("sources.txt 为空或不存在", file=sys.stderr)
        sys.exit(1)

    channels = {}          # 规范名 -> set(URL)
    ok_count = 0
    for url in urls:
        text = fetch(url)
        if not text or "#EXTINF" not in text:
            if text:
                print(f"[跳过] {url} 内容不是有效的 M3U", file=sys.stderr)
            continue
        ok_count += 1
        for raw_name, stream_url in parse_m3u(text):
            canon = normalize(raw_name)
            if not canon:
                continue
            stream_url = stream_url.strip()
            if not stream_url.startswith(("http://", "https://")):
                continue
            channels.setdefault(canon, set()).add(stream_url)

    # 每频道去重后排序，最多保留 3 条
    final = {
        name: sorted(url_set)[:MAX_URLS_PER_CHANNEL]
        for name, url_set in channels.items()
    }
    ordered = sorted(final, key=sort_key)

    import os
    os.makedirs(args.out_dir, exist_ok=True)
    m3u_path = os.path.join(args.out_dir, "tv.m3u")
    txt_path = os.path.join(args.out_dir, "tv.txt")

    with open(m3u_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name in ordered:
            grp = channel_group(name)
            for u in final[name]:
                f.write(f'#EXTINF:-1 tvg-name="{name}" group-title="{grp}",{name}\n{u}\n')

    with open(txt_path, "w", encoding="utf-8") as f:
        last_grp = None
        for name in ordered:
            grp = channel_group(name)
            if grp != last_grp:
                f.write(f"{grp},#genre#\n")
                last_grp = grp
            for u in final[name]:
                f.write(f"{name},{u}\n")

    total_entries = sum(len(v) for v in final.values())
    print(f"成功抓取 {ok_count}/{len(urls)} 个源；"
          f"频道 {len(final)} 个；条目 {total_entries} 条")
    print(f"已生成: {m3u_path} / {txt_path}")


if __name__ == "__main__":
    main()
