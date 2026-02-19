from __future__ import annotations


def edge_semantics_text(language: str) -> str:
    if language == "python":
        return (
            "Edge semantics (Python): A file A depends on file B if A imports a module whose implementation resides in B. "
            "Imports under `if TYPE_CHECKING:` (or equivalent guards) do NOT count. "
            "Dynamic/lazy imports still count as dependencies unless excluded by TYPE_CHECKING."
        )

    if language == "csharp":
        return (
            "Edge semantics (C#/.NET): A file A depends on file B if A explicitly refers to a type declared in B "
            "(compile-time type reference resolved by Roslyn). This includes type mentions in variables/parameters/returns/generics and attributes. "
            "Unused `using` directives do NOT count. Generated files are excluded upstream."
        )

    raise ValueError(f"Unsupported language {language!r}. Expected exactly 'python' or 'csharp'.")
