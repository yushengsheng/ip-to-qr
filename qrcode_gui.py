import ipaddress
import locale
import queue
import re
import socket
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse

from concurrent.futures import ThreadPoolExecutor, as_completed
import ssl

import qrcode
from PIL import Image, ImageTk


rows = {}
current_qr_photo = None
paste_placeholder_visible = False
preview_url_value = ""
current_preview_item_id = None
context_menu_item_id = None
active_test_jobs = 0
bulk_test_running = False
test_result_queue = queue.Queue()

IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
RESAMPLING = getattr(Image, "Resampling", Image)
DEFAULT_TEST_TARGET = "https://www.google.com"
SOCKS5_REPLY_MESSAGES = {
    0x01: "代理故障",
    0x02: "规则拒绝",
    0x03: "网络不可达",
    0x04: "目标主机不可达",
    0x05: "目标拒绝连接",
    0x06: "TTL 过期",
    0x07: "命令不支持",
    0x08: "地址类型不支持",
}
PASTE_PLACEHOLDER = """支持以下导入格式（每行一条）
1. 纯代理
113.201.9.110|5477|mbjs20x2|mbjs20x2|2026-01-19

2. 备注 + 代理
burtonbattis885@outlook.com GRO_28502_7Q1C3 113.201.9.110|5477|mbjs20x2|mbjs20x2|2026-01-19

3. 代理 + 备注
113.201.9.110|5477|mbjs20x2|mbjs20x2|2026-01-19 burtonbattis885@outlook.com GRO_28502_7Q1C3

日期可选，最少支持 IP|端口|用户|密码。
直接粘贴多行数据后，点击下方“导入粘贴内容”即可。"""


def extract_ip_data(text):
    parts = re.split(r"\s+", text.strip())
    ip_data = None
    remarks_parts = []

    for part in parts:
        if "|" in part and IP_PATTERN.search(part):
            ip_parts = part.split("|")
            if len(ip_parts) >= 4:
                ip_data = {
                    "ip": ip_parts[0],
                    "port": ip_parts[1],
                    "user": ip_parts[2],
                    "pwd": ip_parts[3],
                    "date": ip_parts[4] if len(ip_parts) > 4 else "",
                }
                continue
        remarks_parts.append(part)

    return ip_data, " - ".join(remarks_parts)


def build_proxy_url(ip_data, remarks):
    base = (
        f"socks5://{ip_data['user']}:{ip_data['pwd']}"
        f"@{ip_data['ip']}:{ip_data['port']}"
    )
    return f"{base}#{remarks}" if remarks else base


def build_tree_values(ip_data, remarks, latency, status):
    endpoint = f"{ip_data['ip']}:{ip_data['port']}"
    return (
        endpoint,
        ip_data["user"],
        ip_data["pwd"],
        ip_data["date"] or "-",
        remarks or "-",
        latency,
        status,
    )


def make_qr_image(url):
    image = qrcode.make(url)
    if hasattr(image, "get_image"):
        image = image.get_image()
    return image.convert("RGB")


def build_preview_meta(row):
    return (
        f"用户: {row['ip_data']['user']}\n"
        f"日期: {row['ip_data']['date'] or '-'}\n"
        f"备注: {row['remarks'] or '-'}\n"
        f"目标: {row['target_display']}\n"
        f"延迟: {row['latency']}\n"
        f"连通: {row['test_status']}"
    )


def refresh_row(item_id):
    row = rows.get(item_id)
    if not row or not table.exists(item_id):
        return

    table.item(
        item_id,
        values=build_tree_values(
            row["ip_data"],
            row["remarks"],
            row["latency"],
            row["test_status"],
        ),
    )


