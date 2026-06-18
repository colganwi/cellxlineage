# cellxlineage

_An interactive explorer for single-cell transcriptomics data with lineage tree visualization._

cellxlineage is a fork of [CZ CELLxGENE Annotate](https://cellxgene.cziscience.com/docs/01__CellxGene) extended to support [TreeData](https://github.com/YosefLab/treedata) objects and lineage tree visualization alongside the standard UMAP embedding.

## Installation

Requires Python 3.10+ and Node 18.17.0+. Install into a conda environment:

```bash
conda create -n cellxlineage python=3.12
conda activate cellxlineage
pip install -e ".[dev]"
pip install -e /path/to/treedata
```

Build the frontend:

```bash
cd client && npm install && npm run prod && cd ..
make copy-client-assets
```

## Usage

```bash
# Launch with a TreeData file
cellxlineage launch data.h5td

# Launch with a standard AnnData file
cellxlineage launch data.h5ad

# Common options
cellxlineage launch data.h5td --host 0.0.0.0 --port 8080 --title "My Dataset"
```

## CELLxGENE documentation

cellxlineage inherits all standard CELLxGENE Annotate features. For documentation on exploration, filtering, differential expression, and annotations, see the [CELLxGENE Annotate documentation](https://cellxgene.cziscience.com/docs/01__CellxGene).

## License

MIT — see [LICENSE](LICENSE). Portions copyright Chan Zuckerberg Initiative; lineage extensions copyright William Colgan.
