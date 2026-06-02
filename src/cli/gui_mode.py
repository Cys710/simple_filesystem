# -*- coding: utf-8 -*-
"""
Tkinter graphical mode for the simulated file system.

The GUI is intentionally a thin layer: most file actions are translated back
into shell commands, so permissions, login state, path handling and errors stay
consistent with command-line mode.
"""

from __future__ import annotations

import fnmatch
import posixpath
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
except ImportError as exc:  # pragma: no cover - depends on local Python install
    raise ImportError("tkinter is required for gui mode") from exc

from core.file_system import FileSystem, FileSystemError
from head import DIR_TYPE, FILE_TYPE


CommandExecutor = Callable[[str], tuple[bool, str]]


@dataclass(frozen=True)
class GuiEntry:
    name: str
    path: str
    type_id: int


class FileSystemGuiError(Exception):
    """Raised when graphical mode cannot be started."""


class FileSystemGui:
    def __init__(
        self,
        fs_getter: Callable[[], FileSystem | None],
        command_executor: CommandExecutor,
        *,
        disk_path_getter: Callable[[], Path] | None = None,
        command_logger: Callable[[str], None] | None = None,
        error_formatter: Callable[[str, str], str] | None = None,
    ):
        self.fs_getter = fs_getter
        self.command_executor = command_executor
        self.disk_path_getter = disk_path_getter
        self.command_logger = command_logger
        self.error_formatter = error_formatter
        self.current_path = "/"
        self.root: tk.Tk | None = None
        self.path_var: tk.StringVar | None = None
        self.user_var: tk.StringVar | None = None
        self.status_var: tk.StringVar | None = None
        self.search_var: tk.StringVar | None = None
        self.tree: ttk.Treeview | None = None
        self.entries: ttk.Treeview | None = None
        self._tree_paths: dict[str, str] = {}
        self._entry_paths: dict[str, str] = {}
        self._path_types: dict[str, int] = {}
        self._images: dict[str, tk.PhotoImage] = {}
        self._rename_editor: ttk.Entry | None = None
        self._user_menu: tk.Menu | None = None
        self._useradd_menu_index: int | None = None
        self._search_mode = False

    def run(self) -> None:
        if self.fs_getter() is None:
            raise FileSystemGuiError("file system is not mounted")
        self.root = tk.Tk()
        self.root.title(self._window_title())
        self.root.geometry("1080x640")
        self._create_images()
        self._build_ui()
        self.refresh()
        self.root.mainloop()

    def _build_ui(self) -> None:
        assert self.root is not None
        self.path_var = tk.StringVar()
        self.user_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")
        self.search_var = tk.StringVar()

        self._build_menu()
        self._build_toolbar()

        header = ttk.Frame(self.root, padding=(10, 6, 10, 0))
        header.pack(fill=tk.X)
        ttk.Label(header, textvariable=self.path_var).pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self.user_var).pack(side=tk.RIGHT)

        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=3)

        self.tree = ttk.Treeview(left, show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_open)
        self.tree.bind("<Button-3>", self._on_tree_context)

        self.entries = ttk.Treeview(
            right,
            columns=("type", "size", "mode", "owner", "inode"),
            show="tree headings",
            selectmode="browse",
        )
        self.entries.heading("#0", text="名称")
        self.entries.heading("type", text="类型")
        self.entries.heading("size", text="大小")
        self.entries.heading("mode", text="权限")
        self.entries.heading("owner", text="Owner")
        self.entries.heading("inode", text="inode")
        self.entries.column("#0", width=360, anchor=tk.W)
        self.entries.column("type", width=90, anchor=tk.CENTER)
        self.entries.column("size", width=90, anchor=tk.E)
        self.entries.column("mode", width=180, anchor=tk.CENTER)
        self.entries.column("owner", width=90, anchor=tk.CENTER)
        self.entries.column("inode", width=90, anchor=tk.CENTER)
        self.entries.pack(fill=tk.BOTH, expand=True)
        self.entries.bind("<Double-1>", self._on_entry_open)
        self.entries.bind("<Button-3>", self._on_entry_context)

        ttk.Label(
            self.root,
            textvariable=self.status_var,
            anchor=tk.W,
            relief=tk.SUNKEN,
            padding=(8, 4),
        ).pack(fill=tk.X)

    def _build_menu(self) -> None:
        assert self.root is not None
        menu = tk.Menu(self.root)

        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="挂载...", command=self.mount_disk)
        file_menu.add_command(label="格式化...", command=self.format_disk)
        file_menu.add_separator()
        file_menu.add_command(label="刷新", command=self.refresh)
        file_menu.add_command(label="退出图形模式", command=self.root.destroy)
        menu.add_cascade(label="文件", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="新建文件", command=self.new_file)
        edit_menu.add_command(label="新建文件夹", command=self.new_dir)
        edit_menu.add_command(label="打开", command=self.open_selected)
        edit_menu.add_command(label="编辑", command=self.edit_selected)
        edit_menu.add_command(label="重命名", command=self.rename_selected)
        edit_menu.add_command(label="删除", command=self.delete_selected)
        edit_menu.add_command(label="属性", command=self.properties_selected)
        menu.add_cascade(label="编辑", menu=edit_menu)

        search_menu = tk.Menu(menu, tearoff=False)
        search_menu.add_command(label="搜索当前目录", command=self.search)
        search_menu.add_command(label="清除搜索", command=self.clear_search)
        menu.add_cascade(label="搜索", menu=search_menu)

        user_menu = tk.Menu(menu, tearoff=False)
        user_menu.add_command(label="登录...", command=self.login)
        user_menu.add_command(label="注销", command=self.logout)
        user_menu.add_command(label="切换用户...", command=self.su)
        user_menu.add_command(label="新建用户...", command=self.useradd)
        self._useradd_menu_index = user_menu.index(tk.END)
        user_menu.add_command(label="修改密码...", command=self.passwd)
        menu.add_cascade(label="用户", menu=user_menu)
        self._user_menu = user_menu
        self.root.config(menu=menu)

    def _build_toolbar(self) -> None:
        assert self.root is not None
        bar = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        bar.pack(fill=tk.X)
        for text, command in (
            ("新建文件", self.new_file),
            ("新建文件夹", self.new_dir),
            ("打开", self.open_selected),
            ("编辑", self.edit_selected),
            ("删除", self.delete_selected),
            ("属性", self.properties_selected),
            ("上一级", self.go_up),
            ("刷新", self.refresh),
        ):
            ttk.Button(bar, text=text, command=command).pack(side=tk.LEFT, padx=(0, 6))

        search_box = ttk.Frame(bar)
        search_box.pack(side=tk.RIGHT)
        ttk.Entry(search_box, textvariable=self.search_var, width=24).pack(side=tk.LEFT)
        ttk.Button(search_box, text="搜索", command=self.search).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(search_box, text="清除", command=self.clear_search).pack(side=tk.LEFT, padx=(6, 0))

    def refresh(self) -> None:
        if not self._can_show_dir(self.current_path):
            try:
                self.current_path = self._fs().pwd()
            except FileSystemError:
                self.current_path = "/"
        self._search_mode = False
        self._update_header()
        self._refresh_tree()
        self._refresh_entries()
        self._set_status("已刷新")

    def mount_disk(self) -> None:
        initial = str(self.disk_path_getter()) if self.disk_path_getter else ""
        path = filedialog.askopenfilename(title="选择磁盘镜像", initialfile=initial)
        if path:
            self._run(["mount", path], refresh_tree=True)

    def format_disk(self) -> None:
        path = filedialog.asksaveasfilename(title="格式化磁盘镜像")
        if path and messagebox.askyesno("确认格式化", f"格式化会清空磁盘：\n{path}\n是否继续？"):
            self._run(["format", path], refresh_tree=True)

    def new_file(self) -> None:
        self._create_default_entry(is_dir=False)

    def new_dir(self) -> None:
        self._create_default_entry(is_dir=True)

    def open_selected(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        if self._is_dir(path):
            self._run(["cd", path])
            return
        ok, output = self._run(["cat", path], refresh=False)
        if ok:
            self._show_text(f"查看：{path}", output, readonly=True)

    def edit_selected(self) -> None:
        path = self._selected_path()
        if path is None or self._is_dir(path):
            self._set_status("请选择一个文件")
            return
        if not (self._can_read_path(path) and self._can_write_path(path)):
            self._set_status("当前用户没有编辑该文件的权限")
            return
        ok, output = self._run(["cat", path], refresh=False)
        if ok:
            self._show_text(f"编辑：{path}", output, readonly=False, save_path=path)

    def rename_selected(self) -> None:
        path = self._selected_path()
        if path is None or path == "/":
            return
        parent_path = self._parent_path(path)
        if not (self._can_write_path(parent_path) and self._can_execute_path(parent_path)):
            self._set_status("当前用户没有重命名该项目的权限")
            return
        old_name = posixpath.basename(path.rstrip("/"))
        self._begin_inline_rename(path, old_name)

    def delete_selected(self) -> None:
        path = self._selected_path()
        if path is None or path == "/":
            return
        parent_path = self._parent_path(path)
        if not (self._can_write_path(parent_path) and self._can_execute_path(parent_path)):
            self._set_status("当前用户没有删除该项目的权限")
            return
        if not messagebox.askyesno("确认删除", f"删除 {path}？"):
            return
        if self._is_dir(path):
            recursive = messagebox.askyesno("目录删除", "是否递归删除该目录？")
            argv = ["rmdir", "-r", path] if recursive else ["rmdir", path]
        else:
            argv = ["rm", path]
        self._run(argv)

    def link_selected(self) -> None:
        path = self._selected_path()
        if path is None or self._is_dir(path):
            self._set_status("请选择一个文件创建硬链接")
            return
        if not (self._can_write_path(self.current_path) and self._can_execute_path(self.current_path)):
            self._set_status("当前用户没有在当前目录创建硬链接的权限")
            return
        default = self._default_name(f"{posixpath.basename(path)}-link")
        name = self._ask_name("创建硬链接", "链接名称：", default)
        if name:
            self._run(["ln", path, self._child_path(name)])

    def chmod_selected(self) -> None:
        if not self._can_change_permissions():
            self._set_status("只有 root 用户可以修改权限")
            return
        path = self._selected_path()
        if path is None:
            return
        current = str(self._stat(path).get("mode", ""))
        mode = self._ask_name(
            "修改权限",
            (
                "请输入两位八进制权限。\n"
                "第一位表示所有者，第二位表示其他用户。\n"
                "4=读，2=写，1=执行，可以相加。\n"
                "例如：64 表示所有者可读/可写，其他用户只读；"
                "70 表示所有者可读/可写/可执行，其他用户无权限。"
            ),
            current,
        )
        if mode:
            self._run(["chmod", mode, path])

    def properties_selected(self) -> None:
        path = self._selected_path() or self.current_path
        self._show_properties(path)

    def _create_default_entry(self, *, is_dir: bool) -> None:
        if not (self._can_write_path(self.current_path) and self._can_execute_path(self.current_path)):
            self._set_status("当前用户没有在当前目录中新建项目的权限")
            return
        default_name = self._default_name("新建文件夹" if is_dir else "新建文件.txt")
        path = self._child_path(default_name)
        ok, _output = self._run(["mkdir" if is_dir else "touch", path])
        if ok:
            self._select_entry_path(path)
            self._begin_inline_rename(path, default_name)

    def search(self) -> None:
        assert self.search_var is not None
        pattern = self.search_var.get().strip()
        if not pattern:
            pattern = simpledialog.askstring("搜索", "输入匹配模式，例如 *.txt：") or ""
            self.search_var.set(pattern)
        if not pattern:
            return
        self._log_command(["find", self.current_path, pattern])
        matches = self._find_entries(self.current_path, pattern)
        self._search_mode = True
        self._refresh_entries(matches)
        self._set_status(f"搜索 {pattern}: {len(matches)} 项")

    def clear_search(self) -> None:
        assert self.search_var is not None
        self.search_var.set("")
        self._search_mode = False
        self._refresh_entries()
        self._set_status("已清除搜索")

    def go_up(self) -> None:
        if self.current_path != "/":
            self._run(["cd", posixpath.dirname(self.current_path.rstrip("/")) or "/"])

    def login(self) -> None:
        username = simpledialog.askstring("登录", "用户名：")
        if not username:
            return
        password = simpledialog.askstring("登录", "密码：", show="*")
        if password is None:
            return
        self._log_command(["login", username])
        try:
            fs = self._fs()
            fs.login(username, password)
            if fs.current_user and fs.current_user.home_path:
                fs.cd(fs.current_user.home_path)
            self.current_path = fs.pwd()
            self.refresh()
            self._set_status(f"已登录：{username}")
        except FileSystemError as exc:
            self._show_error("login", exc)

    def logout(self) -> None:
        self._run(["logout"])

    def su(self) -> None:
        username = simpledialog.askstring("切换用户", "用户名：")
        if not username:
            return
        password = simpledialog.askstring("切换用户", "密码：", show="*")
        if password is None:
            return
        self._log_command(["su", username])
        try:
            self._fs().su(username, password)
            self.current_path = self._fs().pwd()
            self.refresh()
            self._set_status(f"已切换到：{username}")
        except FileSystemError as exc:
            self._show_error("su", exc)

    def useradd(self) -> None:
        if not self._can_manage_users():
            self._set_status("只有 root 用户可以新建用户")
            return
        username = simpledialog.askstring("新建用户", "用户名：")
        if not username:
            return
        password = simpledialog.askstring("新建用户", "密码：", show="*")
        if password is None:
            return
        self._log_command(["useradd", username])
        try:
            self._fs().useradd(username, password)
            self.refresh()
            self._set_status(f"已创建用户：{username}")
        except FileSystemError as exc:
            self._show_error("useradd", exc)

    def passwd(self) -> None:
        username = simpledialog.askstring("修改密码", "用户名（留空表示当前用户）：")
        password = simpledialog.askstring("修改密码", "新密码：", show="*")
        if password is None:
            return
        argv = ["passwd"] + ([username] if username else [])
        self._log_command(argv)
        try:
            self._fs().passwd(username or self._fs().whoami(), password)
            self._set_status("密码已更新")
        except FileSystemError as exc:
            self._show_error("passwd", exc)

    def _refresh_tree(self) -> None:
        assert self.tree is not None
        self.tree.delete(*self.tree.get_children())
        self._tree_paths.clear()
        root_id = self.tree.insert("", tk.END, text="/", image=self._images["folder_open"], open=True)
        self._tree_paths[root_id] = "/"
        self._fill_tree_node(root_id, "/")

    def _fill_tree_node(self, item_id: str, path: str) -> None:
        assert self.tree is not None
        for entry in self._entries(path):
            if entry.type_id != DIR_TYPE:
                continue
            child_id = self.tree.insert(
                item_id,
                tk.END,
                text=entry.name,
                image=self._images["folder"],
                open=entry.path == self.current_path,
            )
            self._tree_paths[child_id] = entry.path
            self._fill_tree_node(child_id, entry.path)

    def _refresh_entries(self, entries: list[GuiEntry] | None = None) -> None:
        assert self.entries is not None
        self.entries.delete(*self.entries.get_children())
        self._entry_paths.clear()
        self._path_types.clear()
        for entry in entries if entries is not None else self._entries(self.current_path):
            stat = self._stat(entry.path)
            image = self._images["folder"] if entry.type_id == DIR_TYPE else self._images["file"]
            item_id = self.entries.insert(
                "",
                tk.END,
                text=entry.path if self._search_mode else entry.name,
                image=image,
                values=(
                    "文件夹" if entry.type_id == DIR_TYPE else "文件",
                    self._size_text(stat),
                    self._permission_text(stat),
                    stat.get("owner_id", "-"),
                    stat.get("inode_id", "-"),
                ),
            )
            self._entry_paths[item_id] = entry.path
            self._path_types[entry.path] = entry.type_id

    def _refresh_entries_only(self) -> None:
        self._search_mode = False
        self._update_header()
        self._refresh_entries()

    def _on_tree_select(self, _event: object) -> None:
        path = self._selected_tree_path()
        if path:
            self.current_path = path
            self._search_mode = False
            self._update_header()
            self._refresh_entries()

    def _on_tree_open(self, _event: object) -> None:
        path = self._selected_tree_path()
        if path:
            self._run(["cd", path])

    def _on_entry_open(self, _event: object) -> None:
        self.open_selected()

    def _on_tree_context(self, event: tk.Event) -> None:
        assert self.tree is not None
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self.tree.selection_set(item_id)
            path = self._tree_paths.get(item_id, self.current_path)
            self.current_path = path
            self._update_header()
            self._refresh_entries()
        self._show_context_menu(event, target_path=self.current_path, is_background=True)

    def _on_entry_context(self, event: tk.Event) -> None:
        assert self.entries is not None
        item_id = self.entries.identify_row(event.y)
        if item_id:
            self.entries.selection_set(item_id)
            path = self._entry_paths.get(item_id)
            self._show_context_menu(event, target_path=path, is_background=False)
        else:
            self._show_context_menu(event, target_path=self.current_path, is_background=True)

    def _show_context_menu(
        self,
        event: tk.Event,
        *,
        target_path: str | None,
        is_background: bool,
    ) -> None:
        assert self.root is not None
        menu = tk.Menu(self.root, tearoff=False)
        if is_background:
            can_create = self._can_write_path(self.current_path) and self._can_execute_path(self.current_path)
            menu.add_command(
                label="新建文件",
                command=self.new_file,
                state=tk.NORMAL if can_create else tk.DISABLED,
            )
            menu.add_command(
                label="新建文件夹",
                command=self.new_dir,
                state=tk.NORMAL if can_create else tk.DISABLED,
            )
            menu.add_separator()
            menu.add_command(
                label="搜索此目录",
                command=self.search,
                state=tk.NORMAL if self._can_read_path(self.current_path) else tk.DISABLED,
            )
            menu.add_command(label="刷新", command=self.refresh)
            menu.tk_popup(event.x_root, event.y_root)
            return

        is_dir = bool(target_path and self._is_dir(target_path))
        parent_path = self._parent_path(target_path) if target_path else self.current_path
        can_read = bool(target_path and self._can_read_path(target_path))
        can_write_target = bool(target_path and self._can_write_path(target_path))
        can_write_parent = self._can_write_path(parent_path) and self._can_execute_path(parent_path)
        can_create_inside = bool(
            target_path
            and is_dir
            and self._can_write_path(target_path)
            and self._can_execute_path(target_path)
        )
        menu.add_command(
            label="打开",
            command=self.open_selected,
            state=tk.NORMAL if can_read else tk.DISABLED,
        )
        if not is_dir:
            menu.add_command(
                label="编辑",
                command=self.edit_selected,
                state=tk.NORMAL if can_read and can_write_target else tk.DISABLED,
            )
            menu.add_command(
                label="创建硬链接",
                command=self.link_selected,
                state=tk.NORMAL if can_write_parent else tk.DISABLED,
            )
        if is_dir:
            menu.add_command(
                label="在此目录中新建文件",
                command=lambda: self._new_inside(target_path, False),
                state=tk.NORMAL if can_create_inside else tk.DISABLED,
            )
            menu.add_command(
                label="在此目录中新建文件夹",
                command=lambda: self._new_inside(target_path, True),
                state=tk.NORMAL if can_create_inside else tk.DISABLED,
            )
        menu.add_separator()
        menu.add_command(
            label="重命名",
            command=self.rename_selected,
            state=tk.NORMAL if can_write_parent else tk.DISABLED,
        )
        menu.add_command(
            label="删除",
            command=self.delete_selected,
            state=tk.NORMAL if can_write_parent else tk.DISABLED,
        )
        menu.add_command(
            label="修改权限",
            command=self.chmod_selected,
            state=tk.NORMAL if self._can_change_permissions() else tk.DISABLED,
        )
        menu.add_command(label="属性", command=self.properties_selected)
        menu.tk_popup(event.x_root, event.y_root)

    def _new_inside(self, path: str | None, is_dir: bool) -> None:
        if not path:
            return
        self.current_path = path
        self._update_header()
        self.new_dir() if is_dir else self.new_file()

    def _selected_tree_path(self) -> str | None:
        assert self.tree is not None
        selection = self.tree.selection()
        return self._tree_paths.get(selection[0]) if selection else None

    def _selected_path(self) -> str | None:
        assert self.entries is not None
        selection = self.entries.selection()
        if selection:
            return self._entry_paths.get(selection[0])
        return self._selected_tree_path()

    def _select_entry_path(self, path: str) -> None:
        assert self.entries is not None
        for item_id, item_path in self._entry_paths.items():
            if item_path == path:
                self.entries.selection_set(item_id)
                self.entries.focus(item_id)
                self.entries.see(item_id)
                return

    def _begin_inline_rename(self, path: str, initial: str) -> None:
        assert self.entries is not None
        assert self.root is not None
        self._destroy_rename_editor()
        item_id = None
        for current_item_id, item_path in self._entry_paths.items():
            if item_path == path:
                item_id = current_item_id
                break
        if item_id is None:
            return

        self.entries.selection_set(item_id)
        self.entries.focus(item_id)
        self.entries.see(item_id)
        bbox = self.entries.bbox(item_id, "#0")
        if not bbox:
            return
        x, y, width, height = bbox
        editor = ttk.Entry(self.entries)
        editor.insert(0, initial)
        editor.select_range(0, tk.END)
        editor.focus_set()
        editor.place(x=x + 22, y=y, width=max(width - 22, 120), height=height)
        self._rename_editor = editor

        def commit(_event: object | None = None) -> None:
            new_name = editor.get().strip()
            self._destroy_rename_editor()
            if not new_name or new_name == initial:
                return
            if "/" in new_name:
                messagebox.showerror("重命名", "名称不能包含 /")
                return
            self._run(["rename", path, new_name])

        def cancel(_event: object | None = None) -> None:
            self._destroy_rename_editor()

        editor.bind("<Return>", commit)
        editor.bind("<Escape>", cancel)
        editor.bind("<FocusOut>", cancel)

    def _destroy_rename_editor(self) -> None:
        if self._rename_editor is not None:
            self._rename_editor.destroy()
            self._rename_editor = None

    def _run(
        self,
        argv: list[str],
        *,
        refresh: bool = True,
        refresh_tree: bool = False,
    ) -> tuple[bool, str]:
        command = shlex.join(argv)
        ok, output = self.command_executor(command)
        if ok and argv and argv[0] in {"cd", "format", "mount", "logout"}:
            try:
                self.current_path = self._fs().pwd()
            except FileSystemError:
                self.current_path = "/"
        if ok and refresh:
            self.refresh() if refresh_tree else self._refresh_entries_only()
        if not ok:
            self._set_status(output or "命令执行失败")
            if output:
                messagebox.showerror("命令失败", output)
        else:
            self._set_status(command)
        return ok, output

    def _log_command(self, argv: list[str]) -> None:
        if self.command_logger is not None:
            self.command_logger(shlex.join(argv))

    def _show_text(
        self,
        title: str,
        content: str,
        *,
        readonly: bool,
        save_path: str | None = None,
    ) -> None:
        assert self.root is not None
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry("720x480")
        text = tk.Text(window, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        text.insert("1.0", content)
        if readonly:
            text.configure(state=tk.DISABLED)
            return

        def save() -> None:
            assert save_path is not None
            data = text.get("1.0", tk.END).rstrip("\n")
            ok, _output = self._run(["write", save_path, data])
            if ok:
                window.destroy()

        ttk.Button(window, text="保存", command=save).pack(pady=(0, 8))

    def _show_properties(self, path: str) -> None:
        stat = self._stat(path)
        rows = [
            f"路径: {path}",
            f"类型: {stat.get('type', '-')}",
            f"inode: {stat.get('inode_id', '-')}",
            f"owner: {stat.get('owner_id', '-')}",
            f"当前用户权限: {self._permission_text(stat)}",
            f"权限模式: {self._permission_detail_text(stat.get('mode', '-'))}",
            f"大小: {stat.get('size', '-')} bytes",
        ]
        if self._is_dir(path):
            entries = self._entries(path)
            rows.append(f"包含项目: {len(entries)}")
        self._show_text(f"属性：{path}", "\n".join(rows), readonly=True)

    def _ask_name(self, title: str, prompt: str, initial: str) -> str | None:
        name = simpledialog.askstring(title, prompt, initialvalue=initial)
        if name is None:
            return None
        name = name.strip()
        if not name:
            messagebox.showerror(title, "名称不能为空")
            return None
        if "/" in name:
            messagebox.showerror(title, "名称不能包含 /")
            return None
        return name

    def _entries(self, path: str) -> list[GuiEntry]:
        try:
            _inode, dir_block = self._fs()._resolve_dir(path)
        except FileSystemError:
            return []
        entries = [
            GuiEntry(name, self._join(path, name), DIR_TYPE)
            for name in sorted(dir_block.son_dirs)
        ]
        entries.extend(
            GuiEntry(name, self._join(path, name), FILE_TYPE)
            for name in sorted(dir_block.son_files)
        )
        return entries

    def _find_entries(self, path: str, pattern: str) -> list[GuiEntry]:
        matches: list[GuiEntry] = []
        for entry in self._entries(path):
            if fnmatch.fnmatch(entry.name, pattern):
                matches.append(entry)
            if entry.type_id == DIR_TYPE:
                matches.extend(self._find_entries(entry.path, pattern))
        return matches

    def _stat(self, path: str) -> dict[str, object]:
        try:
            return self._fs().stat(path)
        except FileSystemError:
            return {"type": "-", "size": "-", "mode": "-", "owner_id": "-", "inode_id": "-"}

    def _can_show_dir(self, path: str) -> bool:
        try:
            self._fs()._resolve_dir(path)
            return True
        except FileSystemError:
            return False

    def _can_read_path(self, path: str) -> bool:
        return self._can_access_path(path, "r")

    def _can_write_path(self, path: str) -> bool:
        return self._can_access_path(path, "w")

    def _can_execute_path(self, path: str) -> bool:
        return self._can_access_path(path, "x")

    def _can_access_path(self, path: str, permission: str) -> bool:
        try:
            inode, _dir = self._fs()._resolve_path(path)
            self._fs()._check_permission(inode, permission)
            return True
        except FileSystemError:
            return False

    def _parent_path(self, path: str) -> str:
        return posixpath.dirname(path.rstrip("/")) or "/"

    def _permission_text(self, stat: dict[str, object]) -> str:
        mode = stat.get("mode", "-")
        text = str(mode)
        if len(text) != 2 or any(ch not in "01234567" for ch in text):
            return text
        username = self._current_username()
        if self._is_root_user():
            return f"{username}: 可读/可写"
        fs = self.fs_getter()
        current_user_id = fs.current_user.user_id if fs is not None and fs.current_user is not None else None
        mode_digit = text[0] if current_user_id == stat.get("owner_id") else text[1]
        value = int(mode_digit, 8)
        readable = "可读" if value & 4 else "不可读"
        writable = "可写" if value & 2 else "不可写"
        return f"{username}: {readable}/{writable}"

    def _permission_detail_text(self, mode: object) -> str:
        text = str(mode)
        if len(text) != 2 or any(ch not in "01234567" for ch in text):
            return text
        owner = self._permission_group_text(int(text[0], 8))
        other = self._permission_group_text(int(text[1], 8))
        return f"{text}；所有者:{owner}；其他用户:{other}"

    def _permission_group_text(self, value: int) -> str:
        names = []
        if value & 4:
            names.append("读")
        if value & 2:
            names.append("写")
        if value & 1:
            names.append("执行")
        return "/".join(names) if names else "无"

    def _is_root_user(self) -> bool:
        fs = self.fs_getter()
        return fs is not None and fs.current_user is not None and fs.current_user.name == "root"

    def _current_username(self) -> str:
        fs = self.fs_getter()
        if fs is None or fs.current_user is None:
            return "当前用户"
        return fs.current_user.name

    def _is_dir(self, path: str) -> bool:
        if path in self._path_types:
            return self._path_types[path] == DIR_TYPE
        try:
            inode, _dir = self._fs()._resolve_path(path)
            return inode.is_dir
        except FileSystemError:
            return False

    def _default_name(self, base: str) -> str:
        names = {entry.name for entry in self._entries(self.current_path)}
        if base not in names:
            return base
        stem, suffix = posixpath.splitext(base)
        for index in range(2, 1000):
            candidate = f"{stem} ({index}){suffix}"
            if candidate not in names:
                return candidate
        return base

    def _size_text(self, stat: dict[str, object]) -> str:
        if stat.get("type") == "dir":
            return ""
        return str(stat.get("size", ""))

    def _child_path(self, name: str) -> str:
        return self._join(self.current_path, name)

    def _join(self, parent: str, name: str) -> str:
        return posixpath.join(parent, name) if parent != "/" else f"/{name}"

    def _update_header(self) -> None:
        fs = self.fs_getter()
        user = fs.whoami() if fs is not None else "-"
        if self.path_var is not None:
            self.path_var.set(f"当前路径: {self.current_path}")
        if self.user_var is not None:
            self.user_var.set(f"用户: {user}")
        self._update_user_actions()
        if self.root is not None:
            self.root.title(self._window_title())

    def _window_title(self) -> str:
        fs = self.fs_getter()
        user = fs.whoami() if fs is not None else "-"
        return f"文件管理系统 - {user}"

    def _set_status(self, text: str) -> None:
        if self.status_var is not None:
            self.status_var.set(text)

    def _update_user_actions(self) -> None:
        if self._user_menu is None or self._useradd_menu_index is None:
            return
        state = tk.NORMAL if self._can_manage_users() else tk.DISABLED
        self._user_menu.entryconfig(self._useradd_menu_index, state=state)

    def _can_manage_users(self) -> bool:
        return self._is_root_user()

    def _can_change_permissions(self) -> bool:
        return self._is_root_user()

    def _show_error(self, command: str, exc: Exception) -> None:
        message = str(exc)
        text = (
            self.error_formatter(command, message)
            if self.error_formatter is not None
            else f"{command}: {message}"
        )
        self._set_status(text)
        messagebox.showerror("操作失败", text)

    def _fs(self) -> FileSystem:
        fs = self.fs_getter()
        if fs is None:
            raise FileSystemGuiError("file system is not mounted")
        return fs

    def _create_images(self) -> None:
        assert self.root is not None
        self._images["folder"] = self._solid_icon("#f4c542", "#d49b19")
        self._images["folder_open"] = self._solid_icon("#ffd86b", "#d49b19")
        self._images["file"] = self._solid_icon("#f7fbff", "#7f9db9")

    def _solid_icon(self, fill: str, outline: str) -> tk.PhotoImage:
        image = tk.PhotoImage(width=16, height=16)
        image.put(outline, to=(2, 2, 14, 15))
        image.put(fill, to=(3, 3, 13, 14))
        return image
