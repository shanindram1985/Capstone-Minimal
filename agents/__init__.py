"""Agents package (lazy imports — use submodule paths directly)."""

__all__ = [
    "create_vision_agent",
    "StepBuilder",
    "ScriptGeneratorAgent",
    "ReporterAgent",
]


def __getattr__(name: str):
    if name == "create_vision_agent":
        from agents.vision_agent import create_vision_agent

        return create_vision_agent
    if name == "StepBuilder":
        from agents.step_builder import StepBuilder

        return StepBuilder
    if name == "ScriptGeneratorAgent":
        from agents.script_generator import ScriptGeneratorAgent

        return ScriptGeneratorAgent
    if name == "ReporterAgent":
        from agents.reporter_agent import ReporterAgent

        return ReporterAgent
    raise AttributeError(f"module 'agents' has no attribute {name!r}")
