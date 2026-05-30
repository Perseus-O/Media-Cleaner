"""
Media Cleaner v2 - Find, inspect, and delete media files on a selected drive.
Skips all Windows system folders. Safe for everyday use.
"""

import os
import sys
import shutil
import hashlib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime
import threading
from collections import defaultdict

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False



# MEDIA EXTENSIONS
# ─────────────────────────────────────────────

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif",
    ".heic", ".heif", ".avif", ".svg", ".ico", ".raw", ".cr2", ".nef",
    ".orf", ".sr2", ".arw", ".dng", ".psd", ".ai", ".eps", ".jfif",
}

VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".3gp", ".3g2", ".ogv", ".ts", ".mts", ".m2ts",
    ".vob", ".divx", ".xvid", ".rmvb", ".rm", ".asf", ".f4v",
}

AUDIO_EXTS = {
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus",
    ".aiff", ".aif", ".ape", ".wv", ".mka", ".mid", ".midi", ".ra",
    ".amr", ".ac3", ".dts", ".tta", ".spx", ".caf",
}

ALL_MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS



# WINDOWS SYSTEM FOLDERS TO SKIP
# ─────────────────────────────────────────────

WINDOWS_SKIP_DIRS = {
    "windows", "program files", "program files (x86)", "programdata",
    "system volume information", "$recycle.bin", "recovery", "boot",
    "perflogs", "msocache", "windows.old", "winre", "$windows.~ws",
    "$windows.~bt", "bootmgr", "pagefile", "hiberfil",
}


def is_system_path(path: Path) -> bool:
    for part in path.parts:
        if part.lower().strip("\\/ ") in WINDOWS_SKIP_DIRS:
            return True
    return False


