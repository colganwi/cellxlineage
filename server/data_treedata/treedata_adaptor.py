import importlib.metadata
import struct
from collections import deque

import networkx as nx
import numpy as np
import pandas as pd
import treedata as td

from server.common.errors import DatasetAccessError
from server.common.fbs.matrix import encode_matrix_fbs
from server.data_anndata.anndata_adaptor import AnndataAdaptor


class TreedataAdaptor(AnndataAdaptor):
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
        """Default depth axis: 'depth' unless tdata.uns['default_depth'] overrides
        it with another available numeric key (mirrors pycea's resolution)."""
        uns_default = self.data.uns.get("default_depth")
        if uns_default and uns_default in self.get_lineage_depth_keys():
            return uns_default
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

    @staticmethod
    def _node_depths(tree, root, depth_key):
        """Per-node depth values. Uses the stored attribute when present on every
        node; for 'depth' falls back to topological depth from the root (hops),
        matching pycea.pp.add_depth."""
        attrs = nx.get_node_attributes(tree, depth_key)
        if len(attrs) == tree.number_of_nodes():
            return attrs
        if depth_key == "depth":
            return nx.single_source_shortest_path_length(tree, root)
        raise DatasetAccessError(f"Every node must have a numeric '{depth_key}' attribute.")

    def _layout_trees(self, trees, depth_key):
        """Rectangular layout, reimplemented from pycea.pl._utils.layout_trees
        (extend_branches=False, angled_branches=False) to avoid pulling in the
        matplotlib import chain on the server hot path.

        Returns (node_coords, leaves) where node_coords maps (tree, node) ->
        (x=depth, y=position) and leaves is the ordered list of (tree, leaf).
        """
        # Ordered leaves across all trees (dfs postorder within each tree).
        roots = {}
        leaves = []
        for key, tree in trees.items():
            root = self._tree_root(tree)
            roots[key] = root
            leaves.extend(
                (key, node) for node in nx.dfs_postorder_nodes(tree, root) if tree.out_degree(node) == 0
            )
        n_leaves = len(leaves)
        if n_leaves == 0:
            return {}, []
        leaf_y = {leaf: i / n_leaves for i, leaf in enumerate(leaves)}

        node_coords = {}
        for key, tree in trees.items():
            depths = self._node_depths(tree, roots[key], depth_key)
            for node in nx.dfs_postorder_nodes(tree, roots[key]):
                if tree.out_degree(node) == 0:
                    y = leaf_y[(key, node)]
                else:
                    child_ys = [node_coords[(key, c)][1] for c in tree.successors(node)]
                    y = (min(child_ys) + max(child_ys)) / 2
                node_coords[(key, node)] = (float(depths[node]), y)
        return node_coords, leaves

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

        # Map node/leaf names → obs row position (leaf names match obs index).
        obs_index = self.get_obs_index()

        # Active subset: prune trees to the selected leaves' induced subtree and
        # emit obs indices in the subset's (view) coordinate space.
        name_to_view = None
        if keep_obs is not None:
            keep_obs = np.asarray(keep_obs, dtype=np.int64)
            keep_names = obs_index[keep_obs]
            keep_set = set(keep_names)
            name_to_view = {name: i for i, name in enumerate(keep_names)}
            trees = {k: self._prune_tree(t, keep_set) for k, t in trees.items()}
            trees = {k: t for k, t in trees.items() if t.number_of_nodes() > 0}

        node_coords, leaves = self._layout_trees(trees, depth_key)

        # Branch segments.
        seg_x0, seg_y0, seg_x1, seg_y1 = [], [], [], []
        for key, tree in trees.items():
            for parent, child in tree.edges():
                px, py = node_coords[(key, parent)]
                cx, cy = node_coords[(key, child)]
                # vertical segment at parent's depth, from py to cy
                seg_x0.append(px), seg_y0.append(py), seg_x1.append(px), seg_y1.append(cy)
                # horizontal segment at child's position, from px to cx
                seg_x0.append(px), seg_y0.append(cy), seg_x1.append(cx), seg_y1.append(cy)
        branches_df = pd.DataFrame(
            {
                "x0": np.asarray(seg_x0, dtype=np.float32),
                "y0": np.asarray(seg_y0, dtype=np.float32),
                "x1": np.asarray(seg_x1, dtype=np.float32),
                "y1": np.asarray(seg_y1, dtype=np.float32),
            }
        )

        # Leaves: y position + obs row index.
        leaf_names = [node for (_key, node) in leaves]
        leaf_y = np.asarray([node_coords[leaf][1] for leaf in leaves], dtype=np.float32)
        leaf_obs = self._obs_indexer(leaf_names, obs_index, name_to_view)
        leaves_df = pd.DataFrame({"y": leaf_y, "obs": leaf_obs})

        matrices = [
            encode_matrix_fbs(branches_df, col_idx=branches_df.columns, row_idx=None),
            encode_matrix_fbs(leaves_df, col_idx=leaves_df.columns, row_idx=None),
        ]

        # Internal-node coloring when observations align beyond leaves.
        if getattr(self.data, "alignment", "leaves") != "leaves":
            node_names, nx_, ny_ = [], [], []
            for key, tree in trees.items():
                for node in tree.nodes:
                    if tree.out_degree(node) != 0:
                        x, y = node_coords[(key, node)]
                        node_names.append(node)
                        nx_.append(x)
                        ny_.append(y)
            nodes_df = pd.DataFrame(
                {
                    "x": np.asarray(nx_, dtype=np.float32),
                    "y": np.asarray(ny_, dtype=np.float32),
                    "obs": self._obs_indexer(node_names, obs_index, name_to_view),
                }
            )
            matrices.append(encode_matrix_fbs(nodes_df, col_idx=nodes_df.columns, row_idx=None))

        return self._frame_matrices(matrices)
