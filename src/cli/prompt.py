"""
    Cross-platform interactive prompt support for the shell.
"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.shortcuts import CompleteStyle

from cli.completion import CommandCompleter


class PromptCompleter(Completer):
    def __init__(self, command_completer: CommandCompleter):
        self.command_completer = command_completer

    def get_completions(self, document: Document, _complete_event):
        line = document.text_before_cursor
        active = self.command_completer._active_token(line)
        for candidate in self.command_completer.candidates(line):
            text = candidate if candidate.endswith("/") else f"{candidate} "
            yield Completion(text, start_position=-len(active), display=candidate)


class PromptReader:
    def __init__(self, command_completer: CommandCompleter):
        self.session = PromptSession(
            completer=PromptCompleter(command_completer),
            complete_while_typing=False,
            complete_style=CompleteStyle.READLINE_LIKE,
        )

    def read(self, prompt: str) -> str:
        return self.session.prompt(ANSI(prompt))