def update_preview(item_id, url, image):
    global current_qr_photo, preview_url_value, current_preview_item_id

    preview_image = image.copy()
    preview_image.thumbnail((220, 220), RESAMPLING.LANCZOS)
    current_qr_photo = ImageTk.PhotoImage(preview_image)

    preview_canvas.delete("all")
    preview_canvas.create_image(120, 120, image=current_qr_photo, anchor="center")
    preview_canvas.image = current_qr_photo

    row = rows[item_id]
    preview_title_var.set(f"{row['ip_data']['ip']}:{row['ip_data']['port']}")
    preview_meta_var.set(build_preview_meta(row))
    preview_url_value = url
    preview_url_text.config(state="normal")
    preview_url_text.delete("1.0", tk.END)
    preview_url_text.insert("1.0", url)
    preview_url_text.config(state="disabled")
    current_preview_item_id = item_id


def clear_preview():
    global current_qr_photo, preview_url_value, current_preview_item_id

    current_qr_photo = None
    preview_url_value = ""
    current_preview_item_id = None

    preview_canvas.delete("all")
    preview_canvas.create_text(120, 120, text="暂无二维码", fill="#7a8696", font=("Segoe UI", 11))
    preview_title_var.set("等待选择")
    preview_meta_var.set("从左侧列表选择一条数据，再点击“预览二维码”或直接双击。")
    preview_url_text.config(state="normal")
    preview_url_text.delete("1.0", tk.END)
    preview_url_text.insert("1.0", "代理链接将在这里显示")
    preview_url_text.config(state="disabled")


def show_qr_for_item(item_id):
    row = rows[item_id]
    url = build_proxy_url(row["ip_data"], row["remarks"])

    try:
        qr_image = make_qr_image(url)
        update_preview(item_id, url, qr_image)
        update_status(f"已预览二维码: {row['ip_data']['ip']}:{row['ip_data']['port']}")
    except Exception as exc:
        messagebox.showerror("错误", f"生成二维码失败: {exc}")


def preview_selected():
    selected = table.selection()
    if not selected:
        messagebox.showwarning("提示", "请先选择一条代理数据。")
        return
    show_qr_for_item(selected[0])


def add_row(text, show_warning=True):
    raw_text = text.strip()
    if not raw_text:
        return False

    ip_data, remarks = extract_ip_data(raw_text)
    if not ip_data:
        if show_warning:
            messagebox.showwarning("警告", f"未识别到有效代理数据:\n{raw_text}")
        return False

    status = "未预览"
    values = build_tree_values(ip_data, remarks, "-", "未测试")
    item_id = table.insert("", "end", values=values)
    rows[item_id] = {
        "ip_data": ip_data,
        "remarks": remarks,
        "original_text": raw_text,
        "status": status,
        "latency": "-",
        "test_status": "未测试",
        "target_display": "-",
    }
    update_count()
    return True


def add_lines(lines, source_name):
    success_count = 0
    skipped_lines = []

    for line in lines:
        raw_line = line.strip()
        if not raw_line:
            continue

        if add_row(raw_line, show_warning=False):
            success_count += 1
        else:
            skipped_lines.append(raw_line)

    skipped_count = len(skipped_lines)

    if success_count == 0 and skipped_count > 0:
        messagebox.showwarning("导入结果", "没有识别到有效代理数据。")
    else:
        messagebox.showinfo(
            "导入完成",
            f"{source_name}导入完成。\n成功: {success_count} 条\n跳过: {skipped_count} 条",
        )

    update_count()
    update_status(f"{source_name}导入完成: 成功 {success_count} 条，跳过 {skipped_count} 条")
    return success_count, skipped_lines


def read_text_lines_with_fallback(path):
    preferred_encoding = locale.getpreferredencoding(False) or "utf-8"
    encodings = []

    for encoding in ("utf-8-sig", "gbk", preferred_encoding):
        if encoding and encoding.lower() not in {item.lower() for item in encodings}:
            encodings.append(encoding)

    errors = []
    for encoding in encodings:
        try:
            with open(path, "r", encoding=encoding) as file:
                return file.readlines(), encoding
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")

    details = "\n".join(errors) if errors else "没有可用的编码可尝试。"
    raise RuntimeError(details)


