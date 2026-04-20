import requests
import concurrent.futures
from urllib.parse import urlparse
from datetime import datetime
import re

# ================= 配置区域 =================
# 精选的高质量公开直播源列表 (混合 M3U 和 TXT 格式)
SOURCE_URLS = [
    # fanmingming (IPv6 标杆)
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    # Guovin (近期非常火的聚合源，每日自动更新)
    "https://raw.githubusercontent.com/Guovin/TV/gd/result.m3u",
    # yuanzl77 (高质量聚合源)
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    # YueChan (经典老牌源)
    "https://raw.githubusercontent.com/YueChan/Live/main/IPTV.m3u",
    # WangNing (轻量级 IPv6 源)
    "https://raw.githubusercontent.com/WangNing8991/lightweight_live/main/m3u/ipv6.m3u",
    # 肥羊 (备用 TXT 格式源)
    "https://m3u.ibert.me/txt/fmml_ipv6.txt",
    "https://m3u.ibert.me/txt/y_g.txt",
    "https://m3u.ibert.me/txt/j_iptv.txt"
]

OUTPUT_FILE = "tv_channels.m3u"
TIMEOUT = 5

# 【重要配置】是否在海外服务器上默认 IPv6 源有效？
# 运行在美国 VPS 或 GitHub Actions 上务必设为 True
ASSUME_IPV6_VALID = True 

# 伪装浏览器请求头，防止被拦截
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
# ============================================

def is_ipv6_url(url):
    """判断是否为 IPv6 链接"""
    netloc = urlparse(url).netloc
    if '[' in netloc and ']' in netloc:
        return True
    if 'ipv6' in netloc.lower():
        return True
    return False

def fetch_sources():
    """获取并解析直播源，支持 M3U 和 TXT 格式，按频道名称分组"""
    channels_dict = {}
    print(f"开始从 {len(SOURCE_URLS)} 个公开接口获取直播源...")
    
    for url in SOURCE_URLS:
        try:
            print(f"正在拉取: {url}")
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.encoding = 'utf-8'
            lines = response.text.split('\n')
            
            current_info = ""
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 1. 解析 M3U 格式
                if line.startswith("#EXTINF"):
                    current_info = line
                elif line.startswith("http") and current_info:
                    name = current_info.split(',')[-1].strip()
                    add_to_dict(channels_dict, name, current_info, line)
                    current_info = ""
                    
                # 2. 解析 TXT 格式 (例如: CCTV-1,http://...)
                elif ",http" in line:
                    parts = line.split(',', 1)
                    if len(parts) == 2:
                        name = parts[0].strip()
                        stream_url = parts[1].strip()
                        # 为 TXT 源伪造一个标准的 M3U 信息头
                        fake_info = f'#EXTINF:-1 tvg-name="{name}",{name}'
                        add_to_dict(channels_dict, name, fake_info, stream_url)
                        
        except Exception as e:
            print(f"❌ 获取源失败 (跳过) {url}: {e}")
            
    return channels_dict

def add_to_dict(channels_dict, name, info, url):
    """清理频道名称并加入字典"""
    # 清理频道名称，去除多余的后缀，确保同一个频道能合并在一起
    # 例如把 "CCTV-1 综合", "CCTV1-FHD", "CCTV-1(IPv6)" 统一归类为 "CCTV-1"
    clean_name = re.sub(r'\[.*?\]|\(.*?\)| FHD| HD| 4K| 综合| 频道|-| ', '', name).upper()
    # 简单修复央视名称
    if clean_name.startswith("CCTV") and len(clean_name) > 4 and clean_name[4].isdigit():
        clean_name = f"CCTV-{clean_name[4:]}"
        
    if clean_name not in channels_dict:
        channels_dict[clean_name] = []
        
    channels_dict[clean_name].append({
        "name": name,
        "clean_name": clean_name,
        "info": info,
        "url": url,
        "is_ipv6": is_ipv6_url(url)
    })

def check_stream(url, is_ipv6):
    """验证单个直播源是否可用"""
    if is_ipv6 and ASSUME_IPV6_VALID:
        return True
        
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
        if response.status_code == 200:
            return True
    except requests.RequestException:
        pass
    return False

def process_channel(channel_name, sources):
    """处理单个频道：去重、排序并找出第一个可用的源"""
    # 链接去重 (不同公开源可能包含完全相同的链接)
    unique_sources = {src['url']: src for src in sources}.values()
    sources_list = list(unique_sources)
    
    # 排序：IPv6 优先
    sources_list.sort(key=lambda x: x['is_ipv6'], reverse=True)
    
    for source in sources_list:
        if check_stream(source['url'], source['is_ipv6']):
            return source
            
    return None

def main():
    channels_dict = fetch_sources()
    total_links = sum(len(v) for v in channels_dict.values())
    print(f"\n✅ 拉取完成！共获取到 {len(channels_dict)} 个独立频道，总计 {total_links} 条播放链接。")
    print("开始优选验证 (IPv6 优先)...")
    
    if ASSUME_IPV6_VALID:
        print("⚠️ 已开启海外服务器 IPv6 免验证模式")

    valid_channels = []
    
    # 并发处理每个频道 (最大线程数设为 100，加快海量链接的验证速度)
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        future_to_name = {
            executor.submit(process_channel, name, sources): name 
            for name, sources in channels_dict.items()
        }
        
        for future in concurrent.futures.as_completed(future_to_name):
            result = future.result()
            if result:
                valid_channels.append(result)
                type_str = "IPv6" if result['is_ipv6'] else "IPv4"
                print(f"[有效 - {type_str}] {result['name']}")
            else:
                name = future_to_name[future]
                print(f"[全部失效] {name}")

    print(f"\n🎉 验证完成！最终保留有效频道数: {len(valid_channels)} / {len(channels_dict)}")

    # 生成 TiviMate 支持的 M3U 文件
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        # 注入 fanmingming 的 EPG 节目单接口
        f.write('#EXTM3U x-tvg-url="https://live.fanmingming.com/e.xml"\n')
        
        update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f'#EXTINF:-1 group-title="更新时间",最后更新: {update_time}\n')
        f.write('http://127.0.0.1/dummy.m3u8\n')
        
        # 按频道名称排序，让 TiviMate 列表更整洁
        valid_channels.sort(key=lambda x: x['clean_name'])
        
        for c in valid_channels:
            f.write(f"{c['info']}\n")
            f.write(f"{c['url']}\n")

    print(f"播放列表已保存至 {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
