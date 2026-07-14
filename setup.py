from setuptools import setup, find_packages

with open("README.md", "rb") as fh:
    long_description = fh.read().decode()

with open("server/requirements.txt") as fh:
    requirements = fh.read().splitlines()

with open("server/requirements-prepare.txt") as fh:
    requirements_prepare = fh.read().splitlines()

with open("server/requirements-annotate.txt") as fh:
    requirements_annotate = fh.read().splitlines()

setup(
    name="cellxlineage",
    version="0.3.0",
    packages=find_packages(),
    url="https://github.com/colganwi/cellxlineage",
    license="MIT",
    author="William Colgan",
    author_email="wcolgan@wi.mit.edu",
    description="Web application for exploration of single-cell datasets with lineage tree visualization",
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=requirements,
    python_requires=">=3.10",
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        "Framework :: Flask",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: POSIX",
        "Operating System :: Unix",
        "Operating System :: MacOS :: MacOS X",
        "Programming Language :: JavaScript",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
    ],
    entry_points={"console_scripts": ["cellxlineage = server.cli.cli:cli"]},
    extras_require=dict(prepare=requirements_prepare, annotate=requirements_annotate),
)