def import_data():
    path = filedialog.askopenfilename(
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
    )
    if not path:
        return

    try:
        lines, encoding_used = read_text_lines_with_fallback(path)
        add_lines(lines, f"文件（编码: {encoding_used}）")
    except Exception as exc:
        messagebox.showerror("错误", f"读取文件失败: {exc}")


def get_paste_text_value():
    if paste_placeholder_visible:
        return ""
    return paste_text.get("1.0", tk.END).strip()


def set_paste_text_value(text):
    global paste_placeholder_visible

    paste_text.delete("1.0", tk.END)
    if text:
        paste_text.config(fg="#1f2937")
        paste_text.insert("1.0", text)
        paste_placeholder_visible = False
    else:
        show_paste_placeholder()


def import_pasted_data():
    text = get_paste_text_value()
    if not text:
        messagebox.showwarning("警告", "请先粘贴要导入的内容。")
        return

    _, skipped_lines = add_lines(text.splitlines(), "粘贴内容")
    if skipped_lines:
        set_paste_text_value("\n".join(skipped_lines))
        update_status(f"粘贴导入完成，已保留 {len(skipped_lines)} 条失败数据")
    else:
        clear_paste_text()


def add_single():
    text = single_entry.get().strip()
    if not text:
        messagebox.showwarning("警告", "请输入一条代理数据。")
        return

    if add_row(text):
        single_entry.delete(0, tk.END)
        update_status("已添加 1 条代理数据")


def export_valid_data():
    valid_rows = list(rows.values())
    if not valid_rows:
        messagebox.showinfo("提示", "没有有效数据可导出。")
        return

    path = filedialog.asksaveasfilename(
        defaultextension=".txt",
        filetypes=[("Text files", "*.txt")],
    )
    if not path:
        return

    try:
        with open(path, "w", encoding="utf-8") as file:
            for row in valid_rows:
                file.write(f"{row['original_text']}\n")
        messagebox.showinfo("成功", f"已导出 {len(valid_rows)} 条有效数据。")
        update_status(f"已导出 {len(valid_rows)} 条有效数据")
    except Exception as exc:
        messagebox.showerror("错误", f"导出失败: {exc}")


def select_all():
    items = table.get_children()
    if items:
        table.selection_set(items)
        table.focus_set()
    update_status("已全选")


def deselect_all():
    table.selection_remove(table.selection())
    table.focus_set()
    update_status("已取消全选")


def delete_selected():
    global current_preview_item_id

    selected = table.selection()
    if not selected:
        messagebox.showinfo("提示", "请先选择要删除的数据。")
        return

    if current_preview_item_id in selected:
        clear_preview()

    for item_id in selected:
        table.delete(item_id)
        rows.pop(item_id, None)

    update_count()
    update_status(f"已删除 {len(selected)} 条数据")


def copy_preview_url():
    if not preview_url_value:
        messagebox.showinfo("提示", "当前没有可复制的代理链接。")
        return

    root.clipboard_clear()
    root.clipboard_append(preview_url_value)
    update_status("已复制当前代理链接")


def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise OSError("连接被远端关闭")
        data += chunk
    return data


def normalize_test_target(raw_text):
    text = raw_text.strip()
    if not text:
        raise ValueError("请输入测试网站。")

    parsed = urlparse(text if "://" in text else f"https://{text}")
    scheme = (parsed.scheme or "https").lower()
    if scheme not in {"http", "https"}:
        raise ValueError("只支持 http 或 https 网站。")

    host = parsed.hostname
    if not host:
        raise ValueError("网站格式不正确。")

    try:
        port = parsed.port
    except ValueError:
        raise ValueError("端口格式不正确。") from None

    if port is None:
        port = 443 if scheme == "https" else 80

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    default_port = 443 if scheme == "https" else 80
    host_header = host if port == default_port else f"{host}:{port}"
    display = f"{scheme}://{host_header}{path}"
    return {
        "scheme": scheme,
        "host": host,
        "port": port,
        "path": path,
        "host_header": host_header,
        "display": display,
    }


