# -*- coding: utf-8 -*-
"""
    模拟文件系统的 Qt 图形界面模式。
    该 GUI 是对现有命令行功能的轻量级桌面封装。
"""

from __future__ import annotations

import fnmatch
import os
import posixpath
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

try:
    from PySide6 import QtCore, QtGui, QtWidgets  
except ImportError as exc:  # pragma: no cover - depends on local environment
    QtCore = None
    QtGui = None
    QtWidgets = None
    QT_IMPORT_ERROR = str(exc)
else:
    QT_IMPORT_ERROR = ""

from core.file_system import FileSystem, FileSystemError
from head import DIR_TYPE, FILE_TYPE

from PySide6.QtGui import QFont

CommandExecutor = Callable[[str], tuple[bool, str]]
FIGURE_DIR = Path(__file__).resolve().parents[1] / "figure"
ACTION_ICON_FILES = {
    "新建文件夹": "新建文件夹.svg",
    "新建文件": "新建文件.svg",
    "打开": "4打开文件.svg",
    "编辑": "编辑.svg",
    "删除": "删除.svg",
    "属性": "属性.svg",
    "上一级": "上一级.svg",
    "刷新": "刷新.svg",
}


@dataclass(frozen=True)
class GuiEntry:
    name: str
    path: str
    type_id: int


class FileSystemGuiError(Exception):
    """GUI 无法启动时抛出此异常"""

