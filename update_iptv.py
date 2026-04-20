import requests
import concurrent.futures
from urllib.parse import urlparse
from datetime import datetime
import re

# ================= 配置区域 =================
# 公开直播源获取地址 (包含 IPv6 和 IPv4 的混合源)
SOURCE_URLS = [
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://raw.githubusercontent.com/YueChan/Live/main/IPTV.m3u",
]

OUTPUT_FILE = "tv_channels.m3u"
TIMEOUT = 5

# 【重要配置】是否在海外服务器上默认 IPv6 源有效？
# 如果你运行在美国 VPS 或 GitHub Actions 上，请务必设为 True，否则国内 IPv6 源会被全部误判失效！
# 如果你运行在国内支持 IPv6 的网络环境下，可以设为 False 进行真实验证。
ASSUME_IPV6_VALID = True 
# ============================================

def is_ipv6_url(url):
    """判断是否为 IPv6 链接"""
    netloc = urlparse(url).netloc
    # 检查是否包含 IPv6 的特征括号，例如 http://[2409:8087:...]/
    if '[' in netloc and ']' in netloc:
        return True
    # 检查域名中是否明确标示 ipv6
    if 'ipv6' in netloc.lower():
        return True
    return False

def fetch_sources():
    """获取并解析直播源，按频道名称分组"""
    channels_dict = {}
    print("开始获取直播源...")
    
    for url in SOURCE_URLS:
        try:
            response = requests.get(url, timeout=10)
            response.encoding = 'utf-8'
            lines = response.text.split('\n')
            
            current_info = ""
            for line in lines:
                line = line.strip()
                if line.startswith("#EXTINF"):
                    current_info = line
                elif line.startswith("http"):
                    if current_info:
                        # 提取频道名称 (逗号后面的部分)
                        name = current_info.split(',')[-1].strip()
                        # 简单清理频道名称，方便合并 (例如把 "CCTV-1 综合" 统一归类)
                        clean_name = re.sub(r'\[.*?\]|\(.*?\)| FHD| HD', '', name).strip()
                        
                        if clean_name not in channels_dict:
                            channels_dict[clean_name] = []
                            
                        channels_dict[clean_name].append({
                            "name": name,
                            "clean_name": clean_name,
                            "info": current_info,
                            "url": line,
                            "is_ipv6": is_ipv6_url(line)
                        })
                        current_info = ""
        except Exception as e:
            print(f"获取源失败 {url}: {e}")
            
    return channels_dict

def check_stream(url, is_ipv6):
    """验证单个直播源是否可用"""
    # 海外服务器免验证 IPv6 逻辑
    if is_ipv6 and ASSUME_IPV6_VALID:
        return True
        
    try:
        # 仅请求头部，快速验证
        response = requests.get(url, timeout=TIMEOUT, stream=True)
        if response.status_code == 200:
            return True
    except requests.RequestException:
        pass
    return False

def process_channel(channel_name, sources):
    """处理单个频道：排序并找出第一个可用的源"""
    # 核心逻辑：按 is_ipv6 降序排序，确保 IPv6 排在最前面！
    sources.sort(key=lambda x: x['is_ipv6'], reverse=True)
    
    for source in sources:
        if check_stream(source['url'], source['is_ipv6']):
            # 找到第一个可用的源就立即返回（优先命中的肯定是 IPv6）
            return source
            
    return None # 所有源都失效

def main():
    channels_dict = fetch_sources()
    print(f"共获取到 {len(channels_dict)} 个独立频道，开始优选验证 (IPv6 优先)...")
    if ASSUME_IPV6_VALID:
        print("⚠️ 已开启海外服务器 IPv6 免验证模式")

    valid_channels = []
    
    # 并发处理每个频道
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        # 提交任务：每个频道作为一个任务
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

    print(f"\n验证完成！最终保留有效频道数: {len(valid_channels)} / {len(channels_dict)}")

    # 生成 TiviMate 支持的 M3U 文件
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U x-tvg-url="https://live.fanmingming.com/e.xml"\n')
        
        update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f'#EXTINF:-1 group-title="更新时间",最后更新: {update_time}\n')
        f.write('http://127.0.0.1/dummy.m3u8\n')
        
        # 按频道名称简单排序一下，让列表更好看
        valid_channels.sort(key=lambda x: x['clean_name'])
        
        for c in valid_channels:
            f.write(f"{c['info']}\n")
            f.write(f"{c['url']}\n")

    print(f"播放列表已保存至 {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