def build_socks5_connect_request(host, port):
    try:
        ip_obj = ipaddress.ip_address(host)
        if ip_obj.version == 4:
            return b"\x05\x01\x00\x01" + ip_obj.packed + port.to_bytes(2, "big")
        return b"\x05\x01\x00\x04" + ip_obj.packed + port.to_bytes(2, "big")
    except ValueError:
        host_bytes = host.encode("idna")
        if len(host_bytes) > 255:
            raise ValueError("网站地址过长。")
        return (
            b"\x05\x01\x00\x03"
            + bytes([len(host_bytes)])
            + host_bytes
            + port.to_bytes(2, "big")
        )


def recv_until(sock, marker=b"\r\n", max_bytes=4096):
    data = b""
    while marker not in data:
        chunk = sock.recv(1024)
        if not chunk:
            raise OSError("未收到响应")
        data += chunk
        if len(data) > max_bytes:
            raise OSError("响应头过长")
    return data


def build_http_probe_request(target, method):
    return (
        f"{method} {target['path']} HTTP/1.1\r\n"
        f"Host: {target['host_header']}\r\n"
        "User-Agent: ip-to-qr/1.0\r\n"
        "Connection: close\r\n\r\n"
    ).encode("utf-8")


def probe_target_via_proxy(ip_data, target, http_method, timeout=6):
    try:
        port = int(ip_data["port"])
    except ValueError:
        return False, None

    if port <= 0 or port > 65535:
        return False, None

    user_bytes = ip_data["user"].encode("utf-8")
    pwd_bytes = ip_data["pwd"].encode("utf-8")
    if len(user_bytes) > 255 or len(pwd_bytes) > 255:
        return False, None

    methods = [0x00]
    if user_bytes or pwd_bytes:
        methods.append(0x02)

    start = time.perf_counter()

    try:
        with socket.create_connection((ip_data["ip"], port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(bytes([0x05, len(methods), *methods]))
            version, selected_method = recv_exact(sock, 2)
            if version != 0x05:
                return False, None
            if selected_method == 0xFF:
                return False, None

            if selected_method == 0x02:
                auth_packet = (
                    bytes([0x01, len(user_bytes)])
                    + user_bytes
                    + bytes([len(pwd_bytes)])
                    + pwd_bytes
                )
                sock.sendall(auth_packet)
                auth_version, auth_status = recv_exact(sock, 2)
                if auth_version != 0x01 or auth_status != 0x00:
                    return False, None

            request = build_socks5_connect_request(target["host"], target["port"])
            sock.sendall(request)
            reply = recv_exact(sock, 4)
            if reply[0] != 0x05:
                return False, None
            if reply[1] != 0x00:
                return False, None

            atyp = reply[3]
            if atyp == 0x01:
                recv_exact(sock, 6)
            elif atyp == 0x03:
                domain_length = recv_exact(sock, 1)[0]
                recv_exact(sock, domain_length + 2)
            elif atyp == 0x04:
                recv_exact(sock, 18)
            else:
                return False, None

            request_sock = sock
            if target["scheme"] == "https":
                context = ssl.create_default_context()
                request_sock = context.wrap_socket(sock, server_hostname=target["host"])
                request_sock.settimeout(timeout)

            request_sock.sendall(build_http_probe_request(target, http_method))
            status_line = recv_until(request_sock).split(b"\r\n", 1)[0].decode(
                "iso-8859-1", "replace"
            )
            if not status_line.startswith("HTTP/"):
                return False, None

            parts = status_line.split(" ", 2)
            status_code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            if status_code in {405, 501} and http_method == "HEAD":
                return False, None

            latency_ms = max(1, round((time.perf_counter() - start) * 1000))
            return True, latency_ms
    except (ValueError, ssl.SSLError, socket.timeout, ConnectionRefusedError, OSError):
        return False, None


def test_proxy_connectivity(ip_data, target, timeout=6):
    success, latency_ms = probe_target_via_proxy(ip_data, target, "HEAD", timeout)
    if success:
        return True, latency_ms, "连通"

    success, latency_ms = probe_target_via_proxy(ip_data, target, "GET", timeout)
    if success:
        return True, latency_ms, "连通"

    return False, None, "不通"


def update_test_controls():
    state = "disabled" if bulk_test_running else "normal"
    test_button.config(state=state)


def set_row_test_result(item_id, latency, status):
    row = rows.get(item_id)
    if not row:
        return

    row["latency"] = latency
    row["test_status"] = status
    refresh_row(item_id)

    if current_preview_item_id == item_id:
        preview_meta_var.set(build_preview_meta(row))


def prepare_rows_for_test(item_ids, target_display):
    for item_id in item_ids:
        row = rows.get(item_id)
        if not row:
            continue
        row["target_display"] = target_display
        set_row_test_result(item_id, "-", "测试中")


def run_connectivity_tests(item_ids, target, source):
    success_count = 0

    max_workers = min(32, max(1, len(item_ids)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        for item_id in item_ids:
            row = rows.get(item_id)
            if not row:
                continue
            future = executor.submit(
                test_proxy_connectivity,
                dict(row["ip_data"]),
                dict(target),
            )
            future_map[future] = item_id

        for future in as_completed(future_map):
            item_id = future_map[future]
            try:
                success, latency_ms, status = future.result()
            except Exception as exc:
                success, latency_ms, status = False, None, "不通"
            if success:
                success_count += 1
            latency_text = f"{latency_ms} ms" if latency_ms is not None else "-"
            test_result_queue.put(("result", item_id, latency_text, status))

    test_result_queue.put(("done", len(item_ids), success_count, source))


def start_proxy_test(item_ids, target, scope_label, source):
    global active_test_jobs, bulk_test_running

    if source == "bulk" and bulk_test_running:
        return

    prepare_rows_for_test(item_ids, target["display"])
    active_test_jobs += 1
    if source == "bulk":
        bulk_test_running = True
    update_test_controls()
    update_status(f"正在测试{scope_label} -> {target['display']}")

    worker = threading.Thread(
        target=run_connectivity_tests,
        args=(item_ids, target, source),
        daemon=True,
    )
    worker.start()


def test_all_proxies():
    item_ids = list(table.get_children())
    if not item_ids:
        messagebox.showinfo("提示", "当前没有可测试的代理。")
        return

    try:
        target = normalize_test_target(test_target_var.get())
    except ValueError as exc:
        messagebox.showwarning("提示", str(exc))
        return

    start_proxy_test(item_ids, target, f" {len(item_ids)} 条代理", "bulk")


def test_single_selected_proxy():
    if context_menu_item_id and context_menu_item_id in rows:
        item_ids = [context_menu_item_id]
    else:
        selected = list(table.selection())
        if not selected:
            messagebox.showinfo("提示", "请先选择一条要测试的代理。")
            return
        item_ids = [selected[0]]

    try:
        target = normalize_test_target(test_target_var.get())
    except ValueError as exc:
        messagebox.showwarning("提示", str(exc))
        return

    table.selection_set(item_ids[0])
    table.focus_set()
    start_proxy_test(item_ids, target, " 1 条代理", "single")


def process_test_queue():
    global active_test_jobs, bulk_test_running

    try:
        while True:
            message = test_result_queue.get_nowait()
            if message[0] == "result":
                _, item_id, latency, status = message
                set_row_test_result(item_id, latency, status)
            elif message[0] == "done":
                _, total_count, success_count, source = message
                active_test_jobs = max(0, active_test_jobs - 1)
                if source == "bulk":
                    bulk_test_running = False
                update_test_controls()
                update_status(f"测试完成: 连通 {success_count}/{total_count} 条")
    except queue.Empty:
        pass

    root.after(120, process_test_queue)


def handle_delete_key(_event):
    focused_widget = root.focus_get()
    widget_class = focused_widget.winfo_class() if focused_widget else ""
    if widget_class in {"Entry", "TEntry", "Text"}:
        return None

    if table.selection():
        delete_selected()
        return "break"

    return None


def handle_table_ctrl_a(event):
    select_all()
    return "break"


def handle_table_mousewheel(event):
    if event.delta:
        table.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    return None


def handle_table_double_click(event):
    item_id = table.identify_row(event.y)
    if item_id:
        table.focus_set()
        table.selection_set(item_id)
        show_qr_for_item(item_id)


def handle_table_select(_event):
    selected = table.selection()
    if not selected:
        return

    table.focus_set()
    show_qr_for_item(selected[0])


def show_table_context_menu(event):
    global context_menu_item_id

    context_menu_item_id = None
    item_id = table.identify_row(event.y)
    if item_id:
        context_menu_item_id = item_id
        table.focus_set()
        if item_id not in table.selection():
            table.selection_set(item_id)

    if table.selection():
        try:
            table_menu.tk_popup(event.x_root, event.y_root)
        finally:
            table_menu.grab_release()


def show_paste_placeholder():
    global paste_placeholder_visible

    paste_text.delete("1.0", tk.END)
    paste_text.insert("1.0", PASTE_PLACEHOLDER)
    paste_text.config(fg="#7a8696")
    paste_placeholder_visible = True


def hide_paste_placeholder():
    global paste_placeholder_visible

    if paste_placeholder_visible:
        paste_text.delete("1.0", tk.END)
        paste_text.config(fg="#1f2937")
        paste_placeholder_visible = False


def handle_paste_focus_in(_event):
    hide_paste_placeholder()


def handle_paste_focus_out(_event):
    if not paste_text.get("1.0", tk.END).strip():
        show_paste_placeholder()


def clear_paste_text():
    paste_text.delete("1.0", tk.END)
    show_paste_placeholder()
    update_status("已清空粘贴区")


def update_count():
    total = len(rows)
    count_var.set(f"共 {total} 条数据")


def update_status(message):
    status_var.set(message)
    root.update_idletasks()


def build_style():
    style = ttk.Style()
    available = style.theme_names()
    for theme_name in ("vista", "xpnative", "clam"):
        if theme_name in available:
            style.theme_use(theme_name)
            break

    root.option_add("*Font", "{Segoe UI} 10")
    root.configure(bg="#eef2f7")

    style.configure("App.TFrame", background="#eef2f7")
    style.configure("Card.TLabelframe", background="#ffffff")
    style.configure("Card.TLabelframe.Label", background="#ffffff", foreground="#22324a")
    style.configure("Card.TFrame", background="#ffffff")
    style.configure("Muted.TLabel", background="#ffffff", foreground="#5b6675")
    style.configure("Title.TLabel", background="#ffffff", foreground="#1f2a37", font=("Segoe UI", 11, "bold"))
    style.configure("Count.TLabel", background="#ffffff", foreground="#5b6675")
    style.configure("Treeview", rowheight=30, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))


def apply_initial_pane_layout():
    try:
        total_width = content_pane.winfo_width() or root.winfo_width()
        sash_position = max(700, total_width - 315)
        content_pane.sashpos(0, sash_position)
    except tk.TclError:
        return


root = tk.Tk()
root.title("智能 Socks5 二维码生成工具")
root.geometry("1100x700")
root.minsize(980, 620)

build_style()

main_frame = ttk.Frame(root, style="App.TFrame", padding=(12, 12, 12, 8))
main_frame.pack(fill="both", expand=True)

toolbar_frame = ttk.Frame(main_frame, style="App.TFrame")
toolbar_frame.pack(fill="x", pady=(0, 10))

ttk.Button(toolbar_frame, text="导入文件", command=import_data).pack(side="left")
ttk.Button(toolbar_frame, text="导入粘贴内容", command=import_pasted_data).pack(side="left", padx=(8, 0))
ttk.Button(toolbar_frame, text="预览二维码", command=preview_selected).pack(side="left", padx=(8, 0))
ttk.Label(toolbar_frame, text="测试网站", style="Count.TLabel").pack(side="left", padx=(18, 6))
test_target_var = tk.StringVar(value=DEFAULT_TEST_TARGET)
test_target_entry = ttk.Entry(toolbar_frame, textvariable=test_target_var, width=28)
test_target_entry.pack(side="left")
test_button = ttk.Button(toolbar_frame, text="测试全部代理", command=test_all_proxies)
test_button.pack(side="left", padx=(8, 0))
ttk.Button(toolbar_frame, text="全选", command=select_all).pack(side="left", padx=(18, 0))
ttk.Button(toolbar_frame, text="取消全选", command=deselect_all).pack(side="left", padx=(8, 0))
ttk.Button(toolbar_frame, text="删除选中", command=delete_selected).pack(side="left", padx=(8, 0))
ttk.Button(toolbar_frame, text="导出有效数据", command=export_valid_data).pack(side="left", padx=(8, 0))

content_pane = ttk.Panedwindow(main_frame, orient=tk.HORIZONTAL)
content_pane.pack(fill="both", expand=True)

left_panel = ttk.Frame(content_pane, style="App.TFrame")
right_panel = ttk.Frame(content_pane, style="App.TFrame")
right_panel.configure(width=300)
content_pane.add(left_panel, weight=6)
content_pane.add(right_panel, weight=2)

input_card = ttk.LabelFrame(left_panel, text="数据输入", style="Card.TLabelframe", padding=10)
input_card.pack(fill="x")

single_row = ttk.Frame(input_card, style="Card.TFrame")
single_row.pack(fill="x")

ttk.Label(single_row, text="单条输入", style="Muted.TLabel").pack(side="left")
single_entry = ttk.Entry(single_row)
single_entry.pack(side="left", fill="x", expand=True, padx=(10, 8))
ttk.Button(single_row, text="添加", command=add_single).pack(side="left")

paste_container = ttk.Frame(input_card, style="Card.TFrame")
paste_container.pack(fill="x", pady=(10, 0))

paste_text = tk.Text(
    paste_container,
    height=8,
    wrap="word",
    bd=1,
    relief="solid",
    padx=10,
    pady=10,
    font=("Segoe UI", 10),
    fg="#1f2937",
    bg="#fbfcfe",
    insertbackground="#1f2937",
)
paste_scrollbar = ttk.Scrollbar(paste_container, orient="vertical", command=paste_text.yview)
paste_text.configure(yscrollcommand=paste_scrollbar.set)
paste_text.pack(side="left", fill="x", expand=True)
paste_scrollbar.pack(side="right", fill="y")

paste_action_row = ttk.Frame(input_card, style="Card.TFrame")
paste_action_row.pack(fill="x", pady=(10, 0))

ttk.Button(paste_action_row, text="导入粘贴内容", command=import_pasted_data).pack(side="left")
ttk.Button(paste_action_row, text="清空输入框", command=clear_paste_text).pack(side="left", padx=(8, 0))
ttk.Label(
    paste_action_row,
    text="粘贴后说明文字会自动隐藏，清空后会自动恢复",
    style="Muted.TLabel",
).pack(side="right")

list_card = ttk.LabelFrame(left_panel, text="代理列表", style="Card.TLabelframe", padding=(8, 8, 8, 10))
list_card.pack(fill="both", expand=True, pady=(10, 0))

list_header = ttk.Frame(list_card, style="Card.TFrame")
list_header.pack(fill="x", pady=(0, 8))

count_var = tk.StringVar(value="共 0 条数据")
ttk.Label(list_header, textvariable=count_var, style="Title.TLabel").pack(side="left")
ttk.Label(list_header, text="双击行可直接预览二维码", style="Count.TLabel").pack(side="right")

table_frame = ttk.Frame(list_card, style="Card.TFrame")
table_frame.pack(fill="both", expand=True)

table_columns = ("endpoint", "user", "pwd", "date", "remarks", "latency", "status")
table_display_columns = ("endpoint", "latency", "status", "user", "pwd", "date", "remarks")
table = ttk.Treeview(
    table_frame,
    columns=table_columns,
    displaycolumns=table_display_columns,
    show="headings",
    selectmode="extended",
)

column_specs = {
    "endpoint": ("IP:端口", 150, False),
    "latency": ("延迟(ms)", 84, False),
    "status": ("连通", 86, False),
    "user": ("用户", 92, False),
    "pwd": ("密码", 92, False),
    "date": ("日期", 92, False),
    "remarks": ("备注", 190, True),
}

for column_name, (title, width, stretch) in column_specs.items():
    table.heading(column_name, text=title)
    table.column(column_name, width=width, stretch=stretch, anchor="w")

table_vscroll = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
table_hscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=table.xview)
table.configure(yscrollcommand=table_vscroll.set, xscrollcommand=table_hscroll.set)

table.grid(row=0, column=0, sticky="nsew")
table_vscroll.grid(row=0, column=1, sticky="ns")
table_hscroll.grid(row=1, column=0, sticky="ew")
table_frame.columnconfigure(0, weight=1)
table_frame.rowconfigure(0, weight=1)

table_menu = tk.Menu(root, tearoff=0)
table_menu.add_command(label="测试单条代理", command=test_single_selected_proxy)
table_menu.add_separator()
table_menu.add_command(label="删除选中", command=delete_selected)

preview_card = ttk.LabelFrame(right_panel, text="二维码预览", style="Card.TLabelframe", padding=12)
preview_card.pack(fill="x", anchor="n")

preview_title_var = tk.StringVar(value="等待选择")
preview_meta_var = tk.StringVar(value="从左侧列表选择一条数据，再点击“预览二维码”或直接双击。")

ttk.Label(preview_card, textvariable=preview_title_var, style="Title.TLabel").pack(anchor="w")
ttk.Label(preview_card, textvariable=preview_meta_var, style="Muted.TLabel", justify=tk.LEFT, wraplength=240).pack(
    anchor="w", pady=(6, 12)
)

preview_canvas = tk.Canvas(
    preview_card,
    width=240,
    height=240,
    bg="#ffffff",
    bd=1,
    relief="solid",
    highlightthickness=0,
)
preview_canvas.pack()
preview_canvas.create_text(120, 120, text="暂无二维码", fill="#7a8696", font=("Segoe UI", 11))

preview_link_row = ttk.Frame(preview_card, style="Card.TFrame")
preview_link_row.pack(fill="x", pady=(12, 6))

ttk.Label(preview_link_row, text="当前代理链接", style="Muted.TLabel").pack(side="left")
ttk.Button(preview_link_row, text="复制链接", command=copy_preview_url).pack(side="right")

preview_url_text = tk.Text(
    preview_card,
    height=4,
    wrap="word",
    bd=1,
    relief="solid",
    padx=8,
    pady=8,
    font=("Consolas", 9),
    bg="#fbfcfe",
    fg="#1f2937",
)
preview_url_text.insert("1.0", "代理链接将在这里显示")
preview_url_text.config(state="disabled")
preview_url_text.pack(fill="both")

status_var = tk.StringVar(value="就绪")
status_bar = ttk.Label(root, textvariable=status_var, anchor="w", padding=(14, 6))
status_bar.pack(fill="x", side="bottom")

show_paste_placeholder()
process_test_queue()
root.after(80, apply_initial_pane_layout)

single_entry.bind("<Return>", lambda event: add_single())
paste_text.bind("<FocusIn>", handle_paste_focus_in)
paste_text.bind("<FocusOut>", handle_paste_focus_out)
table.bind("<Double-1>", handle_table_double_click)
table.bind("<<TreeviewSelect>>", handle_table_select)
table.bind("<Button-3>", show_table_context_menu)
table.bind("<MouseWheel>", handle_table_mousewheel)
table.bind("<Control-a>", handle_table_ctrl_a)
table.bind("<Control-A>", handle_table_ctrl_a)
table.bind("<Delete>", handle_delete_key)
table.bind("<KP_Delete>", handle_delete_key)
root.bind_all("<Delete>", handle_delete_key, add="+")
root.bind_all("<KP_Delete>", handle_delete_key, add="+")

root.mainloop()
