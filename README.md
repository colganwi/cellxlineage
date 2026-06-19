<img src="./docs/cellxlineage-logo.png" width="300">

_An interactive explorer for single-cell lineage tracing._

CELLxLINEAGE is a fork of [CELLxGENE](https://cellxgene.cziscience.com/docs/01__CellxGene) extended to support [TreeData](https://github.com/YosefLab/treedata) objects and lineage tree visualization alongside the standard UMAP embedding.

<img src="./docs/images/cellxlineage-opening.png" width="500">

## Installation

You need to have Python 3.10 or newer installed on your system. If you don't have
Python installed, we recommend installing [Mambaforge](https://github.com/conda-forge/miniforge#mambaforge).

Install the latest release of `cellxlineage` from [PyPI](https://pypi.org/project/cellxlineage):

```bash
pip install cellxlineage
```

## Usage

```bash
# Launch with a TreeData file
cellxlineage launch data.h5td
```

## CELLxGENE documentation

CELLxLINEAGE inherits all standard CELLxGENE Annotate features. For documentation on exploration, filtering, differential expression, and annotations, see the [CELLxGENE Annotate documentation](https://cellxgene.cziscience.com/docs/01__CellxGene).

## Contact

For questions and bug reports please use the [issue tracker](https://github.com/colganwi/cellxlineage/issues).

## License

MIT — see [LICENSE](LICENSE). Portions copyright Chan Zuckerberg Initiative; lineage extensions copyright William Colgan.

