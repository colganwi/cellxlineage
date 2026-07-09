from __future__ import annotations

import random
import weakref

import networkx as nx

# Tree helpers used by the trees-only ancestral-linkage compute. (The pycea
# utilities that took a TreeData — get_trees, get_*_to_*_map, _check_tree_overlap,
# the get_keyed_* accessors — were dropped along with TreeData; the caller resolves
# and subsets trees itself.)

# Per-tree caches of derived, structure-only quantities (leaf list in postorder,
# and a materialized topological order). Trees are treated as read-only during
# analysis, so these are safe to reuse across the many passes a single linkage
# computation makes. WeakKeyDictionary lets the entries drop when the tree is GC'd
# (e.g. the temporary induced subtrees built for a subset). NOTE: if a tree's
# *structure* is mutated in place these caches must be cleared (see clear_tree_caches).
_LEAVES_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_TOPO_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def clear_tree_caches(tree: nx.DiGraph | None = None) -> None:
    """Invalidate the structure-only caches for one tree, or all trees."""
    if tree is None:
        _LEAVES_CACHE.clear()
        _TOPO_CACHE.clear()
    else:
        _LEAVES_CACHE.pop(tree, None)
        _TOPO_CACHE.pop(tree, None)


def get_topological_order(tree: nx.DiGraph) -> list:
    """Materialized topological order of a tree (cached per tree)."""
    order = _TOPO_CACHE.get(tree)
    if order is None:
        order = list(nx.topological_sort(tree))
        _TOPO_CACHE[tree] = order
    return order


def get_root(tree: nx.DiGraph):
    """Finds the root of a tree"""
    if not tree.nodes():
        return None  # Handle empty graph case.
    node = next(iter(tree.nodes))
    while True:
        parent = list(tree.predecessors(node))
        if not parent:
            return node  # No predecessors, this is the root
        node = parent[0]


def get_leaves(tree: nx.DiGraph):
    """Finds the leaves of a tree (cached per tree; trees are read-only here)."""
    leaves = _LEAVES_CACHE.get(tree)
    if leaves is None:
        leaves = [node for node in nx.dfs_postorder_nodes(tree, get_root(tree)) if tree.out_degree(node) == 0]
        _LEAVES_CACHE[tree] = leaves
    return leaves


def check_tree_has_key(tree: nx.DiGraph, key: str):
    """Checks that tree nodes have a given key."""
    # sample 10 nodes to check if the key is present
    sampled_nodes = random.sample(list(tree.nodes), min(10, len(tree.nodes)))
    for node in sampled_nodes:
        if key not in tree.nodes[node]:
            message = f"One or more nodes do not have {key} attribute."
            if key == "depth":
                message += " You can run `pycea.pp.add_depth` to add depth attribute."
            raise ValueError(message)
