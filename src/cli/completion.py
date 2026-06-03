"""
    Command history helpers and tab completion for the shell and monitor.
"""

from __future__ import annotations

import os.path
import posixpath
import shlex
from dataclasses import dataclass
from typing import Callable

from core.file_system import FileSystem, FileSystemError


SHELL_COMMANDS = (
    "append",
    "bash",
    "cat",
    "cd",
    "chmod",
    "clear",
    "close",
    "cp",
    "exit",
    "fill",
    "find",
    "format",
    "gui",
    "help",
    "ln",
    "login",
    "logout",
    "ls",
    "mkdir",
    "monitor",
    "mount",
    "mv",
    "open",
    "passwd",
    "pwd",
    "quit",
    "read",
    "rename",
    "rm",
    "rname",
    "rmdir",
    "seek",
    "stat",
    "su",
    "sync",
    "touch",
    "useradd",
    "users",
    "vim",
    "who",
    "whoami",
    "write",
    "tree",
)

PATH_COMMANDS = {
    "append",
    "bash",
    "cat",
    "cd",
    "chmod",
    "cp",
    "fill",
    "ln",
    "ls",
    "mkdir",
    "mv",
    "open",
    "rename",
    "rm",
    "rname",
    "rmdir",
    "stat",
    "touch",
    "tree",
    "vim",
    "write",
}

DIRECTORY_ONLY_COMMANDS = {"cd", "rmdir"}
@dataclass(frozen=True)
class CompletionResult:
    line: str
    candidates: list[str]


class CommandCompleter:
    def __init__(
        self,
        fs_getter: Callable[[], FileSystem | None],
        *,
        commands: tuple[str, ...] = SHELL_COMMANDS,
    ):
        self.fs_getter = fs_getter
        self.commands = commands

    def candidates(self, line: str) -> list[str]:
        active = self._active_token(line)
        words = self._words_before_active_token(line)
        if not words:
            return [command for command in self.commands if command.startswith(active)]

        command = words[0]
        if command == "find":
            if len(words) == 1:
                return self._path_candidates(active, directories_only=True)
            return []
        if command not in PATH_COMMANDS:
            return []
        return self._path_candidates(active, directories_only=command in DIRECTORY_ONLY_COMMANDS)

    def complete(self, line: str) -> CompletionResult:
        candidates = self.candidates(line)
        if not candidates:
            return CompletionResult(line, [])

        active = self._active_token(line)
        replacement = os.path.commonprefix(candidates)
        if len(candidates) == 1:
            replacement = candidates[0]
            if not replacement.endswith("/"):
                replacement += " "

        return CompletionResult(
            line=line[: len(line) - len(active)] + replacement,
            candidates=candidates,
        )

    def _path_candidates(self, active: str, *, directories_only: bool) -> list[str]:
        fs = self.fs_getter()
        if fs is None:
            return []

        if active == "~":
            parent_text = "~"
            name_prefix = ""
        elif active.startswith("~") and not active.startswith("~/"):
            return []
        else:
            parent_text, name_prefix = posixpath.split(active)

        lookup_dir = parent_text or "."
        display_parent = parent_text
        if display_parent == "/":
            display_parent = "/"
        elif display_parent:
            display_parent += "/"

        try:
            _inode, directory = fs._resolve_dir(lookup_dir)
        except FileSystemError:
            return []

        candidates = []
        for name in sorted(directory.son_dirs):
            if name.startswith(name_prefix):
                candidates.append(f"{display_parent}{name}/")
        if not directories_only:
            for name in sorted(directory.son_files):
                if name.startswith(name_prefix):
                    candidates.append(f"{display_parent}{name}")
        return candidates

    def _active_token(self, line: str) -> str:
        if not line or line[-1].isspace():
            return ""
        return line.rsplit(maxsplit=1)[-1]

    def _words_before_active_token(self, line: str) -> list[str]:
        active = self._active_token(line)
        prefix = line[: len(line) - len(active)]
        try:
            return shlex.split(prefix)
        except ValueError:
            return prefix.split()
