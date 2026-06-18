import importlib.metadata

import numpy as np
import treedata as td

from server.common.errors import DatasetAccessError
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
