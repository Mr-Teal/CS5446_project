"""Structural allocation estimates; separate retained objects from scratch work.

These are conservative Python-object charges, not allocator or process RSS
limits. Shared old path parents are already in the observation's inventory.
"""

from sys import getsizeof

from ._belief_graph import PathNode, StateNode


def path_bytes(node):
    """Size of a new path node and its edges, excluding existing parent graphs."""
    return (getsizeof(node) + getsizeof(node.incoming) + getsizeof(node.count)
            + getsizeof(node.position) + getsizeof(node.recent)
            + sum(getsizeof(edge) + getsizeof(edge[1]) for edge in node.incoming))


def state_bytes(node):
    """Charge retained packed bytes, a path root and container growth.

    The dictionary key is the same bytes object as node.packed. A decoded Board
    belongs to transition scratch, not retained state storage. Reserve a full
    1024-bit membership mask; path multiplicity growth is charged by edge_bytes.
    """
    path = PathNode([], 0, node.paths.position, (1 << 1024) - 1)
    return getsizeof(node) + getsizeof(node.packed) + path_bytes(path) + 128


def edge_bytes(move, old_count, new_count, old_recent, new_recent):
    """A tuple, action string, list capacity and growth of the two path integers."""
    return (getsizeof((None, None)) + getsizeof(move) + 16
            + max(0, getsizeof(new_count) - getsizeof(old_count))
            + max(0, getsizeof(new_recent) - getsizeof(old_recent)))


def budget_inventory(tracker):
    """Inventory the owned DAG without visiting every shared Python scalar.

    State nodes, packed payloads and path nodes are counted once by identity. Known scalar
    fields are charged structurally; the slower storage_stats remains an
    independent diagnostic. Scratch sets are local, not retained by the tracker.
    """
    pending = tracker._pending
    frontiers = (tracker._nodes,) if pending is None else (
        tracker._nodes, pending.parents, pending.nodes.values())
    total = 65536  # Observation/RNG/pending metadata, not transition scratch.
    states, paths, stack = set(), set(), []
    payloads, containers = set(), set()
    for frontier in frontiers:
        if id(frontier) not in containers:
            containers.add(id(frontier))
            total += getsizeof(frontier)
        for node in frontier:
            if node in states:
                continue
            states.add(node)
            total += getsizeof(node)
            if id(node.packed) not in payloads:
                payloads.add(id(node.packed))
                total += getsizeof(node.packed)
            stack.append(node.paths)
    if pending is not None:
        total += getsizeof(pending.nodes)
        for key in pending.nodes:
            if id(key) not in payloads:
                payloads.add(id(key))
                total += getsizeof(key)
    while stack:
        node = stack.pop()
        if node in paths:
            continue
        paths.add(node)
        total += path_bytes(node)
        stack.extend(parent for parent, _ in node.incoming)
    belief = None if tracker.last_update is None else tracker.last_update.belief
    if belief is not None:
        total += len(belief.hypotheses) * (512 + 80 * (belief.ply + 1))
    return total
