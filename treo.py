import os
import sys
import time
import random
import asyncio
import aiohttp
import threading
import gc
from pystyle import Colors, Colorate

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Biến toàn cục
failed_count = {}  # Đếm số lần fail của mỗi token
TOKEN_FAIL_LIMIT = 10  # Giới hạn fail trước khi xóa token
tasks_list = []  # Danh sách các task đang chạy
task_id_counter = 1  # Đếm ID task
stop_events = {}  # Lưu stop_event cho mỗi task

def clean_ram():
    gc.collect()

def print_tasks():
    """Hiển thị danh sách task đang chạy"""
    print(Colors.cyan + "\n" + "="*60)
    print(Colors.yellow + "DANH SÁCH TASK ĐANG CHẠY:")
    if not tasks_list:
        print(Colors.red + "Không có task nào!")
    else:
        for i, task_info in enumerate(tasks_list, 1):
            status = Colors.green + "● ĐANG CHẠY" if not stop_events[task_info['id']].is_set() else Colors.red + "● ĐÃ DỪNG"
            print(f"{i}. {status} - Token: {task_info['token'][:10]}... - Channel: {task_info['channel']} - Thread: {task_info['thread_id']}")
    print("="*60 + Colors.white)

async def validate_token(session, token):
    """Kiểm tra token hợp lệ async"""
    url = "https://discord.com/api/v9/users/@me"
    headers = {"Authorization": token.strip()}
    try:
        async with session.get(url, headers=headers, timeout=5) as resp:
            return resp.status == 200
    except:
        return False

async def show_typing(session, token, channel_id):
    """Hiển thị typing async"""
    url = f"https://discord.com/api/v9/channels/{channel_id}/typing"
    headers = {"Authorization": token.strip(), "User-Agent": USER_AGENT}
    try:
        async with session.post(url, headers=headers, timeout=5) as resp:
            return resp.status in [200, 204]
    except:
        return False

async def spam_messages(session, token, channel_id, messages, thread_id, bold_text, task_id, stop_event):
    """Spam tin nhắn với async và tự động xóa token die"""
    global failed_count, tasks_list
    
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    headers = {
        "Authorization": token.strip(),
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }
    
    # Khởi tạo bộ đếm fail cho token nếu chưa có
    if token not in failed_count:
        failed_count[token] = 0
    
    count = 0
    
    while not stop_event.is_set():
        # Kiểm tra nếu token đã bị xóa do fail quá nhiều
        if token not in failed_count:
            print(Colors.red + f"[Task {task_id}] Token đã bị xóa do fail quá {TOKEN_FAIL_LIMIT} lần")
            break
            
        # Xử lý in đậm
        content = f"# {messages}" if bold_text else messages
        
        print(Colors.cyan + f"[Task {task_id}] Đang nhập...")
        await show_typing(session, token, channel_id)
        await asyncio.sleep(random.uniform(0.5, 2.0))
        
        try:
            async with session.post(url, headers=headers, json={"content": content}, timeout=10) as resp:
                
                if resp.status == 200:
                    count += 1
                    # Reset fail count khi gửi thành công
                    failed_count[token] = max(0, failed_count[token] - 1)
                    
                    colors = [Colors.red, Colors.green, Colors.blue, Colors.yellow, Colors.purple]
                    print(colors[count % 5] + f"[✓] Task {task_id} gửi {count} tin nhắn")
                    
                elif resp.status == 429:  # Rate limit
                    data = await resp.json()
                    retry_after = data.get('retry_after', 5)
                    print(Colors.yellow + f"[!] Rate limit task {task_id}, chờ {retry_after}s")
                    await asyncio.sleep(retry_after)
                    
                else:
                    failed_count[token] += 1
                    print(Colors.red + f"[!] Lỗi {resp.status} - task {task_id} (Fail {failed_count[token]}/{TOKEN_FAIL_LIMIT})")
                    
                    # Kiểm tra nếu token fail quá giới hạn
                    if failed_count[token] >= TOKEN_FAIL_LIMIT:
                        print(Colors.red + f"[✗] Token task {task_id} đã bị xóa do fail {TOKEN_FAIL_LIMIT} lần")
                        del failed_count[token]
                        break
                        
        except asyncio.TimeoutError:
            failed_count[token] += 1
            print(Colors.red + f"[!] Timeout task {task_id} (Fail {failed_count[token]}/{TOKEN_FAIL_LIMIT})")
            
            if failed_count[token] >= TOKEN_FAIL_LIMIT:
                print(Colors.red + f"[✗] Token task {task_id} đã bị xóa do timeout nhiều lần")
                del failed_count[token]
                break
                
        except Exception as e:
            failed_count[token] += 1
            print(Colors.red + f"[!] Lỗi task {task_id}: {e} (Fail {failed_count[token]}/{TOKEN_FAIL_LIMIT})")
            
            if failed_count[token] >= TOKEN_FAIL_LIMIT:
                print(Colors.red + f"[✗] Token task {task_id} đã bị xóa do lỗi nhiều lần")
                del failed_count[token]
                break
        
        # Delay giữa các lần gửi
        delay = random.uniform(2.0, 5.0)
        await asyncio.sleep(delay)
        
        # Dọn RAM mỗi 10 tin nhắn
        if count % 10 == 0:
            clean_ram()
    
    # Xóa task khỏi danh sách khi kết thúc
    tasks_list = [t for t in tasks_list if t['id'] != task_id]
    if task_id in stop_events:
        del stop_events[task_id]
    print(Colors.yellow + f"[Task {task_id}] Đã dừng")

