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


def board_payload_bytes(board):
    """Upper-size fields of the tracker's stack-free chess.Board instances."""
    size = 0
    scalar = getsizeof((1 << 64) - 1)
    for name, value in board.__dict__.items():
        if name in ("move_stack", "_stack"):
            size += getsizeof([])
        elif isinstance(value, list):
            size += getsizeof(value) + sum(max(scalar, getsizeof(v)) for v in value)
        else:
            size += max(scalar, getsizeof(value))
    return size


def state_bytes(board, key):
    """Charge a stack-free board, path root, key and container growth.

    Counting scalar objects separately can overcount shared Python integers.
    No old move stack or imaginary ply-sized draw map is allocated by this DAG.
    """
    size = getsizeof(board) + getsizeof(board.__dict__) + board_payload_bytes(board)
    scalar = getsizeof((1 << 64) - 1)
    # Reserve a maximum-size 1024-bit membership mask and dictionary/tuple slots.
    path = PathNode([], 0, key[0], (1 << 1024) - 1)
    return (size + getsizeof(StateNode(board, path)) + path_bytes(path)
            + getsizeof(key) + sum(max(scalar, getsizeof(v)) for v in key) + 128)


def edge_bytes(move, old_count, new_count, old_recent, new_recent):
    """A tuple, action string, list capacity and growth of the two path integers."""
    return (getsizeof((None, None)) + getsizeof(move) + 16
            + max(0, getsizeof(new_count) - getsizeof(old_count))
            + max(0, getsizeof(new_recent) - getsizeof(old_recent)))


def budget_inventory(tracker):
    """Inventory the owned DAG without visiting every shared Python scalar.

    State boards and path nodes are counted once by identity. Known scalar
    fields are charged structurally; the slower storage_stats remains an
    independent diagnostic. Scratch sets are local, not retained by the tracker.
    """
    pending = tracker._pending
    frontiers = (tracker._nodes,) if pending is None else (
        tracker._nodes, pending.parents, pending.nodes.values())
    total = 65536  # Observation/RNG/pending metadata, not transition scratch.
    states, paths, stack = set(), set(), []
    payload = None
    for frontier in frontiers:
        total += getsizeof(frontier)
        for node in frontier:
            if node in states:
                continue
            states.add(node)
            if payload is None:
                payload = board_payload_bytes(node.board)
            total += (getsizeof(node) + getsizeof(node.board)
                      + getsizeof(node.board.__dict__) + payload)
            stack.append(node.paths)
    if pending is not None:
        total += getsizeof(pending.nodes)
        total += sum(getsizeof(key) + sum(map(getsizeof, key)) for key in pending.nodes)
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
