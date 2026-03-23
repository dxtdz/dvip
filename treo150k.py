import asyncio
import aiohttp
import aiohttp.client_exceptions
import time
import os
import sys
import hashlib
import random
import gc
import psutil
import signal
from collections import defaultdict
from datetime import datetime
import tracemalloc

# Bật theo dõi memory
tracemalloc.start()

# Màu sắc ANSI
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    RESET = '\033[0m'
    RAINBOW = [RED, YELLOW, GREEN, CYAN, BLUE, PURPLE]

# Biến toàn cục
sent_messages = 0
failed_messages = 0
rate_limit_hits = 0
proxies = []
token_delays = {}
token_rate_limit_times = defaultdict(float)
semaphore = None
stop_event = asyncio.Event()

# QUẢN LÝ TOKEN
active_tokens = []
invalid_tokens = set()
token_last_used = {}
token_fail_count = {}
token_success_count = {}
token_lock = asyncio.Lock()

# QUẢN LÝ RAM
last_cleanup_time = time.time()
CLEANUP_INTERVAL = 300
MAX_MEMORY_PERCENT = 80

# Request tracker
request_tracker = {
    "requests": [],
    "last_reset": time.time(),
    "consecutive_failures": 0
}

# ==================== USER-AGENT MOBILE ====================
MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.165 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.165 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.165 Mobile Safari/537.36",
]

token_user_agent = {}

def get_mobile_user_agent(token):
    if token not in token_user_agent:
        token_user_agent[token] = random.choice(MOBILE_USER_AGENTS)
    return token_user_agent[token]

def generate_request_fingerprint():
    timestamp = str(int(time.time() * 1000))
    random_id = str(random.randint(100000, 999999))
    return hashlib.md5(f"{timestamp}{random_id}".encode()).hexdigest()

def get_smart_headers(token):
    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": get_mobile_user_agent(token),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

def color_rainbow(text):
    result = ""
    colors = Colors.RAINBOW
    for i, char in enumerate(text):
        color = colors[i % len(colors)]
        result += f"{color}{char}"
    result += Colors.RESET
    return result

def color_gradient(text, start_color, end_color):
    return f"{start_color}{text}{Colors.RESET}"

def get_time():
    return datetime.now().strftime("%H:%M:%S | %d/%m/%Y")

def log_info(msg):
    print(color_rainbow(f"[INFO] {msg}"))

def log_success(msg):
    print(f"{Colors.GREEN}[SUCCESS] {msg}{Colors.RESET}")

def log_warning(msg):
    print(f"{Colors.YELLOW}[WARNING] {msg}{Colors.RESET}")

def log_error(msg):
    print(f"{Colors.RED}[ERROR] {msg}{Colors.RESET}")

def log_input(msg):
    print(color_rainbow(f"[INPUT] {msg}"), end="")
    return input()

def log_memory():
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / 1024 / 1024
    cpu_percent = process.cpu_percent()
    system_memory = psutil.virtual_memory()
    
    print(f"{Colors.PURPLE}[MEMORY] RAM: {memory_mb:.2f} MB | CPU: {cpu_percent:.1f}% | System: {system_memory.percent}%{Colors.RESET}")
    return memory_mb

def read_proxies(file_name):
    if not os.path.exists(file_name):
        return []
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            proxy_list = []
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '://' in line:
                        proxy_list.append(line)
                    else:
                        parts = line.split(':')
                        if len(parts) >= 2:
                            if len(parts) == 2:
                                proxy_url = f"http://{parts[0]}:{parts[1]}"
                                proxy_list.append(proxy_url)
                            elif len(parts) == 4:
                                proxy_url = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
                                proxy_list.append(proxy_url)
            return proxy_list
    except:
        return []

def read_tokens(file_name):
    if not os.path.exists(file_name):
        return []
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except:
        return []

async def get_channel_and_server_info(session, token, channel_id):
    headers = get_smart_headers(token)
    try:
        async with session.get(f"https://discord.com/api/v9/channels/{channel_id}", headers=headers, timeout=5) as response:
            if response.status == 200:
                channel_data = await response.json()
                channel_name = channel_data.get("name", "Unknown Channel")
                guild_id = channel_data.get("guild_id")
                if guild_id:
                    async with session.get(f"https://discord.com/api/v9/guilds/{guild_id}", headers=headers, timeout=5) as guild_response:
                        if guild_response.status == 200:
                            guild_data = await guild_response.json()
                            server_name = guild_data.get("name", "Unknown Server")
                            return channel_name, server_name
        return "Unknown Channel", "Unknown Server"
    except:
        return "Unknown Channel", "Unknown Server"

