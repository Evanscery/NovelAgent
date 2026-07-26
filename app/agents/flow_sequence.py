"""Flow sequence generator: generate_flow_sequence.

Produces the numbered execution-order text injected into the director
prompt, derived from a :class:`~app.agents.tree_model.WorkflowTree`.
"""

from __future__ import annotations

from app.agents.tree_model import WorkflowTree


def generate_flow_sequence(tree: WorkflowTree) -> str:
    """Generate the numbered execution-order text for the director prompt.

    Format (one node per line, BFS order)::

        1. [depth=0] agent_name: description
        2. [depth=1] agent_name: description (parallel with X, depends on Y)

    Annotations (only when ``dependency_ids`` is non-empty):

    * ``(parallel with X, Y)`` -- dependencies at the SAME depth.
    * ``(depends on X, Y)`` -- dependencies at a DIFFERENT depth.
    * Both can appear comma-separated when both kinds exist.

    Args:
        tree: The expanded :class:`WorkflowTree`.

    Returns:
        A newline-separated numbered list string. Empty tree -> empty str.
    """
    if not tree.all_nodes:
        return ""

    ordered = sorted(tree.all_nodes.values(), key=lambda n: (n.depth, n.id))

    lines: list[str] = []
    for i, node in enumerate(ordered, start=1):
        annotation = ""
        if node.dependency_ids:
            same_depth = [d for d in node.dependency_ids if tree.all_nodes[d].depth == node.depth]
            diff_depth = [d for d in node.dependency_ids if tree.all_nodes[d].depth != node.depth]
            parts: list[str] = []
            if same_depth:
                parts.append("parallel with " + ", ".join(same_depth))
            if diff_depth:
                parts.append("depends on " + ", ".join(diff_depth))
            annotation = f" ({', '.join(parts)})"
        desc = f": {node.description}" if node.description else ""
        lines.append(f"{i}. [depth={node.depth}] {node.agent_name}{desc}{annotation}")
    return "\n".join(lines)
