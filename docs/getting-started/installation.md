# Installation

envlib requires **Python 3.10 or newer**.

```bash
pip install envlib
```

or with [uv](https://docs.astral.sh/uv/):

```bash
uv add envlib
```

## What comes with it

Installing envlib brings in the storage stack it is built on: [cfdb](https://github.com/mullenkamp/cfdb) (the CF-conventions array database each dataset is stored as), [ebooklet](https://github.com/mullenkamp/ebooklet)/[booklet](https://github.com/mullenkamp/booklet) (local + S3-synced key-value storage underneath cfdb and the catalogue index), plus [shapely](https://shapely.readthedocs.io/) and [pyproj](https://pyproj4.github.io/pyproj/) for geometry and reprojection.

No credentials or configuration are needed to *read* publicly hosted datasets; producers need S3-compatible object storage (any provider) to host their data.