# GUI 设计
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
        self._search_mode = False
        self._tree_paths: dict[object, str] = {}
        self._entry_paths: dict[object, str] = {}
        self._path_types: dict[str, int] = {}
        self._renaming_path: str | None = None
        self._rename_armed = False
        self._suppress_item_change = False

        self.app = None
        self.window = None
        self.tree = None
        self.entries = None
        self.path_label = None
        self.user_label = None
        self.search_edit = None
        self.useradd_action = None
        self.login_action = None 
        self.logout_action = None
        self.su_action = None
        self.passwd_action = None
   
    def run(self) -> None:
        if self.fs_getter() is None:
            raise FileSystemGuiError("file system is not mounted")
        self._ensure_qt_available()
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        self.window = QtWidgets.QMainWindow()
        self.window.setWindowTitle(self._window_title())
        self.window.resize(1080, 720)
        self._build_ui()
        self.refresh()
        self.window.show()
        self.app.exec()

    # UI 环境检查
    def _ensure_qt_available(self) -> None:
        if QtWidgets is None:
            raise FileSystemGuiError(
                "PySide6 is required for gui mode. Install it with "
                "'python -m pip install -r requirements.txt'."
            )
        if sys.platform.startswith("linux") and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        ):
            raise FileSystemGuiError(
                "gui requires a graphical display. On WSL, use WSLg or configure "
                "an X server/DISPLAY."
            )

    # UI 构建
    def _build_ui(self) -> None:
        assert self.window is not None

        icon_file = FIGURE_DIR / "文件系统软件图标.svg"
        if icon_file.exists():
            self.window.setWindowIcon(QtGui.QIcon(str(icon_file)))

        # CSS 样式
        self.window.setStyleSheet(
            """
            QMainWindow { background: #f4f6f8; }
            QToolBar { background: #eef2f6; spacing: 4px; padding: 4px 6px; }
            QTreeWidget { background: white; border: 1px solid #c7d0d9; font-size: 13px; }
            QHeaderView::section { background: #edf3f8; padding: 6px; border: 0; border-right: 1px solid #d7dee6; }
            QLineEdit { padding: 5px 8px; border: 1px solid #b8c5d1; border-radius: 4px; background: white; }
            QLabel#PathLabel { color: #1f3b57; font-weight: 600; }
            QTreeWidget::item { height: 32px; }
            """
        )
        # 菜单和工具栏
        self._build_menu()
        self._build_toolbar()

        # 内容放在中间
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        # 头部 HBOX 布局 显示当前路径和用户信息
        header = QtWidgets.QHBoxLayout()
        self.path_label = QtWidgets.QLabel()
        self.path_label.setObjectName("PathLabel")
        self.user_label = QtWidgets.QLabel()
        header.addWidget(self.path_label)
        header.addStretch(1)
        header.addWidget(self.user_label)
        layout.addLayout(header)

        # 主体部分左右分割，左侧是目录树，右侧是当前目录的文件列表
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.itemSelectionChanged.connect(self._on_tree_select)
        # 双击树节点也进入目录，但不展开/收起节点
        self.tree.itemDoubleClicked.connect(lambda _item, _column: self._open_tree_selection())
        self.tree.customContextMenuRequested.connect(self._on_tree_context)

        # 文件列表使用 QTreeWidget 来显示多列信息
        self.entries = QtWidgets.QTreeWidget()
        self.entries.setColumnCount(6)
        self.entries.setHeaderLabels(["名称", "类型", "大小", "权限", "Owner", "inode"])
        self.entries.setRootIsDecorated(False)
        self.entries.setAlternatingRowColors(True)
        self.entries.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        # 静止手动编辑
        self.entries.setEditTriggers(QtWidgets.QTreeWidget.NoEditTriggers)
        # 双击文件列表项：如果是目录则进入，否则打开文件
        self.entries.itemDoubleClicked.connect(lambda _item, _column: self.open_selected())
        # 右键文件列表项显示上下文菜单
        self.entries.customContextMenuRequested.connect(self._on_entry_context)
        # 重命名处理
        self.entries.itemChanged.connect(self._on_entry_changed)

        # 自适应 
        header = self.entries.header()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        # 全局最小宽度（所有列不会小于这个值）
        header.setMinimumSectionSize(80)
        # 全局最大宽度（所有列不会大于这个值）
        header.setMaximumSectionSize(300)
        # 最后一列拉伸（完美布局）
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.Stretch)

        splitter.addWidget(self.tree)
        splitter.addWidget(self.entries)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)
        self.window.setCentralWidget(central)
        self.window.statusBar().showMessage("就绪")

    # 菜单构建
    def _build_menu(self) -> None:
        assert self.window is not None
        menu = self.window.menuBar()
        file_menu = menu.addMenu("文件")
        self._add_action(file_menu, "挂载...", self.mount_disk)
        self._add_action(file_menu, "格式化...", self.format_disk)
        file_menu.addSeparator()
        self._add_action(file_menu, "刷新", self.refresh)
        self._add_action(file_menu, "退出图形模式", self.window.close)

        edit_menu = menu.addMenu("编辑")
        self._add_action(edit_menu, "新建文件", self.new_file)
        self._add_action(edit_menu, "新建文件夹", self.new_dir)
        self._add_action(edit_menu, "打开", self.open_selected)
        self._add_action(edit_menu, "编辑", self.edit_selected)
        self._add_action(edit_menu, "重命名", self.rename_selected)
        self._add_action(edit_menu, "删除", self.delete_selected)
        self._add_action(edit_menu, "属性", self.properties_selected)

        search_menu = menu.addMenu("搜索")
        self._add_action(search_menu, "搜索当前目录", self.search)
        self._add_action(search_menu, "清除搜索", self.clear_search)

        user_menu = menu.addMenu("用户")
        self.login_action = self._add_action(user_menu, "登录...", self.login)
        self.logout_action = self._add_action(user_menu, "注销", self.logout)
        self.su_action = self._add_action(user_menu, "切换用户...", self.su)
        self.useradd_action = self._add_action(user_menu, "新建用户...", self.useradd)
        self.passwd_action = self._add_action(user_menu, "修改密码...", self.passwd)
        
        menubar = self.window.menuBar()
        menubar.setNativeMenuBar(False)

    # 工具栏构建
    def _build_toolbar(self) -> None:
        assert self.window is not None
        toolbar = QtWidgets.QToolBar("文件操作")
        toolbar.setMovable(False)
        self.window.addToolBar(toolbar)
        toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        toolbar.setIconSize(QtCore.QSize(22, 22))
        for label, slot in (
            ("新建文件", self.new_file),
            ("新建文件夹", self.new_dir),
            ("打开", self.open_selected),
            ("编辑", self.edit_selected),
            ("删除", self.delete_selected),
            ("属性", self.properties_selected),
            ("上一级", self.go_up),
            ("刷新", self.refresh),
        ):
            action = toolbar.addAction(self._icon_for_action(label), "", slot)
            action.setToolTip(label)
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("搜索当前目录，例如 *.txt")
        self.search_edit.setFixedWidth(240)
        self.search_edit.returnPressed.connect(self.search)
        toolbar.addWidget(self.search_edit)
        search_action = toolbar.addAction(self._icon_for_action("搜索"), "", self.search)
        search_action.setToolTip("搜索")
        clear_action = toolbar.addAction(self._icon_for_action("清除"), "", self.clear_search)
        clear_action.setToolTip("清除")

    """
        以下是各种操作的实现，包括刷新、文件操作、用户管理等。
    """

    # 刷新当前目录显示，保持在当前路径
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

    # 挂载磁盘
    def mount_disk(self) -> None:
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(self.window, "选择磁盘镜像")
        if path:
            self._run(["mount", path], refresh_tree=True)

    # 格式化磁盘
    def format_disk(self) -> None:
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(self.window, "格式化磁盘镜像")
        if path and self._confirm("确认格式化", f"格式化会清空磁盘：\n{path}\n是否继续？"):
            self._run(["format", path], refresh_tree=True)

    # 新建文件和文件夹
    def new_file(self) -> None:
        self._create_default_entry(is_dir=False)

    def new_dir(self) -> None:
        self._create_default_entry(is_dir=True)

    # 打开文件或进入目录
    def open_selected(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        if self._is_dir(path):
            self._run(["cd", path])
            return
        if not self._can_read_path(path):
            self._set_status("当前用户没有打开该文件的权限")
            return
        ok, output = self._run(["cat", path], refresh=False)
        if ok:
            self._show_text(f"查看：{path}", output, readonly=True)

    # 编辑选中的文件
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

    # 重命名选中的文件或目录
    def rename_selected(self) -> None:
        path = self._selected_path()
        if path is None or path == "/":
            return
        parent_path = self._parent_path(path)
        if not (self._can_write_path(parent_path) and self._can_execute_path(parent_path)):
            self._set_status("当前用户没有重命名该项目的权限")
            return
        self._begin_inline_rename(path)

    # 删除选中的文件或目录
    def delete_selected(self) -> None:

        path = self._selected_path()
        if path is None or path == "/":
            return
        parent_path = self._parent_path(path)
        if not (self._can_write_path(parent_path) and self._can_execute_path(parent_path)):
            self._set_status("当前用户没有删除该项目的权限")
            return
        if not self._confirm("确认删除", f"删除 {path}？"):
            return

        if self._is_dir(path):
            # 检查目录是否为空
            if self._is_empty_dir(path):
                # 空目录 → 直接删除
                argv = ["rmdir", path]
            else:
                # 非空目录 → 提示并确认
                if not self._confirm("提示", "目录不为空，是否确认删除？"):
                    return
                argv = ["rmdir", "-r", path]
        else:
            # 文件直接删除
            argv = ["rm", path]

        self._run(argv)

    # 创建硬链接
    def link_selected(self) -> None:
        path = self._selected_path()
        if path is None or self._is_dir(path):
            self._set_status("请选择一个文件创建硬链接")
            return
        if not (self._can_write_path(self.current_path) and self._can_execute_path(self.current_path)):
            self._set_status("当前用户没有在当前目录创建硬链接的权限")
            return
        default = self._default_name(f"{posixpath.basename(path)}-link")
        name = self._ask_text("创建硬链接", "链接名称：", default)
        if name:
            self._run(["ln", path, self._child_path(name)])

    # 修改权限
    def chmod_selected(self) -> None:
        if not self._can_change_permissions():
            self._set_status("只有 root 用户可以修改权限")
            return
        path = self._selected_path()
        if path is None:
            return
        current = str(self._stat(path).get("mode", ""))
        mode = self._ask_text(
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

    # 显示属性
    def properties_selected(self) -> None:
        path = self._selected_path() or self.current_path
        self._show_properties(path)

    # 搜索当前目录
    def search(self) -> None:
        pattern = self.search_edit.text().strip() if self.search_edit is not None else ""
        if not pattern:
            pattern = self._ask_text("搜索", "输入匹配模式，例如 *.txt：", "")
            if self.search_edit is not None:
                self.search_edit.setText(pattern or "")
        if not pattern:
            return
        self._log_command(["find", self.current_path, pattern])
        matches = self._find_entries(self.current_path, pattern)
        self._search_mode = True
        self._refresh_entries(matches)
        self._set_status(f"搜索 {pattern}: {len(matches)} 项")

    # 清除搜索结果，回到正常的目录显示
    def clear_search(self) -> None:
        if self.search_edit is not None:
            self.search_edit.clear()
        self._search_mode = False
        self._refresh_entries()
        self._set_status("已清除搜索")

    # 进入上一级目录
    def go_up(self) -> None:
        if self.current_path != "/":
            self._run(["cd", posixpath.dirname(self.current_path.rstrip("/")) or "/"])

    # 用户登录
    def login(self) -> None:
        
        # 调用双输入弹窗
        result = self._ask_two_texts(
            title="登录",
            label1="用户名：",
            label2="密码：",
            password2=True
        )

        # 用户取消
        if result is None:
            return

        username, password = result
        # 不能为空校验
        if not username or not password:
            self._show_error("登录", "用户名和密码不能为空")
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

    # 用户注销
    def logout(self) -> None:
        self._run(["logout"])
    
    # 切换用户
    def su(self) -> None:
        # 双输入弹窗：用户名 + 密码
        result = self._ask_two_texts(
            title="切换用户",
            label1="用户名：",
            label2="密码：",
            password2=True
        )

        # 点取消直接退出
        if result is None:
            return

        username, password = result

        # 校验不能为空
        if not username or not password:
            self._show_error("切换用户", "用户名和密码不能为空")
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

        # 双输入弹窗：用户名 + 密码
        result = self._ask_two_texts(
            title="新建用户",
            label1="用户名：",
            label2="密码：",
            password2=True
        )

        # 点取消直接退出
        if result is None:
            return

        username, password = result

        # 校验不能为空
        if not username or not password:
            self._show_error("新建用户", "用户名和密码不能为空")
            return

        self._log_command(["useradd", username])
        try:
            self._fs().useradd(username, password)
            self.refresh()
            self._set_status(f"已创建用户：{username}")
        except FileSystemError as exc:
            self._show_error("useradd", exc)

    # 修改密码
    def passwd(self) -> None:
         # 获取当前登录用户
        current_user = self._fs().whoami()

        # 双输入弹窗：用户名（默认当前用户） + 新密码
        result = self._ask_two_texts(
            title="修改密码",
            label1="用户名：",
            label2="新密码：",
            initial1=current_user,  # 默认填当前用户
            password2=True         # 密码框隐藏
        )

        # 点取消直接退出
        if result is None:
            return

        username, password = result

        # 密码不能为空
        if not password:
            self._show_error("修改密码", "密码不能为空")
            return

        argv = ["passwd"] + ([username] if username else [])
        self._log_command(argv)
        try:
            self._fs().passwd(username or current_user, password)
            self._set_status("密码已更新")
        except FileSystemError as exc:
            self._show_error("passwd", exc)

    """"
        以下是一些内部工具方法，例如刷新树视图、处理上下文菜单、重命名等。
    """
    def _create_default_entry(self, *, is_dir: bool) -> None:
        if not (self._can_write_path(self.current_path) and self._can_execute_path(self.current_path)):
            self._set_status("当前用户没有在当前目录中新建项目的权限")
            return
        default_name = self._default_name("新建文件夹" if is_dir else "新建文件.txt")
        path = self._child_path(default_name)
        ok, _output = self._run(["mkdir" if is_dir else "touch", path])
        if ok:
            self._select_entry_path(path)
            self._begin_inline_rename(path)

    def _refresh_tree(self) -> None:
        assert self.tree is not None
        self.tree.clear()
        self._tree_paths.clear()
        root = QtWidgets.QTreeWidgetItem(["/"])
        root.setIcon(0, self._folder_icon(opened=True))
        self.tree.addTopLevelItem(root)
        root.setExpanded(True)
        self._tree_paths[root] = "/"
        self._fill_tree_node(root, "/")

    def _fill_tree_node(self, item: object, path: str) -> None:
        for entry in self._entries(path):
            if entry.type_id != DIR_TYPE:
                continue
            child = QtWidgets.QTreeWidgetItem([entry.name])
            child.setIcon(0, self._folder_icon())
            item.addChild(child)
            child.setExpanded(entry.path == self.current_path)
            self._tree_paths[child] = entry.path
            self._fill_tree_node(child, entry.path)

    def _refresh_entries(self, entries: list[GuiEntry] | None = None) -> None:
        assert self.entries is not None
        self._suppress_item_change = True
        self.entries.clear()
        self._entry_paths.clear()
        self._path_types.clear()
        for entry in entries if entries is not None else self._entries(self.current_path):
            stat = self._stat(entry.path)
            item = QtWidgets.QTreeWidgetItem([
                entry.path if self._search_mode else entry.name,
                "文件夹" if entry.type_id == DIR_TYPE else "文件",
                self._size_text(stat),
                self._permission_text(stat),
                # str(stat.get("owner_id", "-")),
                self._get_username(stat.get("owner_id")),
                str(stat.get("inode_id", "-")),
            ])
            item.setIcon(0, self._folder_icon() if entry.type_id == DIR_TYPE else self._file_icon())
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            item.setTextAlignment(3, QtCore.Qt.AlignCenter)
            self.entries.addTopLevelItem(item)
            self._entry_paths[item] = entry.path
            self._path_types[entry.path] = entry.type_id
        self._suppress_item_change = False

    def _refresh_entries_only(self) -> None:
        self._search_mode = False
        self._update_header()
        self._refresh_entries()

    def _on_tree_select(self) -> None:
        item = self.tree.currentItem() if self.tree is not None else None
        path = self._tree_paths.get(item)
        if path:
            self.current_path = path
            self._search_mode = False
            self._update_header()
            self._refresh_entries()

    def _open_tree_selection(self) -> None:
        item = self.tree.currentItem() if self.tree is not None else None
        path = self._tree_paths.get(item)
        if path:
            self._run(["cd", path])

    def _on_tree_context(self, pos: object) -> None:
        assert self.tree is not None
        item = self.tree.itemAt(pos)
        if item is not None:
            self.tree.setCurrentItem(item)
            path = self._tree_paths.get(item, self.current_path)
            self.current_path = path
            self._update_header()
            self._refresh_entries()
        self._show_context_menu(self.tree.mapToGlobal(pos), self.current_path, True)

    def _on_entry_context(self, pos: object) -> None:
        assert self.entries is not None
        item = self.entries.itemAt(pos)
        if item is not None:
            self.entries.setCurrentItem(item)
            self._show_context_menu(self.entries.mapToGlobal(pos), self._entry_paths.get(item), False)
        else:
            self._show_context_menu(self.entries.mapToGlobal(pos), self.current_path, True)

    def _show_context_menu(self, global_pos: object, target_path: str | None, is_background: bool) -> None:
        menu = QtWidgets.QMenu(self.window)
        if is_background:
            can_create = self._can_write_path(self.current_path) and self._can_execute_path(self.current_path)
            self._add_action(menu, "新建文件", self.new_file, can_create)
            self._add_action(menu, "新建文件夹", self.new_dir, can_create)
            menu.addSeparator()
            self._add_action(menu, "搜索此目录", self.search, self._can_read_path(self.current_path))
            self._add_action(menu, "刷新", self.refresh)
            menu.exec(global_pos)
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
        self._add_action(menu, "打开", self.open_selected, can_read)
        if not is_dir:
            self._add_action(menu, "编辑", self.edit_selected, can_read and can_write_target)
            self._add_action(menu, "创建硬链接", self.link_selected, can_write_parent)
        if is_dir:
            self._add_action(menu, "在此目录中新建文件", lambda: self._new_inside(target_path, False), can_create_inside)
            self._add_action(menu, "在此目录中新建文件夹", lambda: self._new_inside(target_path, True), can_create_inside)
        menu.addSeparator()
        self._add_action(menu, "重命名", self.rename_selected, can_write_parent)
        self._add_action(menu, "删除", self.delete_selected, can_write_parent)
        self._add_action(menu, "修改权限", self.chmod_selected, self._can_change_permissions())
        self._add_action(menu, "属性", self.properties_selected)
        menu.exec(global_pos)

    def _new_inside(self, path: str | None, is_dir: bool) -> None:
        if not path:
            return
        self.current_path = path
        self._update_header()
        self.new_dir() if is_dir else self.new_file()

    def _selected_path(self) -> str | None:
        item = self.entries.currentItem() if self.entries is not None else None
        if item is not None:
            return self._entry_paths.get(item)
        item = self.tree.currentItem() if self.tree is not None else None
        return self._tree_paths.get(item)

    def _select_entry_path(self, path: str) -> None:
        assert self.entries is not None
        for item, item_path in self._entry_paths.items():
            if item_path == path:
                self.entries.setCurrentItem(item)
                self.entries.scrollToItem(item)
                return

    def _begin_inline_rename(self, path: str) -> None:
        assert self.entries is not None
        for item, item_path in self._entry_paths.items():
            if item_path == path:
                self._renaming_path = path
                self._rename_armed = True
                self.entries.editItem(item, 0)
                return

    def _on_entry_changed(self, item: object, column: int) -> None:
        if (
            self._suppress_item_change
            or column != 0
            or self._renaming_path is None
            or not self._rename_armed
        ):
            return
        old_path = self._renaming_path
        self._renaming_path = None
        self._rename_armed = False
        old_name = posixpath.basename(old_path.rstrip("/"))
        new_name = item.text(0).strip()
        if not new_name or new_name == old_name:
            self._refresh_entries_only()
            return
        if "/" in new_name:
            self._show_message("重命名", "名称不能包含 /", error=True)
            self._refresh_entries_only()
            return
        self._run(["rename", old_path, new_name])

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
                self._show_message("命令失败", output, error=True)
        else:
            self._set_status(command)
        return ok, output

    def _log_command(self, argv: list[str]) -> None:
        if self.command_logger is not None:
            self.command_logger(shlex.join(argv))

    def _show_text(self, title: str, content: str, *, readonly: bool, save_path: str | None = None) -> None:
        dialog = QtWidgets.QDialog(self.window)
        dialog.setWindowTitle(title)
        dialog.resize(760, 520)
        layout = QtWidgets.QVBoxLayout(dialog)
        editor = QtWidgets.QPlainTextEdit()
        editor.setPlainText(content)
        editor.setReadOnly(readonly)
        layout.addWidget(editor)
        buttons = QtWidgets.QDialogButtonBox()
        if readonly:
            buttons.addButton("关闭", QtWidgets.QDialogButtonBox.AcceptRole)
        else:
            buttons.addButton("保存", QtWidgets.QDialogButtonBox.AcceptRole)
            buttons.addButton("取消", QtWidgets.QDialogButtonBox.RejectRole)
        buttons.accepted.connect(lambda: self._save_editor(dialog, editor, save_path, readonly))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _save_editor(self, dialog: object, editor: object, save_path: str | None, readonly: bool) -> None:
        if readonly:
            dialog.accept()
            return
        assert save_path is not None
        ok, _output = self._run(["write", save_path, editor.toPlainText()])
        if ok:
            dialog.accept()

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
            rows.append(f"包含项目: {len(self._entries(path))}")
        self._show_text(f"属性：{path}", "\n".join(rows), readonly=True)

    def _ask_text(self, title: str, label: str, initial: str, *, password: bool = False) -> str | None:
        dialog = QtWidgets.QInputDialog(self.window)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setTextValue(initial)
        if password:
            dialog.setTextEchoMode(QtWidgets.QLineEdit.Password)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        value = dialog.textValue().strip()
        if "/" in value:
            self._show_message(title, "名称不能包含 /", error=True)
            return None
        return value

    # 双输入框的通用函数，适用于登录（用户名+密码）和修改密码（用户名+新密码）
    def _ask_two_texts(
        self,
        title: str,
        label1: str,
        label2: str,
        initial1: str = "",
        initial2: str = "",
        password2: bool = False,
    ) -> tuple[str, str] | None:

        dialog = QtWidgets.QDialog(self.window)
        dialog.setWindowTitle(title)

        dialog.resize(240, 120)  # 宽度，高度
        layout = QtWidgets.QFormLayout(dialog)

        # 第一个输入框
        edit1 = QtWidgets.QLineEdit(initial1)
        layout.addRow(label1, edit1)

        # 第二个输入框（支持密码模式）
        edit2 = QtWidgets.QLineEdit(initial2)
        if password2:
            edit2.setEchoMode(QtWidgets.QLineEdit.Password)
        layout.addRow(label2, edit2)

        # 确定 / 取消按钮
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.layout().setSpacing(64)  # 数字越大，间距越宽
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        # 执行弹窗
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None

        text1 = edit1.text().strip()
        text2 = edit2.text().strip()

        # 沿用你原来的校验：不能包含 /
        if "/" in text1 or "/" in text2:
            self._show_message(title, "名称不能包含 /", error=True)
            return None

        return (text1, text2)

    def _entries(self, path: str) -> list[GuiEntry]:
        try:
            _inode, dir_block = self._fs()._resolve_dir(path)
        except FileSystemError:
            return []
        entries = [GuiEntry(name, self._join(path, name), DIR_TYPE) for name in sorted(dir_block.son_dirs)]
        entries.extend(GuiEntry(name, self._join(path, name), FILE_TYPE) for name in sorted(dir_block.son_files))
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

    def _permission_text(self, stat: dict[str, object]) -> str:
        text = str(stat.get("mode", "-"))
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
        return "" if stat.get("type") == "dir" else str(stat.get("size", ""))

    def _child_path(self, name: str) -> str:
        return self._join(self.current_path, name)

    def _join(self, parent: str, name: str) -> str:
        return posixpath.join(parent, name) if parent != "/" else f"/{name}"

    def _parent_path(self, path: str) -> str:
        return posixpath.dirname(path.rstrip("/")) or "/"

    def _update_header(self) -> None:
        user = self._fs().whoami() if self.fs_getter() is not None else "-"
        if self.path_label is not None:
            self.path_label.setText(f"当前路径: {self.current_path}")
        if self.user_label is not None:
            self.user_label.setText(f"用户: {user}")
        if self.window is not None:
            self.window.setWindowTitle(self._window_title())
        self._update_user_actions()

    def _window_title(self) -> str:
        fs = self.fs_getter()
        user = fs.whoami() if fs is not None else "-"
        return f"文件管理系统 - {user}"

    def _set_status(self, text: str) -> None:
        if self.window is not None:
            self.window.statusBar().showMessage(text)

    def _update_user_actions(self) -> None:
        # 只有 root 用户可以管理用户，所以根据权限启用或禁用相关操作
        if self.useradd_action is not None:
            self.useradd_action.setEnabled(self._can_manage_users())
        
        # 登录操作在没有用户登录时可用，注销和切换用户在有用户登录时可用
        fs = self.fs_getter()
        is_logged_in = fs is not None and fs.current_user is not None
        self.login_action.setEnabled(not is_logged_in)
        self.logout_action.setEnabled(is_logged_in)
        self.su_action.setEnabled(is_logged_in)
        self.passwd_action.setEnabled(is_logged_in)

    def _is_root_user(self) -> bool:
        fs = self.fs_getter()
        return fs is not None and fs.current_user is not None and fs.current_user.name == "root"

    def _current_username(self) -> str:
        fs = self.fs_getter()
        if fs is None or fs.current_user is None:
            return "当前用户"
        return fs.current_user.name

    def _can_manage_users(self) -> bool:
        return self._is_root_user()

    def _can_change_permissions(self) -> bool:
        return self._is_root_user()

    def _show_error(self, command: str, exc: Exception) -> None:
        message = str(exc)
        text = self.error_formatter(command, message) if self.error_formatter is not None else f"{command}: {message}"
        self._set_status(text)
        self._show_message("操作失败", text, error=True)

    def _fs(self) -> FileSystem:
        fs = self.fs_getter()
        if fs is None:
            raise FileSystemGuiError("file system is not mounted")
        return fs

    def _add_action(self, menu_or_toolbar: object, label: str, slot: Callable[[], None], enabled: bool = True) -> object:
        action = QtGui.QAction(self._icon_for_action(label), label, self.window)
        action.triggered.connect(slot)
        action.setEnabled(enabled)
        menu_or_toolbar.addAction(action)
        return action

    def _icon_for_action(self, label: str) -> object:
        style = self.window.style() if self.window is not None else QtWidgets.QApplication.style()
        icon_path = self._icon_resource_path(label)
        if icon_path is not None:
            icon = QtGui.QIcon(str(icon_path))
            if not icon.isNull():
                return icon
        if "文件夹" in label:
            return style.standardIcon(QtWidgets.QStyle.SP_DirIcon)
        if "打开" in label:
            return style.standardIcon(QtWidgets.QStyle.SP_DialogOpenButton)
        if "删除" in label:
            return style.standardIcon(QtWidgets.QStyle.SP_TrashIcon)
        if "刷新" in label:
            return style.standardIcon(QtWidgets.QStyle.SP_BrowserReload)
        if "搜索" in label:
            return style.standardIcon(QtWidgets.QStyle.SP_FileDialogContentsView)
        if "清除" in label:
            return style.standardIcon(QtWidgets.QStyle.SP_DialogCancelButton)
        return QtGui.QIcon()

    def _icon_resource_path(self, label: str) -> Path | None:
        for keyword, filename in ACTION_ICON_FILES.items():
            if keyword in label:
                path = FIGURE_DIR / filename
                if path.exists():
                    return path
        return None

    def _folder_icon(self, *, opened: bool = False) -> object:
        style = self.window.style()
        icon = QtWidgets.QStyle.SP_DirOpenIcon if opened else QtWidgets.QStyle.SP_DirIcon
        return style.standardIcon(icon)

    def _file_icon(self) -> object:
        return self.window.style().standardIcon(QtWidgets.QStyle.SP_FileIcon)

    def _confirm(self, title: str, text: str) -> bool:
        return QtWidgets.QMessageBox.question(
            self.window,
            title,
            text,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        ) == QtWidgets.QMessageBox.Yes

    def _show_message(self, title: str, text: str, *, error: bool = False) -> None:
        if error:
            QtWidgets.QMessageBox.critical(self.window, title, text)
        else:
            QtWidgets.QMessageBox.information(self.window, title, text)

    def _is_empty_dir(self, path: str) -> bool:
        """判断目录是否为空目录"""
        try:
            # 直接获取目录下的项目数量
            return len(self._entries(path)) == 0
        except FileSystemError:
            return False
        
    def _get_username(self, uid: int | None) -> str:
        """把用户ID转成用户名"""
        if uid is None:
            return "-"
        
        fs = self._fs()
        # 遍历用户字典，通过 uid 找对应用户名
        for username, user_obj in fs.super_block.users.items():
            if user_obj.user_id == uid:
                return username
        
        # 找不到就返回 uid 数字
        return str(uid)