def update_request_tracker(success=True):
    global request_tracker
    current_time = time.time()
    if current_time - request_tracker["last_reset"] >= 60:
        request_tracker["requests"] = []
        request_tracker["last_reset"] = current_time
        request_tracker["consecutive_failures"] = 0
    
    request_tracker["requests"].append(current_time)
    request_tracker["consecutive_failures"] = 0 if success else request_tracker["consecutive_failures"] + 1

def calculate_adaptive_delay(base_delay, consecutive_success, consecutive_failures):
    if consecutive_failures > 8:
        return min(base_delay * 1.5, 2.0)
    elif consecutive_success > 5:
        return max(base_delay * 0.1, 0.005)
    else:
        return base_delay + random.uniform(-0.02, 0.02)

def handle_rate_limit(token, retry_after=None):
    current_time = time.time()
    if retry_after:
        wait_time = float(retry_after) * 0.1
    else:
        base_wait = 0.5
        rate_limit_count = token_rate_limit_times.get(token, 0)
        wait_time = base_wait * (rate_limit_count + 1) * 0.5
    
    token_rate_limit_times[token] = current_time + wait_time
    return wait_time

async def cleanup_invalid_tokens():
    global active_tokens, invalid_tokens, last_cleanup_time
    
    async with token_lock:
        before_count = len(active_tokens)
        before_invalid = len(invalid_tokens)
        
        active_tokens = [t for t in active_tokens if t not in invalid_tokens]
        
        for token in invalid_tokens:
            if token in token_fail_count:
                del token_fail_count[token]
            if token in token_success_count:
                del token_success_count[token]
            if token in token_last_used:
                del token_last_used[token]
            if token in token_rate_limit_times:
                del token_rate_limit_times[token]
            if token in token_user_agent:
                del token_user_agent[token]
        
        removed = before_count - len(active_tokens)
        
        gc.collect()
        
        log_memory()
        
        if removed > 0:
            log_success(f"CLEANUP: Đã xóa {removed} token die | Tổng invalid: {before_invalid} | Token còn: {len(active_tokens)}")
        
        last_cleanup_time = time.time()
        return removed

async def periodic_cleanup():
    global last_cleanup_time
    
    while not stop_event.is_set():
        try:
            await asyncio.sleep(60)
            
            current_time = time.time()
            time_since_cleanup = current_time - last_cleanup_time
            
            process = psutil.Process(os.getpid())
            memory_percent = process.memory_percent()
            system_memory = psutil.virtual_memory()
            
            should_cleanup = (
                time_since_cleanup >= CLEANUP_INTERVAL or
                memory_percent > MAX_MEMORY_PERCENT or
                system_memory.percent > 90
            )
            
            if should_cleanup:
                if time_since_cleanup >= CLEANUP_INTERVAL:
                    log_info(f"Định kỳ 5 phút: Đang dọn dẹp...")
                elif memory_percent > MAX_MEMORY_PERCENT:
                    log_warning(f"RAM tool cao ({memory_percent:.1f}%): Đang dọn gấp...")
                else:
                    log_warning(f"RAM hệ thống cao ({system_memory.percent}%): Đang dọn gấp...")
                
                await cleanup_invalid_tokens()
                
        except Exception as e:
            log_error(f"Lỗi trong periodic_cleanup: {e}")

async def send_typing(session, channel_id, headers):
    """Gửi typing indicator để chống rate limit"""
    try:
        async with session.post(
            f"https://discord.com/api/v9/channels/{channel_id}/typing",
            headers=headers,
            timeout=2
        ) as response:
            return response.status == 204
    except:
        return False

