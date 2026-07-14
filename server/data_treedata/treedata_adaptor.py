import importlib.metadata
import struct
import threading
from collections import OrderedDict, defaultdict, deque

import networkx as nx
import numpy as np
import pandas as pd
import treedata as td

from server.common.errors import DatasetAccessError
from server.common.fbs.matrix import encode_matrix_fbs
from server.data_anndata.anndata_adaptor import AnndataAdaptor


class TreedataAdaptor(AnndataAdaptor):
    # Full-tree (no-subset) layouts are deterministic in (trees, depth_key) and
    # the data is read-only, so their framed FBS is cached. Bounded because a
    # single full layout can be large (tens of MB at >1M cells).
    _LINEAGE_CACHE_MAX = 16

    # Pairwise ancestral linkage only includes categories with at least this many
    # cells (pycea's min_size); smaller groups give noisy linkage estimates.
    _LINKAGE_MIN_SIZE = 20

    def get_name(self):
        return "cellxlineage treedata adaptor version"

    def get_library_versions(self):
        return dict(treedata=str(importlib.metadata.version("treedata")))

    @staticmethod
    def open(data_locator, app_config, dataset_config=None):
        return TreedataAdaptor(data_locator, app_config, dataset_config)

    def _load_data(self, data_locator):
        try:
            with data_locator.local_handle() as lh:
                backed = "r" if self.server_config.adaptor__anndata_adaptor__backed else None
                self.data = td.read_h5td(lh, backed=backed)
        except ValueError:
            raise DatasetAccessError(
                "File must be in the .h5td format. "
                "You can create a TreeData object and save it with treedata.write_h5td()."
            )
        except MemoryError:
            raise DatasetAccessError("Out of memory - file is too large for available memory.")
        except Exception as e:
            import traceback

            message = f"Error loading .h5td file: {e}"
            if self.server_config.app__verbose:
                message += f"\n{traceback.format_exc()}"
            raise DatasetAccessError(message)

        # AnnData validates obsm values against obs_names. TreeData may store
        # DataFrames in obsm (e.g. leaf-character matrices) that have string
        # indices incompatible with the integer RangeIndex produced by
        # _alias_annotation_names(). Drop anything that isn't a plain ndarray;
        # cellxgene only uses ndarray embeddings anyway.
        non_array_keys = [k for k, v in self.data.obsm.items() if not isinstance(v, np.ndarray)]
        for key in non_array_keys:
            del self.data.obsm[key]

        # A single adaptor instance serves every request (the threaded server
        # shares it across users), so the lineage caches below are shared mutable
        # state. This lock guards their bookkeeping (get / move_to_end / insert /
        # evict); the heavy layout/prune compute runs outside it so users don't
        # serialize on it.
        self._lineage_lock = threading.RLock()

        # Pre-compute the topological "depth" node attribute on every tree once,
        # here at load time (single-threaded), so no request ever mutates a shared
        # tree via _ensure_depth. Matches _topology_depths / pycea.pp.add_depth:
        # a stored "depth" on every node is used as-is; otherwise it is computed
        # as hops from the root. Induced-subtree copies inherit these values (the
        # prune keeps all ancestors, so root->leaf hop counts are preserved).
        for tree in self.data.obst.values():
            self._ensure_depth(tree, "depth")

        # LRU cache of framed FBS for full-tree (no-subset) layouts.
        self._lineage_layout_cache = OrderedDict()

        # Induced-subtree cache for a subset, keyed by (tree selection, depth key,
        # keepObs signature). The prune is done once per subset and reused by every
        # ancestral-linkage call on that subset (target + pairwise). Small LRU.
        self._prune_cache = OrderedDict()
        self._PRUNE_CACHE_MAX = 4
        # obs name -> set of tree keys it is a leaf of (built once, for grouping the
        # kept leaves by tree without scanning every tree's nodes per request).
        self._obs_tree_keys_cache = None

    # ------------------------------------------------------------------ #
    # Lineage tree support                                               #
    # ------------------------------------------------------------------ #
    # The right-sidebar tree panel renders trees the way pycea.pl.branches
    # does (rectangular). Layout is computed here and shipped to the client
    # as FlatBuffers binary; colors and selection are handled client-side.

    def get_lineage_names(self):
        """Names of all observation trees (tdata.obst keys)."""
        return list(self.data.obst.keys())

    def _select_trees(self, tree_names=None):
        """Resolve tree names to a {name: nx.DiGraph} dict, dropping empty trees.

        Mirrors pycea.utils.get_trees: None/empty selects all trees.
        """
        obst = self.data.obst
        if tree_names is None or len(tree_names) == 0:
            names = list(obst.keys())
        elif isinstance(tree_names, str):
            names = [tree_names]
        else:
            names = list(tree_names)
        trees = {}
        for name in names:
            if name not in obst:
                raise KeyError(f"Unknown tree '{name}'")
            tree = obst[name]
            if tree.number_of_nodes() > 0:
                trees[name] = tree
        return trees

    def get_lineage_default_trees(self):
        """Default tree selection: all trees unless they share observations.

        Mirrors pycea's overlap rule (tdata.has_overlap): multiple trees may be
        laid out together only when no two trees share leaves. Otherwise the
        client must pick a single tree, so we default to the first.
        """
        names = self.get_lineage_names()
        if getattr(self.data, "has_overlap", False) and len(names) > 1:
            return names[:1]
        return names

    def get_lineage_depth_keys(self, tree_names=None):
        """Numeric node attributes usable as the depth axis (x-axis).

        A key is offered if it is numeric (and non-boolean) on every node of a
        sampled set across the selected trees, matching the layout requirement
        that every node carry the depth attribute. "depth" is always offered
        (and listed first): when not stored on all nodes it is computed as the
        topological depth from the root, mirroring pycea.pp.add_depth.
        """
        trees = self._select_trees(tree_names)
        common = None
        for tree in trees.values():
            nodes = list(tree.nodes)
            sample = nodes[: min(50, len(nodes))]
            for node in sample:
                numeric = {
                    k
                    for k, v in tree.nodes[node].items()
                    if not isinstance(v, (bool, np.bool_)) and isinstance(v, (int, float, np.integer, np.floating))
                }
                common = numeric if common is None else (common & numeric)
        common = common or set()
        return ["depth"] + sorted(common - {"depth"})

    def get_lineage_default_depth_key(self):
        """Default depth axis (x-axis) for node placement. Precedence:
        1. tdata.uns['default_depth'], if it names an available numeric key
           (explicit override, mirrors pycea's resolution);
        2. 'time', when available on every node (preferred over topological depth);
        3. 'depth' (topological depth from the root)."""
        keys = self.get_lineage_depth_keys()
        uns_default = self.data.uns.get("default_depth")
        if uns_default and uns_default in keys:
            return uns_default
        if "time" in keys:
            return "time"
        return "depth"

    def get_lineage_meta(self):
        """Metadata for the lineage selectors (JSON-serializable)."""
        names = self.get_lineage_names()
        return {
            "names": names,
            "depthKeys": self.get_lineage_depth_keys(),
            "defaultDepthKey": self.get_lineage_default_depth_key(),
            "defaultTrees": self.get_lineage_default_trees(),
            "hasOverlap": bool(getattr(self.data, "has_overlap", False)),
            "alignment": getattr(self.data, "alignment", "leaves"),
        }

    @staticmethod
    def _prune_tree(tree, keep_names):
        """Induced subtree: the selected leaves plus all of their ancestors.

        Mirrors treedata._utils.subset_tree for alignment='leaves' — start from
        the kept nodes and walk predecessors up to the root, then take the
        induced subgraph. Internal nodes left with a single child (unifurcations)
        are retained, matching TreeData's behavior.
        """
        keep = {n for n in tree.nodes if n in keep_names}
        queue = deque()
        for node in keep:
            queue.extend(tree.predecessors(node))
        while queue:
            node = queue.popleft()
            if node in keep:
                continue
            keep.add(node)
            queue.extend(tree.predecessors(node))
        return tree.subgraph(keep)

    @staticmethod
    def _tree_root(tree):
        node = next(iter(tree.nodes))
        while True:
            preds = list(tree.predecessors(node))
            if not preds:
                return node
            node = preds[0]

    def _full_topology(self, tree):
        """Plain-dict topology of a whole tree: (children, root). `children` maps
        each node to its list of children in the original adjacency order. Uses
        the raw adjacency dict to avoid networkx per-node method overhead."""
        succ = tree._succ  # {node: {child: attrs}} — insertion-ordered
        children = {n: list(kids) for n, kids in succ.items()}
        return children, self._tree_root(tree)

    @staticmethod
    def _induced_topology(tree, keep_set):
        """Plain-dict topology of the induced subtree of the kept leaves: the
        selected leaves plus all of their ancestors (unifurcations retained,
        matching TreeData / _prune_tree). Built directly from the raw adjacency
        dicts — no networkx subgraph view (which is very slow to traverse).

        Returns (children, root) or None when no leaf of this tree is kept.
        """
        succ = tree._succ
        pred = tree._pred
        # Leaves of this tree that survive the subset (leaf names == obs names).
        # Iterate this tree's leaves (bounded by tree size) rather than the whole
        # subset per tree, so cost doesn't scale with (subset size × #trees).
        kept = {n for n, kids in succ.items() if not kids and n in keep_set}
        if not kept:
            return None
        # Walk up to the root, adding every ancestor.
        queue = deque(kept)
        while queue:
            node = queue.popleft()
            parents = pred[node]
            if parents:
                parent = next(iter(parents))
                if parent not in kept:
                    kept.add(parent)
                    queue.append(parent)
        # Children (original order) restricted to kept nodes; root has no kept parent.
        children = {}
        root = None
        for node in kept:
            children[node] = [c for c in succ[node] if c in kept]
            parents = pred[node]
            if not parents or next(iter(parents)) not in kept:
                root = node
        return children, root

    @staticmethod
    def _postorder(children, root):
        """Iterative DFS postorder over the plain-dict `children` adjacency.
        Children are visited in their original order (so the leaf ordering, and
        thus y positions, match a recursive postorder)."""
        order = []
        stack = [(root, False)]
        while stack:
            node, processed = stack.pop()
            if processed:
                order.append(node)
                continue
            stack.append((node, True))
            kids = children[node]
            for i in range(len(kids) - 1, -1, -1):  # reversed → popped in order
                stack.append((kids[i], False))
        return order

    def _topology_depths(self, tree, nodes, children, root, depth_key):
        """Depth (x-axis) value per node. Uses the stored attribute when every
        laid-out node carries it; for 'depth' falls back to topological depth
        from the root (hops), matching pycea.pp.add_depth."""
        node_attrs = tree._node  # {node: attrs}
        missing = object()
        depths = {}
        for n in nodes:
            v = node_attrs[n].get(depth_key, missing)
            if v is missing:
                depths = None
                break
            depths[n] = v
        if depths is not None:
            return depths
        if depth_key == "depth":
            depths = {root: 0}
            queue = deque([root])
            while queue:
                u = queue.popleft()
                for c in children[u]:
                    depths[c] = depths[u] + 1
                    queue.append(c)
            return depths
        raise DatasetAccessError(f"Every node must have a numeric '{depth_key}' attribute.")

    @staticmethod
    def _obs_indexer(names, obs_index, name_to_view):
        """Resolve node/leaf names to obs row indices: full-index positions when
        no subset is active, else positions within the subset (view) space.
        Unmatched names (e.g. unselected ancestors) map to -1."""
        if name_to_view is None:
            return obs_index.get_indexer(names).astype(np.int32)
        return np.asarray([name_to_view.get(n, -1) for n in names], dtype=np.int32)

    @staticmethod
    def _frame_matrices(matrices):
        """Length-prefixed concatenation of FBS matrices: [count][len][bytes]..."""
        out = bytearray(struct.pack("<I", len(matrices)))
        for m in matrices:
            out += struct.pack("<I", len(m))
            out += m
        return bytes(out)

    def lineage_to_fbs_matrix(self, tree_names=None, depth_key="depth", keep_obs=None):
        """Serialize tree layout as a framed sequence of FBS matrices.

        Matrix 0 "branches": one row per line segment, columns x0,y0,x1,y1.
          Each tree edge is an elbow → 2 segments (vertical at parent depth,
          horizontal at child position), matching pycea's square-shoulder style.
        Matrix 1 "leaves": one row per leaf, columns y, obs (obs row index).
        Matrix 2 "nodes" (only when alignment != 'leaves'): internal nodes,
          columns x, y, obs — for coloring nodes instead of a leaf bar.

        keep_obs (optional): obs row positions (in the full obs index, in the
        client's view order) that survive an active subset. When given, each
        tree is pruned to the induced subtree of those leaves, and the emitted
        obs indices are positions within that subset (so they line up with the
        client's subset color/selection arrays). When None, the full trees are
        laid out and obs indices are positions in the full obs index.
        """
        depth_key = depth_key or "depth"
        trees = self._select_trees(tree_names)
        if len(trees) > 1 and bool(getattr(self.data, "has_overlap", False)):
            raise DatasetAccessError("Cannot lay out multiple trees when trees share observations; select one tree.")

        # Full-tree layouts (no active subset) are cached: they depend only on
        # the resolved tree selection and depth key, and the data is read-only.
        cache_key = None
        if keep_obs is None:
            cache_key = (tuple(trees.keys()), depth_key)
            with self._lineage_lock:
                cached = self._lineage_layout_cache.get(cache_key)
                if cached is not None:
                    self._lineage_layout_cache.move_to_end(cache_key)
                    return cached

        # Map node/leaf names → obs row position (leaf names match obs index).
        obs_index = self.get_obs_index()

        # Active subset: restrict each tree to the selected leaves' induced
        # subtree and emit obs indices in the subset's (view) coordinate space.
        name_to_view = None
        keep_set = None
        if keep_obs is not None:
            keep_obs = np.asarray(keep_obs, dtype=np.int64)
            keep_names = obs_index[keep_obs]
            keep_set = set(keep_names)
            name_to_view = {name: i for i, name in enumerate(keep_names)}

        # Plain-dict topology per tree (no networkx traversal on the hot path).
        # For a subset, the induced subtree; otherwise the whole tree.
        topos = {}
        for key, tree in trees.items():
            if keep_set is None:
                topos[key] = self._full_topology(tree)
            else:
                induced = self._induced_topology(tree, keep_set)
                if induced is not None:
                    topos[key] = induced

        want_nodes = getattr(self.data, "alignment", "leaves") != "leaves"

        # Pass 1: postorder each tree and count its leaves (for global y offsets).
        orders = {}
        n_total = 0
        for key, (children, root) in topos.items():
            order = self._postorder(children, root)
            orders[key] = order
            n_total += sum(1 for n in order if not children[n])

        # Pass 2: per-tree layout + vectorized branch segments. Leaf y positions
        # are the global leaf index / n_total, matching a single ordered pass.
        x0_parts, y0_parts, x1_parts, y1_parts = [], [], [], []
        leaf_names, leaf_y_parts = [], []
        node_names, node_x, node_y = [], [], []
        leaf_offset = 0
        for key, (children, root) in topos.items():
            tree = trees[key]
            order = orders[key]
            depths = self._topology_depths(tree, order, children, root, depth_key)

            x, y = {}, {}
            li = leaf_offset
            for node in order:  # postorder → children resolved before parents
                kids = children[node]
                if not kids:
                    yy = li / n_total
                    li += 1
                    leaf_names.append(node)
                    leaf_y_parts.append(yy)
                else:
                    cys = [y[c] for c in kids]
                    yy = (min(cys) + max(cys)) / 2
                    if want_nodes:
                        node_names.append(node)
                        node_x.append(float(depths[node]))
                        node_y.append(yy)
                y[node] = yy
                x[node] = float(depths[node])
            leaf_offset = li

            # Branch segments for this tree, built vectorized. Each edge → an
            # elbow: a vertical segment at the parent's depth then a horizontal
            # segment at the child's position.
            pxs, pys, cxs, cys = [], [], [], []
            for parent, kids in children.items():
                xp, yp = x[parent], y[parent]
                for child in kids:
                    pxs.append(xp)
                    pys.append(yp)
                    cxs.append(x[child])
                    cys.append(y[child])
            ne = len(pxs)
            if ne:
                pxs = np.asarray(pxs, dtype=np.float32)
                pys = np.asarray(pys, dtype=np.float32)
                cxs = np.asarray(cxs, dtype=np.float32)
                cys = np.asarray(cys, dtype=np.float32)
                x0 = np.empty(2 * ne, dtype=np.float32)
                y0 = np.empty(2 * ne, dtype=np.float32)
                x1 = np.empty(2 * ne, dtype=np.float32)
                y1 = np.empty(2 * ne, dtype=np.float32)
                x0[0::2], y0[0::2], x1[0::2], y1[0::2] = pxs, pys, pxs, cys  # vertical
                x0[1::2], y0[1::2], x1[1::2], y1[1::2] = pxs, cys, cxs, cys  # horizontal
                x0_parts.append(x0)
                y0_parts.append(y0)
                x1_parts.append(x1)
                y1_parts.append(y1)

        empty = np.empty(0, dtype=np.float32)
        branches_df = pd.DataFrame(
            {
                "x0": np.concatenate(x0_parts) if x0_parts else empty,
                "y0": np.concatenate(y0_parts) if y0_parts else empty,
                "x1": np.concatenate(x1_parts) if x1_parts else empty,
                "y1": np.concatenate(y1_parts) if y1_parts else empty,
            }
        )

        # Leaves: y position + obs row index.
        leaf_y = np.asarray(leaf_y_parts, dtype=np.float32)
        leaf_obs = self._obs_indexer(leaf_names, obs_index, name_to_view)
        leaves_df = pd.DataFrame({"y": leaf_y, "obs": leaf_obs})

        matrices = [
            encode_matrix_fbs(branches_df, col_idx=branches_df.columns, row_idx=None),
            encode_matrix_fbs(leaves_df, col_idx=leaves_df.columns, row_idx=None),
        ]

        # Internal-node coloring when observations align beyond leaves.
        if want_nodes:
            nodes_df = pd.DataFrame(
                {
                    "x": np.asarray(node_x, dtype=np.float32),
                    "y": np.asarray(node_y, dtype=np.float32),
                    "obs": self._obs_indexer(node_names, obs_index, name_to_view),
                }
            )
            matrices.append(encode_matrix_fbs(nodes_df, col_idx=nodes_df.columns, row_idx=None))

        result = self._frame_matrices(matrices)
        if cache_key is not None:
            with self._lineage_lock:
                self._lineage_layout_cache[cache_key] = result
                self._lineage_layout_cache.move_to_end(cache_key)
                while len(self._lineage_layout_cache) > self._LINEAGE_CACHE_MAX:
                    self._lineage_layout_cache.popitem(last=False)
        return result

    # ------------------------------------------------------------------ #
    # Ancestral linkage (pycea.tl.ancestral_linkage, metric="path")      #
    # ------------------------------------------------------------------ #
    # The compute is vendored under server/common/compute/ancestral_linkage
    # (a trimmed copy of pycea's compute chain — no matplotlib/scanpy) and runs
    # directly on the networkx trees plus a leaf-name → category mapping, so no
    # TreeData is constructed. Full trees are passed by reference (no copy, no
    # extra memory); a subset is the induced subtree of the selected leaves (a
    # small copy). self.data.obs is never touched; the tree graphs only gain a
    # cached "depth" attribute.

    def _ensure_depth(self, tree, depth_key):
        """Guarantee every node carries `depth_key`. For "depth" (topological
        depth from the root, in hops) it is computed and stored in place when not
        already present on every node, matching _topology_depths and
        pycea.pp.add_depth. This runs once per tree at load time (see
        _load_data), so it never mutates a shared tree during a request; the
        induced-subtree copies built for a subset inherit the stored values (the
        prune keeps every ancestor, so root->leaf hop counts are preserved).
        Other keys are assumed stored on all nodes (validated downstream by
        check_tree_has_key)."""
        if depth_key != "depth":
            return
        node_attrs = tree._node
        if node_attrs and all("depth" in attrs for attrs in node_attrs.values()):
            return
        root = self._tree_root(tree)
        if root is None:
            return
        depths = nx.single_source_shortest_path_length(tree, root)
        nx.set_node_attributes(tree, depths, "depth")

    def _obs_tree_keys(self):
        """obs name -> set of tree keys it is a leaf of (built once, cached).

        Lets a subset's kept leaves be grouped by tree in O(subset) without
        scanning every tree's nodes on each request.
        """
        with self._lineage_lock:
            if self._obs_tree_keys_cache is None:
                mapping = defaultdict(set)
                for key, tree in self.data.obst.items():
                    for node, deg in tree.out_degree():
                        if deg == 0:
                            mapping[node].add(key)
                self._obs_tree_keys_cache = mapping
            return self._obs_tree_keys_cache

    @staticmethod
    def _induced_subtree(tree, keep_leaves):
        """Induced subtree of `keep_leaves` (leaves of `tree`) + their ancestors,
        built from the leaves upward — O(subtree size), not O(tree size). Mirrors
        treedata.subset_tree for alignment="leaves"."""
        keep = set(keep_leaves)
        pred = tree._pred
        queue = deque(keep_leaves)
        while queue:
            node = queue.popleft()
            for parent in pred[node]:
                if parent not in keep:
                    keep.add(parent)
                    queue.append(parent)
        return tree.subgraph(keep).copy()

    def _linkage_trees(self, tree_names, depth_key, keep_obs=None):
        """Return {tree name: nx.DiGraph} for the linkage compute, depth-annotated.

        With `keep_obs=None` the selected trees are returned by reference (no copy).
        Otherwise (an active subset) each touched tree is reduced to the induced
        subtree of the kept leaves. The pruned trees are cached by the subset
        signature so the prune happens once per subset and is reused by every
        linkage call on it (target + pairwise), not repeated per click.
        """
        selected = self._select_trees(tree_names)
        if len(selected) > 1 and bool(getattr(self.data, "has_overlap", False)):
            raise DatasetAccessError(
                "Cannot compute linkage across multiple trees when trees share observations; select one tree."
            )
        if keep_obs is None or len(keep_obs) == 0:
            trees = {}
            for name, tree in selected.items():
                self._ensure_depth(tree, depth_key)
                trees[name] = tree
            return trees

        positions = np.asarray(keep_obs, dtype=np.int64)
        cache_key = (tuple(selected.keys()), depth_key, len(positions), hash(np.sort(positions).tobytes()))
        with self._lineage_lock:
            cached = self._prune_cache.get(cache_key)
            if cached is not None:
                self._prune_cache.move_to_end(cache_key)
                return cached

        keep_names = set(self._selected_names(positions))
        obs_tree_keys = self._obs_tree_keys()
        leaves_by_tree = defaultdict(list)
        for name in keep_names:
            for key in obs_tree_keys.get(name, ()):
                if key in selected:
                    leaves_by_tree[key].append(name)

        trees = {}
        for key, leaves in leaves_by_tree.items():
            graph = self._induced_subtree(selected[key], leaves)
            self._ensure_depth(graph, depth_key)
            trees[key] = graph

        with self._lineage_lock:
            self._prune_cache[cache_key] = trees
            self._prune_cache.move_to_end(cache_key)
            while len(self._prune_cache) > self._PRUNE_CACHE_MAX:
                self._prune_cache.popitem(last=False)
        return trees

    def _selected_names(self, selected):
        """Map selected obs row positions (full obs index, as the client sends
        them) to original obs names."""
        obs_index = self.get_obs_index()
        positions = np.asarray(selected, dtype=np.int64)
        if positions.size and (positions.min() < 0 or positions.max() >= len(obs_index)):
            raise DatasetAccessError("Selected obs positions are out of range.")
        return obs_index[positions]

    def ancestral_linkage_selected(self, selected, tree_names=None, depth_key="depth", keep_obs=None):
        """Target-mode linkage: per-cell tree distance (path) to the nearest
        selected cell. Returns {"values": [...]} in full obs order (NaN -> None),
        suitable for a new continuous obs column on the client.

        `keep_obs` (when a subset is active) is the view's obs row positions; the
        trees are pruned to that subset (shared/cached with the pairwise call and
        the tree-view subset) so the compute runs only over the visible cells."""
        from server.common.compute.ancestral_linkage import linkage_selected_scores

        depth_key = depth_key or "depth"
        names = self._selected_names(selected)
        if len(names) == 0:
            raise ValueError("Select one or more cells before running selected linkage.")

        obs_index = self.get_obs_index()
        is_selected = obs_index.isin(set(names))
        name_to_cat = dict(zip(obs_index, np.where(is_selected, "selected", "other")))
        trees = self._linkage_trees(tree_names, depth_key, keep_obs=keep_obs)

        scores = linkage_selected_scores(trees, name_to_cat, "selected", depth_key, metric="path")

        # Scatter the per-leaf scores into full obs order.
        values = np.full(len(obs_index), np.nan)
        if scores:
            leaves = list(scores.keys())
            positions = obs_index.get_indexer(leaves)
            values[positions] = [scores[leaf] for leaf in leaves]

        # Negate so that closely-related cells (small normalized distance) become
        # high values — colored red (hot). The selected target cells themselves are
        # pinned to the maximum so they read as the hottest of all.
        values = -values
        finite = values[np.isfinite(values)]
        if finite.size:
            values[np.asarray(is_selected) & np.isfinite(values)] = float(np.max(finite))
        return {"values": [None if not np.isfinite(v) else float(v) for v in values]}

    def _groupby_column(self, groupby, obs_index):
        """Resolve a color-by column to a pandas Series in obs order. Looks first
        in the dataset's obs, then in the current session's user annotations
        (categories the user created in the browser live there, not in
        self.data.obs — otherwise pairwise linkage over a user-defined category
        would fail with "not an obs column")."""
        if groupby in self.data.obs.columns:
            return self.data.obs[groupby]

        annotations = getattr(self.dataset_config, "user_annotations", None)
        if annotations is not None and annotations.user_annotations_enabled():
            labels = annotations.read_labels(self)
            if labels is not None and not labels.empty and groupby in labels.columns:
                # read_labels is indexed by obs names (check_new_labels sets the
                # index to get_obs_index()); reindex to guarantee obs order.
                return labels[groupby].reindex(obs_index)

        raise ValueError(f"'{groupby}' is not an obs column or a user annotation.")

    def ancestral_linkage_pairwise(self, groupby, selected=None, tree_names=None, depth_key="depth"):
        """Pairwise-mode linkage over a categorical obs column, optionally
        restricted to the selected cells (which prunes the trees to their induced
        subtree). Returns the clustered, symmetrized normalized-enrichment matrix as
        {"labels": [...], "matrix": [[...]], "vmin": v, "vmax": v}."""
        from server.common.compute.ancestral_linkage import cluster_order, linkage_pairwise_matrix

        depth_key = depth_key or "depth"
        obs_index = self.get_obs_index()
        col = self._groupby_column(groupby, obs_index)
        if not (isinstance(col.dtype, pd.CategoricalDtype) or col.dtype.kind in ("O", "b")):
            raise ValueError(f"'{groupby}' is not a categorical column; pick a categorical color-by.")

        # col is aligned to obs order (both self.data.obs and the user-annotation
        # labels are stored one row per obs, in obs order), so a positional zip
        # with obs_index yields {leaf name: category}.
        name_to_cat = dict(zip(obs_index, col.to_numpy()))
        keep_obs = selected if (selected is not None and len(selected) > 0) else None
        trees = self._linkage_trees(tree_names, depth_key, keep_obs=keep_obs)

        matrix = linkage_pairwise_matrix(
            trees,
            name_to_cat,
            depth_key,
            metric="path",
            symmetrize="mean",
            # Only include categories with at least this many cells; smaller
            # groups give noisy linkage estimates.
            min_size=self._LINKAGE_MIN_SIZE,
        )
        if matrix is None or matrix.shape[0] < 2:
            raise ValueError(
                f"Need at least two categories with ≥{self._LINKAGE_MIN_SIZE} cells to compute pairwise linkage."
            )

        # Cluster on the raw (path = dissimilarity) matrix, THEN negate for display
        # so that closely-related categories (small distance) become high values —
        # colored red (hot). Negating after clustering keeps the ordering intact.
        order = cluster_order(matrix, method="average", negate=False)
        arr = -matrix.iloc[order, order].to_numpy(dtype=float)
        labels = [str(x) for x in matrix.index[order]]

        # Diverging scale centered at 0 from the largest abs off-diagonal value
        # (mirrors pycea.pl.ancestral_linkage's TwoSlopeNorm default).
        off = arr.copy()
        np.fill_diagonal(off, np.nan)
        finite = off[np.isfinite(off)]
        span = float(np.nanmax(np.abs(finite))) if finite.size else 1.0
        if not np.isfinite(span) or span == 0:
            span = 1.0

        return {
            "labels": labels,
            "matrix": [[None if not np.isfinite(v) else float(v) for v in row] for row in arr],
            "vmin": -span,
            "vmax": span,
        }