def format_size(bytes_val: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"


def get_category(ext: str) -> str:
    ext = ext.lower()
    if ext in IMAGE_EXTS:
        return "🖼 Image"
    if ext in VIDEO_EXTS:
        return "🎬 Video"
    if ext in AUDIO_EXTS:
        return "🎵 Audio"
    return "❓ Other"


def file_hash(path: Path, chunk=65536) -> str:
    """MD5 hash of first 64KB — fast enough for large drives."""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            h.update(f.read(chunk))
        return h.hexdigest()
    except OSError:
        return ""



# SCANNER
# ─────────────────────────────────────────────

class MediaScanner:
    def __init__(self, root_path: Path, progress_callback=None, status_callback=None):
        self.root_path = root_path
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.results = []
        self.cancelled = False
        self.scanned_count = 0
        self.error_count = 0

    def scan(self):
        self.results = []
        self.scanned_count = 0
        self.error_count = 0

        for dirpath, dirnames, filenames in os.walk(self.root_path, topdown=True):
            if self.cancelled:
                break

            current = Path(dirpath)

            dirnames[:] = [
                d for d in dirnames
                if not is_system_path(current / d)
                and not d.startswith(".")
            ]

            if self.status_callback:
                self.status_callback(f"Scanning: {str(current)[:90]}...")

            for filename in filenames:
                if self.cancelled:
                    break

                ext = Path(filename).suffix.lower()
                if ext not in ALL_MEDIA_EXTS:
                    continue

                filepath = current / filename
                try:
                    stat = filepath.stat()
                    self.results.append({
                        "path": filepath,
                        "name": filename,
                        "ext": ext,
                        "category": get_category(ext),
                        "size": stat.st_size,
                        "size_str": format_size(stat.st_size),
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "folder": str(current),
                        "is_duplicate": False,
                        "dup_group": -1,
                    })
                except (PermissionError, OSError):
                    self.error_count += 1

                self.scanned_count += 1
                if self.progress_callback:
                    self.progress_callback(self.scanned_count)

        return self.results

    def find_duplicates(self, status_callback=None):
        """Group files by (size, partial_hash). Mark duplicates in self.results."""
        
        size_groups = defaultdict(list)
        for f in self.results:
            size_groups[f["size"]].append(f)

        
        hash_groups = defaultdict(list)
        group_id = 0
        candidates = [f for group in size_groups.values() if len(group) > 1 for f in group]

        for i, f in enumerate(candidates):
            if status_callback:
                status_callback(f"Hashing {i+1}/{len(candidates)}: {f['name'][:60]}...")
            h = file_hash(f["path"])
            if h:
                hash_groups[h].append(f)

        
        dup_count = 0
        for h, group in hash_groups.items():
            if len(group) > 1:
                for f in group:
                    f["is_duplicate"] = True
                    f["dup_group"] = group_id
                    dup_count += 1
                group_id += 1

        return dup_count



# IMAGE PREVIEW WINDOW
# ─────────────────────────────────────────────

class PreviewWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Preview")
        self.geometry("520x480")
        self.configure(bg="#16213e")
        self.resizable(True, True)

        self._photo = None
        self._no_preview_label = None
        self._name_label = tk.Label(self, text="", bg="#16213e", fg="#aaa",
                                    font=("Segoe UI", 9), wraplength=500)
        self._name_label.pack(pady=(6, 2))

        self._canvas = tk.Canvas(self, bg="#16213e", highlightthickness=0)
        self._canvas.pack(fill="both", expand=True, padx=8, pady=8)

        self._msg = tk.Label(self._canvas, text="", bg="#16213e", fg="#777",
                             font=("Segoe UI", 11))
        self._canvas.create_window(260, 220, window=self._msg)

        self._show_placeholder("Click an image row to preview it here.")

    def _show_placeholder(self, msg):
        self._canvas.delete("img")
        self._msg.config(text=msg)

    def show_image(self, path: Path):
        self._name_label.config(text=str(path))
        if not PIL_AVAILABLE:
            self._show_placeholder("Install Pillow for image preview:\npip install Pillow")
            return

        ext = path.suffix.lower()
        if ext not in IMAGE_EXTS or ext in {".svg", ".raw", ".cr2", ".nef", ".orf",
                                              ".sr2", ".arw", ".dng", ".psd", ".ai", ".eps"}:
            self._show_placeholder(f"Preview not supported for {ext} files.")
            return

        try:
            img = Image.open(path)
            img.thumbnail((500, 420), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(img)
            self._canvas.delete("all")
            w = self._canvas.winfo_width() or 504
            h = self._canvas.winfo_height() or 430
            self._canvas.create_image(w // 2, h // 2, image=self._photo, anchor="center", tags="img")
            self._msg = tk.Label(self._canvas, text="", bg="#16213e")
        except Exception as e:
            self._show_placeholder(f"Could not open image:\n{e}")



# MAIN GUI
# ─────────────────────────────────────────────

class MediaCleanerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Media Cleaner v2")
        self.root.geometry("1200x740")
        self.root.configure(bg="#1a1a2e")
        self.root.resizable(True, True)

        self.scanner = None
        self.scan_thread = None
        self.all_files = []
        self.filtered_files = []
        self.selected_drive = tk.StringVar()
        self.filter_var = tk.StringVar(value="All")
        self.search_var = tk.StringVar()
        self.show_dupes_only = tk.BooleanVar(value=False)
        self.search_var.trace_add("write", lambda *a: self.apply_filter())

        self._sort_col = "size"
        self._sort_reverse = True

        self.preview_win = None
        self.checked_items = {}

        self._build_ui()

 
    # STYLES
    # ─────────────────────────────────────────

    def _apply_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
            background="#16213e", foreground="#e0e0e0",
            rowheight=24, fieldbackground="#16213e",
            font=("Consolas", 10),
        )
        style.configure("Treeview.Heading",
            background="#0f3460", foreground="#e0e0e0",
            relief="flat", font=("Segoe UI", 10, "bold"),
        )
        style.map("Treeview", background=[("selected", "#e94560")])
        style.configure("TButton",
            background="#0f3460", foreground="#e0e0e0",
            padding=6, relief="flat", font=("Segoe UI", 10),
        )
        style.map("TButton", background=[("active", "#e94560")])
        style.configure("Accent.TButton",
            background="#e94560", foreground="#ffffff",
            padding=6, relief="flat", font=("Segoe UI", 10, "bold"),
        )
        style.map("Accent.TButton", background=[("active", "#c73652")])

    
    # UI BUILDER
    # ─────────────────────────────────────────

    def _build_ui(self):
        self._apply_styles()

        
        top = tk.Frame(self.root, bg="#0f3460", pady=10, padx=14)
        top.pack(fill="x")

        tk.Label(top, text="🎯 Media Cleaner v2", font=("Segoe UI", 16, "bold"),
                 bg="#0f3460", fg="#e94560").pack(side="left")

        tk.Label(top, text="Drive:", bg="#0f3460", fg="#e0e0e0",
                 font=("Segoe UI", 10)).pack(side="left", padx=(20, 4))

        drives = self._get_drives()
        self.drive_combo = ttk.Combobox(top, textvariable=self.selected_drive,
                                        values=drives, width=8, state="readonly")
        if drives:
            self.drive_combo.set(drives[0])
        self.drive_combo.pack(side="left", padx=(0, 8))

        ttk.Button(top, text="📂 Custom Folder", command=self.pick_folder).pack(side="left", padx=4)
        self.scan_btn = ttk.Button(top, text="🔍 Scan", command=self.start_scan)
        self.scan_btn.pack(side="left", padx=4)
        self.cancel_btn = ttk.Button(top, text="⛔ Cancel", command=self.cancel_scan, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)

        self.dup_btn = ttk.Button(top, text="🔁 Find Duplicates", command=self.find_duplicates, state="disabled")
        self.dup_btn.pack(side="left", padx=(16, 4))

        tk.Checkbutton(top, text="Dupes only", variable=self.show_dupes_only,
                       command=self.apply_filter,
                       bg="#0f3460", fg="#e0e0e0", selectcolor="#1a1a2e",
                       activebackground="#0f3460", activeforeground="#e94560",
                       font=("Segoe UI", 10)).pack(side="left", padx=4)

        ttk.Button(top, text="👁 Preview", command=self.toggle_preview).pack(side="right", padx=4)

        
        fbar = tk.Frame(self.root, bg="#1a1a2e", pady=6, padx=14)
        fbar.pack(fill="x")

        tk.Label(fbar, text="Filter:", bg="#1a1a2e", fg="#aaa",
                 font=("Segoe UI", 10)).pack(side="left")

        for label in ["All", "🖼 Image", "🎬 Video", "🎵 Audio"]:
            tk.Radiobutton(fbar, text=label, variable=self.filter_var, value=label,
                           command=self.apply_filter,
                           bg="#1a1a2e", fg="#e0e0e0", selectcolor="#0f3460",
                           activebackground="#1a1a2e", activeforeground="#e94560",
                           font=("Segoe UI", 10)).pack(side="left", padx=8)

        tk.Label(fbar, text="Search:", bg="#1a1a2e", fg="#aaa",
                 font=("Segoe UI", 10)).pack(side="left", padx=(20, 4))

        search_entry = tk.Entry(fbar, textvariable=self.search_var,
                                bg="#16213e", fg="#e0e0e0", insertbackground="white",
                                relief="flat", font=("Consolas", 10), width=24)
        search_entry.pack(side="left")

        self.count_label = tk.Label(fbar, text="", bg="#1a1a2e", fg="#aaa",
                                    font=("Segoe UI", 10))
        self.count_label.pack(side="right", padx=8)

        
        tree_frame = tk.Frame(self.root, bg="#1a1a2e")
        tree_frame.pack(fill="both", expand=True, padx=14, pady=(0, 4))

        columns = ("select", "name", "category", "size", "modified", "folder", "dup")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")

        
        self.tree.heading("select",   text="☑", anchor="center")
        self.tree.heading("name",     text="File Name",
                          command=lambda: self._sort("name", False))
        self.tree.heading("category", text="Type",
                          command=lambda: self._sort("category", False))
        self.tree.heading("size",     text="Size ↕",
                          command=lambda: self._sort("size", True))
        self.tree.heading("modified", text="Modified",
                          command=lambda: self._sort("modified", False))
        self.tree.heading("folder",   text="Folder",
                          command=lambda: self._sort("folder", False))
        self.tree.heading("dup",      text="Dup", anchor="center")

        self.tree.column("select",   width=38,  anchor="center", stretch=False)
        self.tree.column("name",     width=240, anchor="w")
        self.tree.column("category", width=90,  anchor="center")
        self.tree.column("size",     width=90,  anchor="e")
        self.tree.column("modified", width=130, anchor="center")
        self.tree.column("folder",   width=360, anchor="w")
        self.tree.column("dup",      width=40,  anchor="center", stretch=False)

        self.tree.tag_configure("duplicate", foreground="#f4a261")
        self.tree.tag_configure("even",      background="#16213e")
        self.tree.tag_configure("odd",       background="#1a2540")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Double-1>", self.on_double_click)

        
        bot = tk.Frame(self.root, bg="#0f3460", pady=8, padx=14)
        bot.pack(fill="x")

        self.status_label = tk.Label(bot, text="Select a drive and click Scan.",
                                     bg="#0f3460", fg="#aaa", font=("Segoe UI", 10))
        self.status_label.pack(side="left")

        self.sel_label = tk.Label(bot, text="", bg="#0f3460", fg="#e94560",
                                  font=("Segoe UI", 10, "bold"))
        self.sel_label.pack(side="left", padx=20)

        ttk.Button(bot, text="✅ Select All",   command=self.select_all).pack(side="right", padx=4)
        ttk.Button(bot, text="❌ Deselect All", command=self.deselect_all).pack(side="right", padx=4)
        ttk.Button(bot, text="☑ Select Dupes", command=self.select_dupes).pack(side="right", padx=4)

        self.move_btn = ttk.Button(bot, text="📁 Move to Folder",
                                   command=self.move_selected, state="disabled")
        self.move_btn.pack(side="right", padx=4)

        self.delete_btn = ttk.Button(bot, text="🗑 Delete Selected",
                                     command=self.delete_selected, state="disabled",
                                     style="Accent.TButton")
        self.delete_btn.pack(side="right", padx=4)

        self.progress_bar = ttk.Progressbar(bot, mode="indeterminate", length=140)

    
    # DRIVE / FOLDER
    # ─────────────────────────────────────────

    def _get_drives(self):
        drives = []
        if sys.platform == "win32":
            import string
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append(drive)
        else:
            drives = ["/"]
        return drives

    def pick_folder(self):
        folder = filedialog.askdirectory(title="Select a folder to scan")
        if folder:
            self.selected_drive.set(folder)

    
    # PREVIEW WINDOW
    # ─────────────────────────────────────────

    def toggle_preview(self):
        if self.preview_win and self.preview_win.winfo_exists():
            self.preview_win.destroy()
            self.preview_win = None
        else:
            self.preview_win = PreviewWindow(self.root)

    def _maybe_preview(self, path: Path):
        if self.preview_win and self.preview_win.winfo_exists():
            ext = path.suffix.lower()
            if ext in IMAGE_EXTS:
                self.preview_win.show_image(path)

    
    # SCAN
    # ─────────────────────────────────────────

    def start_scan(self):
        path_str = self.selected_drive.get().strip()
        if not path_str:
            messagebox.showwarning("No Drive", "Please select a drive or folder first.")
            return

        scan_path = Path(path_str)
        if not scan_path.exists():
            messagebox.showerror("Not Found", f"Path does not exist:\n{path_str}")
            return

        self.tree.delete(*self.tree.get_children())
        self.checked_items.clear()
        self.all_files.clear()
        self.filtered_files.clear()
        self.count_label.config(text="")
        self.sel_label.config(text="")
        self.delete_btn.config(state="disabled")
        self.move_btn.config(state="disabled")
        self.dup_btn.config(state="disabled")
        self.scan_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress_bar.pack(side="left", padx=12)
        self.progress_bar.start(10)

        self.scanner = MediaScanner(
            scan_path,
            progress_callback=self._on_progress,
            status_callback=self._on_status,
        )

        self.scan_thread = threading.Thread(target=self._run_scan, daemon=True)
        self.scan_thread.start()

    def _run_scan(self):
        results = self.scanner.scan()
        self.root.after(0, self._scan_done, results)

    def _on_progress(self, count):
        self.root.after(0, lambda: self.status_label.config(
            text=f"Found {count} media file(s)..."
        ))

    def _on_status(self, msg):
        self.root.after(0, lambda: self.status_label.config(text=msg))

    def _scan_done(self, results):
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.scan_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")

        status = (f"Scan cancelled. Found {len(results)} file(s)."
                  if self.scanner.cancelled
                  else f"Scan complete — {len(results)} media file(s) found. "
                       f"({self.scanner.error_count} inaccessible)")
        self.status_label.config(text=status)

        self.all_files = results
        self.apply_filter()

        if results:
            self.delete_btn.config(state="normal")
            self.move_btn.config(state="normal")
            self.dup_btn.config(state="normal")

    def cancel_scan(self):
        if self.scanner:
            self.scanner.cancelled = True
        self.cancel_btn.config(state="disabled")
        self.status_label.config(text="Cancelling...")

    
    # DUPLICATE FINDER
    # ─────────────────────────────────────────

    def find_duplicates(self):
        if not self.all_files:
            return

        self.dup_btn.config(state="disabled")
        self.scan_btn.config(state="disabled")
        self.progress_bar.pack(side="left", padx=12)
        self.progress_bar.start(10)

        def _run():
            count = self.scanner.find_duplicates(
                status_callback=lambda m: self.root.after(0, lambda: self.status_label.config(text=m))
            )
            self.root.after(0, self._dup_done, count)

        threading.Thread(target=_run, daemon=True).start()

    def _dup_done(self, count):
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.scan_btn.config(state="normal")
        self.dup_btn.config(state="normal")
        self.status_label.config(
            text=f"Duplicate scan complete — {count} duplicate file(s) found (shown in orange)."
        )
        self.apply_filter()

    def select_dupes(self):
        for f in self.filtered_files:
            iid = str(f["path"])
            if f.get("is_duplicate"):
                self.checked_items[iid] = True
        self._populate_tree()
        self._update_sel_label()

    
    # SORT
    # ─────────────────────────────────────────

    def _sort(self, col: str, numeric: bool):
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = numeric  

        self.filtered_files.sort(
            key=lambda f: f[col] if not numeric else f[col],
            reverse=self._sort_reverse,
        )
        self._populate_tree()

        
        arrows = {"name": "", "category": "", "size": "", "modified": "", "folder": ""}
        arrows[col] = " ↓" if self._sort_reverse else " ↑"
        self.tree.heading("name",     text=f"File Name{arrows['name']}")
        self.tree.heading("category", text=f"Type{arrows['category']}")
        self.tree.heading("size",     text=f"Size{arrows['size']}")
        self.tree.heading("modified", text=f"Modified{arrows['modified']}")
        self.tree.heading("folder",   text=f"Folder{arrows['folder']}")

    
    # FILTER & DISPLAY
    # ─────────────────────────────────────────

    def apply_filter(self):
        category_filter = self.filter_var.get()
        search_text = self.search_var.get().lower().strip()
        dupes_only = self.show_dupes_only.get()

        self.filtered_files = []
        for f in self.all_files:
            if category_filter != "All" and f["category"] != category_filter:
                continue
            if search_text and search_text not in f["name"].lower() and search_text not in f["folder"].lower():
                continue
            if dupes_only and not f.get("is_duplicate"):
                continue
            self.filtered_files.append(f)

        self._populate_tree()
        total_size = sum(f["size"] for f in self.filtered_files)
        dup_count = sum(1 for f in self.filtered_files if f.get("is_duplicate"))
        dup_str = f"  |  🔁 {dup_count} dupes" if dup_count else ""
        self.count_label.config(
            text=f"{len(self.filtered_files)} file(s)  |  {format_size(total_size)}{dup_str}"
        )
        self._update_sel_label()

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, f in enumerate(self.filtered_files):
            iid = str(f["path"])
            checked = self.checked_items.get(iid, False)
            check_str = "☑" if checked else "☐"
            dup_str = "🔁" if f.get("is_duplicate") else ""
            row_tag = "duplicate" if f.get("is_duplicate") else ("even" if i % 2 == 0 else "odd")
            self.tree.insert("", "end", iid=iid, values=(
                check_str,
                f["name"],
                f["category"],
                f["size_str"],
                f["modified"],
                f["folder"],
                dup_str,
            ), tags=(row_tag,))

    
    # SELECTION & CLICKS
    # ─────────────────────────────────────────

    def on_tree_click(self, event):
        col = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if not iid:
            return

        if col == "#1":  # checkbox
            current = self.checked_items.get(iid, False)
            self.checked_items[iid] = not current
            self.tree.set(iid, "select", "☑" if not current else "☐")
            self._update_sel_label()
        else:
            
            self._maybe_preview(Path(iid))

    def on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        try:
            os.startfile(Path(iid).parent)
        except Exception:
            pass

    def select_all(self):
        for f in self.filtered_files:
            self.checked_items[str(f["path"])] = True
        self._populate_tree()
        self._update_sel_label()

    def deselect_all(self):
        for f in self.filtered_files:
            self.checked_items[str(f["path"])] = False
        self._populate_tree()
        self._update_sel_label()

    def _get_selected(self):
        return [f for f in self.filtered_files if self.checked_items.get(str(f["path"]), False)]

    def _update_sel_label(self):
        sel = self._get_selected()
        if sel:
            total = sum(f["size"] for f in sel)
            self.sel_label.config(text=f"{len(sel)} selected  |  {format_size(total)} will be freed")
        else:
            self.sel_label.config(text="")

    def _remove_from_lists(self, paths_removed: set):
        self.all_files = [f for f in self.all_files if f["path"] not in paths_removed]
        self.checked_items = {k: v for k, v in self.checked_items.items()
                              if Path(k) not in paths_removed}
        self.apply_filter()

    
    # MOVE TO FOLDER
    # ─────────────────────────────────────────

    def move_selected(self):
        selected = self._get_selected()
        if not selected:
            messagebox.showinfo("Nothing Selected", "Check the ☐ boxes next to files you want to move.")
            return

        dest = filedialog.askdirectory(title="Move selected files to...")
        if not dest:
            return

        dest_path = Path(dest)
        total_size = sum(f["size"] for f in selected)

        confirm = messagebox.askyesno(
            "Confirm Move",
            f"Move {len(selected)} file(s) ({format_size(total_size)}) to:\n{dest_path}\n\nContinue?",
        )
        if not confirm:
            return

        moved = 0
        failed = []
        moved_paths = set()

        for f in selected:
            try:
                target = dest_path / f["name"]
                
                counter = 1
                while target.exists():
                    stem = f["path"].stem
                    target = dest_path / f"{stem}_{counter}{f['ext']}"
                    counter += 1
                shutil.move(str(f["path"]), str(target))
                moved += 1
                moved_paths.add(f["path"])
            except Exception as e:
                failed.append((f["name"], str(e)))

        self._remove_from_lists(moved_paths)

        msg = f"✅ Moved {moved} file(s) to:\n{dest_path}"
        if failed:
            msg += f"\n\n⚠️ Failed {len(failed)} file(s):\n"
            msg += "\n".join(f"• {n}: {e}" for n, e in failed[:10])
        messagebox.showinfo("Move Complete", msg)
        self.status_label.config(text=f"Moved {moved} file(s).")

    
    # DELETE
    # ─────────────────────────────────────────

    def delete_selected(self):
        selected = self._get_selected()
        if not selected:
            messagebox.showinfo("Nothing Selected", "Check the ☐ boxes next to files you want to delete.")
            return

        total_size = sum(f["size"] for f in selected)
        confirm = messagebox.askyesno(
            "⚠️ Confirm Permanent Deletion",
            f"Permanently delete {len(selected)} file(s)?\n"
            f"Space freed: {format_size(total_size)}\n\n"
            f"This CANNOT be undone! Consider 'Move to Folder' instead.\n\nContinue?",
            icon="warning",
        )
        if not confirm:
            return

        deleted = 0
        failed = []
        deleted_paths = set()

        for f in selected:
            try:
                os.remove(f["path"])
                deleted += 1
                deleted_paths.add(f["path"])
            except Exception as e:
                failed.append((f["name"], str(e)))

        self._remove_from_lists(deleted_paths)

        msg = f"✅ Deleted {deleted} file(s), freed {format_size(total_size)}."
        if failed:
            msg += f"\n\n⚠️ Failed {len(failed)} file(s):\n"
            msg += "\n".join(f"• {n}: {e}" for n, e in failed[:10])
        messagebox.showinfo("Done", msg)
        self.status_label.config(text=f"Deleted {deleted} file(s).")



# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    root = tk.Tk()
    app = MediaCleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()