async def log_message(channel_id, channel_name, server_name, content, token, status="Success", proxy=None, typing_time=0):
    global sent_messages, failed_messages
    short_token = f"{token[:6]}...{token[-6:]}"
    proxy_info = f"{proxy}" if proxy else "No Proxy"
    content_preview = content[:30] + ("..." if len(content) > 30 else "")
    gio = datetime.now().strftime("%H|%M|%S")
    
    if status == "Success":
        sent_messages += 1
        if sent_messages % 100 == 0:
            log_memory()
        typing_info = f" | Typing: {typing_time:.1f}s" if typing_time > 0 else ""
        print(color_gradient(f"[{gio} | Successfully] >> Token: {short_token} | Channel: {channel_name} | Server: {server_name} | Ndung: {content_preview} | Send: {sent_messages} | Proxy: {proxy_info}{typing_info}", Colors.GREEN, Colors.CYAN))
    else:
        failed_messages += 1

async def spam_task(semaphore, token, channel_id, channel_info, contents, base_delay, proxy_list, task_id, typing_delay):
    global active_tokens, invalid_tokens, stop_event
    
    channel_name = channel_info.get("name", "Unknown Channel")
    server_name = channel_info.get("server", "Unknown Server")
    content_index = task_id % len(contents)
    
    consecutive_success = 0
    consecutive_failures = 0
    token_delay = token_delays.get(token, base_delay)
    proxy_index = 0
    
    while not stop_event.is_set():
        try:
            if token in invalid_tokens:
                break
            
            async with semaphore:
                current_time = time.time()
                if current_time < token_rate_limit_times.get(token, 0):
                    wait_time = token_rate_limit_times[token] - current_time
                    await asyncio.sleep(wait_time * 0.5)
                    continue
                
                proxy = None
                if proxy_list:
                    proxy = proxy_list[proxy_index % len(proxy_list)]
                    proxy_index += 1
                
                headers = get_smart_headers(token)
                
                # Tạo session mới cho mỗi request
                connector = aiohttp.TCPConnector(ssl=False, force_close=True)
                async with aiohttp.ClientSession(connector=connector) as session:
                    # GỬI TYPING TRƯỚC
                    typing_start = time.time()
                    
                    # Gửi typing indicator
                    try:
                        async with session.post(
                            f"https://discord.com/api/v9/channels/{channel_id}/typing",
                            headers=headers,
                            timeout=2
                        ) as typing_response:
                            pass
                    except:
                        pass
                    
                    # Đợi typing_delay giây (giả lập đang gõ)
                    await asyncio.sleep(typing_delay)
                    
                    # Sau đó mới gửi message
                    payload = {"content": contents[content_index]}
                    content_index = (content_index + 1) % len(contents)
                    
                    try:
                        async with session.post(
                            f"https://discord.com/api/v9/channels/{channel_id}/messages",
                            headers=headers,
                            json=payload,
                            proxy=proxy,
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as response:
                            
                            token_last_used[token] = time.time()
                            typing_time = time.time() - typing_start
                            
                            if response.status == 404:
                                async with token_lock:
                                    if token not in invalid_tokens:
                                        invalid_tokens.add(token)
                                        log_error(f"TOKEN 404: {token[:6]}...{token[-6:]} - Đã xóa")
                                        
                                        if len(invalid_tokens) % 5 == 0:
                                            asyncio.create_task(cleanup_invalid_tokens())
                                break
                                
                            elif response.status == 429:
                                global rate_limit_hits
                                rate_limit_hits += 1
                                consecutive_failures += 1
                                consecutive_success = 0
                                token_fail_count[token] = token_fail_count.get(token, 0) + 1
                                
                                retry_after = response.headers.get('Retry-After')
                                wait_time = handle_rate_limit(token, retry_after)
                                
                                print(color_gradient(
                                    f"[RATE LIMIT] Token: {token[:6]}...{token[-6:]} | Channel: {channel_name} | Wait: {wait_time:.2f}s | Proxy: {proxy if proxy else 'None'}",
                                    Colors.YELLOW, Colors.RED
                                ))
                                
                                update_request_tracker(False)
                                await asyncio.sleep(0.01)
                                
                            elif response.status == 200:
                                await log_message(channel_id, channel_name, server_name, contents[content_index], token, "Success", proxy, typing_time)
                                consecutive_success += 1
                                consecutive_failures = 0
                                token_success_count[token] = token_success_count.get(token, 0) + 1
                                token_fail_count[token] = 0
                                update_request_tracker(True)
                                
                                adaptive_delay = calculate_adaptive_delay(token_delay, consecutive_success, consecutive_failures)
                                await asyncio.sleep(adaptive_delay)
                            else:
                                consecutive_failures += 1
                                consecutive_success = 0
                                token_fail_count[token] = token_fail_count.get(token, 0) + 1
                                update_request_tracker(False)
                                
                                if token_fail_count.get(token, 0) >= 10:
                                    async with token_lock:
                                        if token not in invalid_tokens:
                                            invalid_tokens.add(token)
                                            log_warning(f"TOKEN FAIL 10 LẦN: {token[:6]}...{token[-6:]} - Đã xóa")
                                    break
                                
                                await asyncio.sleep(0.1)
                                
                    except asyncio.TimeoutError:
                        consecutive_failures += 1
                        update_request_tracker(False)
                        await asyncio.sleep(0.2)
                    except Exception as e:
                        consecutive_failures += 1
                        consecutive_success = 0
                        token_fail_count[token] = token_fail_count.get(token, 0) + 1
                        update_request_tracker(False)
                        
                        if proxy_list:
                            proxy_index += 1
                        
                        await asyncio.sleep(0.1)
                    
                    await connector.close()
                    
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(0.1)

async def main_async():
    global semaphore, proxies, token_delays, stop_event, active_tokens
    
    print(color_gradient("\n" + "="*70, Colors.CYAN, Colors.BLUE))
    log_info("SPAM DISCORD - MODE TYPING")
    print(color_gradient("="*70, Colors.CYAN, Colors.BLUE))
    
    log_success(f"Đã load {len(MOBILE_USER_AGENTS)} user-agent mobile")
    
    log_info("Chọn chế độ spam:")
    print(color_rainbow("  1. Đơn token\n  2. Đa token"))
    token_mode = log_input("Chọn [1 or 2]: ").strip()
    while token_mode not in ["1", "2"]:
        log_warning("Lựa chọn phải là 1 hoặc 2!")
        token_mode = log_input("Chọn [1-2]: ").strip()
    
    tokens = []
    if token_mode == "1":
        token = log_input("Nhập Token: ").strip()
        if not token:
            log_error("Token không được để trống!")
            return
        tokens = [token]
    else:
        token_file = log_input("Nhập file token: ").strip()
        if not token_file:
            log_error("Tên file không được để trống!")
            return
        tokens = read_tokens(token_file)
        if not tokens:
            log_error("Không có token hợp lệ trong file!")
            return
        log_success(f"Đã đọc {len(tokens)} token")
    
    active_tokens = tokens.copy()
    
    channel_ids = []
    channel_info = {}
    
    if token_mode == "1":
        channel_id = log_input("Nhập Channel ID: ").strip()
        if not channel_id.isdigit():
            log_error("ID channel phải là số!")
            return
        channel_ids = [channel_id]
        
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            channel_name, server_name = await get_channel_and_server_info(session, tokens[0], channel_id)
            channel_info[channel_id] = {"name": channel_name, "server": server_name}
        await connector.close()
        log_success(f"Channel: {channel_name} | Server: {server_name}")
    else:
        log_info("Nhập ID channels (nhập 'done' để dừng):")
        while True:
            channel_id = log_input("Channel ID: ").strip()
            if channel_id.lower() == "done":
                if not channel_ids:
                    log_error("Cần ít nhất 1 Channel!")
                    continue
                break
            if channel_id.isdigit():
                channel_ids.append(channel_id)
                
                connector = aiohttp.TCPConnector(ssl=False)
                async with aiohttp.ClientSession(connector=connector) as session:
                    channel_name, server_name = await get_channel_and_server_info(session, tokens[0], channel_id)
                    channel_info[channel_id] = {"name": channel_name, "server": server_name}
                await connector.close()
                log_success(f"Thêm: {channel_name} | {server_name}")
            else:
                log_warning("ID kênh phải là số!")
    
    tasks_per_token = log_input("Tasks/token [10]: ").strip() or "10"
    try:
        tasks_per_token = int(tasks_per_token)
        log_success(f"Tasks: {tasks_per_token}")
    except ValueError:
        tasks_per_token = 10
    
    delay_input = log_input("Delay (giây) [5]: ").strip() or "5"
    try:
        base_delay = float(delay_input)
        if base_delay < 0:
            base_delay = 5
        log_success(f"Delay: {base_delay}s")
    except ValueError:
        base_delay = 5
    
    typing_delay_input = log_input("Delay typing (giây) [2]: ").strip() or "2"
    try:
        typing_delay = float(typing_delay_input)
        if typing_delay < 0.5:
            typing_delay = 0.5
        elif typing_delay > 5:
            typing_delay = 5
        log_success(f"Typing delay: {typing_delay}s")
    except ValueError:
        typing_delay = 2.0
        log_success(f"Typing delay: {typing_delay}s (mặc định)")
    
    if token_mode == "2":
        log_info("Setup delay riêng cho từng token:")
        for i, token in enumerate(tokens, 1):
            token_delay_input = log_input(f"Delay cho token {i} [{base_delay}s]: ").strip() or str(base_delay)
            try:
                token_delay = float(token_delay_input)
                if token_delay >= 0:
                    token_delays[token] = token_delay
                    log_success(f"Token {i}: {token_delay}s")
                else:
                    token_delays[token] = base_delay
            except ValueError:
                token_delays[token] = base_delay
    
    content_files = []
    log_info("Nhập file nội dung (nhập 'done' để dừng):")
    while True:
        file_name = log_input("File: ").strip()
        if file_name.lower() == "done":
            if not content_files:
                log_error("Cần ít nhất 1 file nội dung!")
                continue
            break
        if os.path.exists(file_name):
            content_files.append(file_name)
            log_success(f"Thêm: {file_name}")
        else:
            log_warning(f"File '{file_name}' không tồn tại!")
    
    contents = []
    for f in content_files:
        try:
            with open(f, "r", encoding="utf-8") as file:
                content = file.read().strip()
                if content:
                    contents.append(content)
        except Exception as e:
            log_warning(f"Lỗi đọc file {f}: {e}")
    
    if not contents:
        log_error("Không có nội dung hợp lệ!")
        return
    
    proxy_file = log_input("Nhập file proxy (nhập 'skip' để bỏ qua): ").strip()
    proxy_list = []
    if proxy_file.lower() != "skip":
        if os.path.exists(proxy_file):
            proxy_list = read_proxies(proxy_file)
            if proxy_list:
                log_success(f"Sử dụng {len(proxy_list)} proxy")
            else:
                log_warning("Không đọc được proxy nào!")
        else:
            log_warning(f"File '{proxy_file}' không tồn tại!")
    
    max_concurrent = tasks_per_token * len(active_tokens) * len(channel_ids) * 2
    semaphore = asyncio.Semaphore(max_concurrent)
    
    tasks = []
    task_id = 0
    for channel_id in channel_ids:
        for token in active_tokens:
            for _ in range(tasks_per_token):
                task = asyncio.create_task(
                    spam_task(
                        semaphore,
                        token,
                        channel_id,
                        channel_info[channel_id],
                        contents,
                        base_delay,
                        proxy_list,
                        task_id,
                        typing_delay
                    )
                )
                tasks.append(task)
                task_id += 1
    
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    total_tasks = len(tasks)
    log_success(f"Khởi động {total_tasks} tasks spam...")
    log_success(f"User-Agent: Mobile ({len(MOBILE_USER_AGENTS)} loại)")
    log_success(f"Typing delay: {typing_delay}s - Giúp tránh rate limit")
    log_success("Tool đang chạy... Nhấn Ctrl+C để dừng")
    
    log_memory()
    
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        log_warning("Đang dừng tất cả tasks...")
    finally:
        stop_event.set()
        cleanup_task.cancel()
        
        for task in tasks:
            task.cancel()
        
        await asyncio.gather(*tasks, return_exceptions=True)
        await cleanup_invalid_tokens()
        log_success("Đã dừng tất cả tasks")
        log_memory()

def main():
    def signal_handler(sig, frame):
        print(f"\n{Colors.YELLOW}[WARNING] Đang thoát...{Colors.RESET}")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[WARNING] Đang thoát...{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Lỗi không mong muốn: {e}{Colors.RESET}")

if __name__ == "__main__":
    main()
