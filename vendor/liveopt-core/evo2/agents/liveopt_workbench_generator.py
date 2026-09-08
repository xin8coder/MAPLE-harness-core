"""Public LiveOpt Workbench generator API.

The historical implementation module is kept for import compatibility; new
code should import from this LiveOpt-named facade.
"""

from __future__ import annotations

from evo2.agents.liveopt_workbench_impl import (
    LiveOptWorkbenchGenerator as LiveOptWorkbenchGenerator,
    ScaffoldProject,
    ScaffoldTrace,
    compile_scaffold_project,
)

__all__ = [
    "LiveOptWorkbenchGenerator",
    "ScaffoldProject",
    "ScaffoldTrace",
    "compile_scaffold_project",
]
