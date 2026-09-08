"""LiveOpt web demo: a chat-first agent over the real LiveOpt pipeline.

The demo reuses ``evo2`` as a library: an LLM router decides per message
whether to answer, start an optimization session, or apply a natural-language
update; the Workbench generator, dynamic runner, and semantic restart gate do
the actual LiveOpt work.
"""

from demo.chat import Chat, ChatManager
from demo.session import DemoSession

__all__ = ["Chat", "ChatManager", "DemoSession"]
