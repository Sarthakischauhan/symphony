"""What skills and plugins share: where they live, where they come from, how problems are reported.

Why a package of its own: ``addons/skills`` and ``addons/plugins`` both need the
root order and the source parser, and neither may import the other.
"""

from coding_agent.extensions.diagnostics import Diagnostic
from coding_agent.extensions.roots import BUNDLED_SKILLS, ExtensionRoot, extension_roots, project_root

__all__ = ["BUNDLED_SKILLS", "Diagnostic", "ExtensionRoot", "extension_roots", "project_root"]