async def add_new_task(session, token, channel, messages, bold):
    """Thêm task mới"""
    global task_id_counter, tasks_list, stop_events
    
    task_id = task_id_counter
    task_id_counter += 1
    
    stop_event = threading.Event()
    stop_events[task_id] = stop_event
    
    task_info = {
        'id': task_id,
        'token': token,
        'channel': channel,
        'thread_id': task_id,
        'stop_event': stop_event
    }
    tasks_list.append(task_info)
    
    task = asyncio.create_task(
        spam_messages(session, token, channel, messages, task_id, bold, task_id, stop_event)
    )
    return task_id

async def stop_task(task_number):
    """Dừng task theo số thứ tự trong danh sách"""
    if 1 <= task_number <= len(tasks_list):
        task_info = tasks_list[task_number - 1]
        task_id = task_info['id']
        if task_id in stop_events:
            stop_events[task_id].set()
            print(Colors.yellow + f"Đã yêu cầu dừng task {task_id}")
            return True
    else:
        print(Colors.red + f"Không tìm thấy task số {task_number}")
    return False

async def main_async():
    os.system('cls' if os.name == 'nt' else 'clear')
    
    banner = """
╔══════════════════════════════════════╗
║    DISCORD SPAM TOOL v5            ║
║    Task Manager + Add/Stop          ║
║    Async + Auto Remove Dead Token   ║
╚══════════════════════════════════════╝
    """
    print(Colorate.Horizontal(Colors.rainbow, banner))
    
    # Khởi tạo session
    async with aiohttp.ClientSession() as session:
        messages = ""
        bold = False
        valid_tokens = []
        
        while True:
            print(Colors.cyan + "\n" + "="*60)
            print(Colors.yellow + "MENU ĐIỀU KHIỂN:")
            print("1. " + Colors.green + "ADD" + Colors.white + " - Thêm task mới")
            print("2. " + Colors.blue + "LIST" + Colors.white + " - Xem danh sách task")
            print("3. " + Colors.red + "STOP [số]" + Colors.white + " - Dừng task (VD: stop 1)")
            print("4. " + Colors.purple + "EXIT" + Colors.white + " - Thoát chương trình")
            print("="*60)
            
            cmd = input(Colors.yellow + "Nhập lệnh: " + Colors.white).strip().lower()
            
            if cmd == 'exit':
                # Dừng tất cả task trước khi thoát
                for task_id, stop_event in stop_events.items():
                    stop_event.set()
                print(Colors.red + "Đang dừng tất cả task...")
                await asyncio.sleep(2)
                break
                
            elif cmd == 'list':
                print_tasks()
                
            elif cmd.startswith('stop '):
                try:
                    task_num = int(cmd.split()[1])
                    await stop_task(task_num)
                except (IndexError, ValueError):
                    print(Colors.red + "Cú pháp: stop [số thứ tự]")
                    
            elif cmd == 'add':
                # Thêm task mới
                print(Colors.cyan + "\n--- THÊM TASK MỚI ---")
                
                # Nhập token
                token = input("Nhập token: ").strip()
                if not token:
                    print(Colors.red + "Token không được để trống!")
                    continue
                
                # Validate token
                print("Đang kiểm tra token...")
                if not await validate_token(session, token):
                    print(Colors.red + "Token không hợp lệ!")
                    continue
                
                # Nhập channel ID
                channel = input("Nhập channel ID: ").strip()
                if not channel:
                    print(Colors.red + "Channel ID không được để trống!")
                    continue
                
                # Nhập nội dung tin nhắn nếu chưa có
                if not messages:
                    file_path = input("Nhập đường dẫn file tin nhắn (Enter để nhập trực tiếp): ").strip()
                    if file_path:
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                messages = f.read().strip()
                            print(Colors.green + f"✓ Đã load {len(messages)} ký tự từ file")
                        except:
                            print(Colors.red + "Không đọc được file!")
                            messages = input("Nhập tin nhắn: ").strip()
                    else:
                        messages = input("Nhập tin nhắn: ").strip()
                    
                    if not messages:
                        print(Colors.red + "Nội dung tin nhắn không được để trống!")
                        continue
                    
                    bold = input("In đậm tin nhắn? (y/n): ").lower() == 'y'
                
                # Thêm task
                task_id = await add_new_task(session, token, channel, messages, bold)
                print(Colors.green + f"✓ Đã thêm task {task_id} thành công!")
                
            else:
                print(Colors.red + "Lệnh không hợp lệ!")

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print(Colors.red + "\n⚠️ Đã dừng tool!")

if __name__ == "__main__":
    main()
