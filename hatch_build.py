"""Bundle the explicitly selected release guides without changing their sources."""

import asyncio
from pathlib import Path
from re import Match, findall, sub
from tempfile import TemporaryDirectory
from typing import Any

# Hatchling is supplied by the isolated build environment, not runtime dependencies.
from hatchling.builders.hooks.plugin.interface import (  # ty: ignore[unresolved-import]
    BuildHookInterface,
)


class ReleaseDocsError(Exception):
    """Release documentation inputs are missing from a build tree."""


class ReleaseDocsHook(BuildHookInterface):
    """Use the release index as the opt-in inventory for offline guides."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._bundle: TemporaryDirectory[str] | None = None

    def initialize(self, _version: str, build_data: dict[str, Any]) -> None:
        """Prepare package resources for both wheel and source builds."""
        asyncio.run(asyncio.to_thread(self._prepare_bundle, build_data))

    def finalize(
        self, _version: str, _build_data: dict[str, Any], _artifact_path: str
    ) -> None:
        """Remove staging files after the archive has been written."""
        if self._bundle is not None:
            asyncio.run(asyncio.to_thread(self._bundle.cleanup))

    def _prepare_bundle(self, build_data: dict[str, Any]) -> None:
        root = Path(self.root).resolve()
        index = root / "docs" / "release-index.md"
        if not index.is_file():
            # Source archives already carry the curated package resources.
            if (root / "snekql" / "docs" / "README.md").is_file():
                return
            msg = "Missing docs/release-index.md or prebundled snekql/docs/README.md"
            raise ReleaseDocsError(msg)
        self._bundle = TemporaryDirectory(prefix="snekql-docs-")
        bundle = Path(self._bundle.name)
        sources = {"README.md": index, "SECURITY.md": root / "SECURITY.md"}
        for target in findall(r"\]\(([^)]+)\)", index.read_text(encoding="utf-8")):
            source = (index.parent / target.split("#")[0]).resolve()
            sources[source.name] = source
        # Linked recipes are reading resources, not new runtime modules.
        for source in tuple(sources.values()):
            for target in findall(
                r"\]\((\.\./examples/[^)]+\.py)\)",
                source.read_text(encoding="utf-8"),
            ):
                recipe = (source.parent / target).resolve()
                sources[f"examples/{recipe.name}"] = recipe

        destinations = {source: name for name, source in sources.items()}
        destinations[root / "docs" / "README.md"] = "README.md"
        destinations[root / "snekql" / "examples" / "basic.py"] = "../examples/basic.py"
        for name, source in sources.items():
            text = (
                self._rewrite_guide(source, destinations)
                if source.suffix == ".md"
                else source.read_text(encoding="utf-8")
            )
            if name == "README.md":
                heading, remainder = text.split("\n", 1)
                text = f"{heading}\n\nRelease: {self.metadata.version}\n{remainder}"
            destination = bundle / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        build_data["force_include"][str(bundle)] = "snekql/docs"

    def _rewrite_guide(self, source: Path, destinations: dict[Path, str]) -> str:
        """Keep examples intact while making prose navigation work offline."""

        def rewrite(match: Match[str]) -> str:
            label, target = match.groups()
            if label is None or target.startswith(("https:", "http:", "mailto:", "#")):
                return match.group()
            path, separator, fragment = target.partition("#")
            referenced = (source.parent / path).resolve()
            if referenced in destinations:
                return f"[{label}]({destinations[referenced]}{separator}{fragment})"
            # Evidence stays distinguishable from instructions, without dangling
            # links or bringing repository internals into a consumer's environment.
            return f"{label} (repository-only: `{target}`)"

        return sub(
            r"```[\s\S]*?```|`[^`\n]*`|\[([^\]\n]+)\]\(([^)\n]+)\)",
            rewrite,
            source.read_text(encoding="utf-8"),
        )
