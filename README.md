# Satellogic EarthView STAC GeoParquet

This repo documents a process for converting the static [SpatioTemporal Asset Catalog (STAC)](https://stacspec.org/en) describing [Satellogic EarthView](https://satellogic-earthview.s3.us-west-2.amazonaws.com/index.html) dataset into a GeoParquet file. This dataset contains ~7.1 million high-resolution (~1m) satellite images released under CC-BY 4.0 license and made available via AWS's Open Data Registry.

_Static_ [SpatioTemporal Asset Catalogs (STAC)](https://radiantearth.github.io/stac-browser/#/external/satellogic-earthview.s3.us-west-2.amazonaws.com/stac/catalog.json?.language=en) are made up of a large number of JSON files containing GeoJSON Features annotated with metadata (STAC Items) that describe the images. Due to this storage structure, static STACs [are difficult to query](https://cloudnativegeo.org/blog/2024/08/introduction-to-stac-geoparquet/) and, therefore, explore. For example, searching for all of the images that intersect an area of interest would require reading every single STAC Item--potentially gigabytes of data. Aggregating metadata (e.g., cloud cover, temporal coverage) would be similarly laborious. These use cases can also be onerous with a dynamic STAC API because they would require paging over results which can be slow and susceptible to request failure, rate-limiting, etc.

Enter **[STAC GeoParquet](https://stac-utils.github.io/stac-geoparquet/latest/)**! Packaging STAC Items in GeoParquet format [makes these tasks trivial](https://stac-utils.github.io/stac-geoparquet/latest/spec/stac-geoparquet-spec/#use-cases) by providing a cloud-friendly, queryable representation of a STAC Collection.

## tldr;

* Parquet is a columnar storage file format optimized for efficient storage and retrieval (querying) of large datasets
* [GeoParquet](https://geoparquet.org/) adds interoperable geospatial types
* STAC GeoParquet specifies how to map STAC Items into GeoParquet format
* **STAC GeoParquet enables efficient bulk-access to large STAC Collections for analytic workflows**

## Converting the Satellogic EarthView STAC to STAC GeoParquet

The EarthView STAC is comprised of 7.1 million JSON files in AWS S3 object storage ([catalog root](https://satellogic-earthview.s3.us-west-2.amazonaws.com/stac/2022/catalog.json)). I converted these files to STAC GeoParquet in two steps:

1. Scrape all STAC Items in the Catalog to `ndjson` file(s) ([newline delimited JSON](https://github.com/ndjson/ndjson-spec))
2. Use the [`stac-geoparquet` Python library](https://stac-utils.github.io/stac-geoparquet/latest/) to create a STAC GeoParquet file containing all of the Items
3. Apply spatial sorting to enable efficient spatial queries and compression to reduce overall file size

I performed the conversion in AWS EC2 on a [`t3.large` instance](https://aws.amazon.com/ec2/instance-types/t3/#:~:text=t3.large,%240.036) in the `us-west-2` region where the Satellogic data are stored to minimize network latency. I found that applying the spatial sorting and compression required significantly more memory so I had to use a larger instance for this step ([`r7i.8xlarge`](https://aws.amazon.com/ec2/instance-types/r7i/#:~:text=Up%20to%2010-,r7i.8xlarge,-32)).

### Setup

* Clone this repo:

    ```sh
    $ git clone git@github.com:bmcandr/satellogic-earthview-stac-parquet.git
    $ cd satellogic-earthview-stac-parquet
    ```

* Create a Python virtual environment and install dependencies:

    ```sh
    $ mkdir satellogic-stac-geoparquet
    $ satellogic-stac-geoparquet
    $ pyenv local 3.11
    $ python -m venv venv
    $ source venv/bin/activate
    $ pip install -r requirements.txt
    ```

* Install `duckdb` per [instructions](https://duckdb.org/docs/installation/?version=stable&environment=cli&platform=macos&download_method=direct) (only required to apply spatial sort and compression)
    * Install required extensions:

        ```sh
        $ duckdb
        D install spatial;
        D install lindel;
        ```

### Scraping STAC Items

The EarthView STAC is organized into nested Collections for year, month, and day:

```
.
└── 2022/
    ├── 2022-07/
    │   └── 2022-07-01/
    │       ├── 20220701_085711_SN18_36N_359407_5809328
    │       └── ...
    ├── 2022-08
    ├── 2022-09
    ├── 2022-10
    ├── 2022-11
    └── 2022-12
```

[`cli.py`](cli.py) contains some Python utilities to traverse and scrape Catalogs, audit the scraped results, and convert the results to Parquet (see `python cli.py --help` for more info).  Using these tools, I scraped the Catalogs to produce an `ndjson` for each terminal Collection by running:

```bash
$ python cli.py list-catalog-children-uris https://satellogic-earthview.s3.us-west-2.amazonaws.com/stac/2022/catalog.json \
    | xargs -n1 python cli.py list-catalog-children-uris \
    | xargs -n1 -P5 python cli.py scrape-catalog
```

_Note: the `scrape-catalog` command uses `aiohttp` to make asynchronous requests to read the Items and `aiofiles` to write the response to file. Through trial and error I found that running 5 concurrent processes via `xargs -n1 -P5` avoided intermittent request failures (rate-limiting? :shrug:)._

<img src="https://i.ytimg.com/vi/S3wsCRJVUyg/maxresdefault.jpg?sqp=-oaymwEmCIAKENAF8quKqQMa8AEB-AH-DoACuAiKAgwIABABGH8gGSgTMA8=&rs=AOn4CLCOX9gqjvonooj0wlfP3uESR-tLUQ" width=200 alt="spongebob: a few moments later"/>

After about an hour I had a pile of `ndjson` files:

```
.
└── data/
    ├── 2022-07-01.ndjson
    ├── ...
    └── 2022-12-31.ndjson
```

These files contained ~7.1 million lines and weighed in at **22GB**.

### Creating STAC GeoParquet File

At this point, combining the `ndjson`s into a GeoParquet file is very straightforward:

```sh
$ python cli.py parse-stac-ndjson-to-parquet data/*.json all-items.parquet
```

Use `duckdb` to check that the resulting file is readable and contains all the expected data:

```sh
$ duckdb
D load spatial;
D SELECT COUNT(*) items FROM all-items.parquet;

┌─────────┐
│  items  │
│  int64  │
├─────────┤
│ 7095985 │
└─────────┘

D DESCRIBE SELECT * FROM all-items.parquet;

┌─────────────────────┬────────────────────────────────────┬─────────┬─────────┬─────────┬─────────┐
│     column_name     │            column_type             │  null   │   key   │ default │  extra  │
│       varchar       │              varchar               │ varchar │ varchar │ varchar │ varchar │
├─────────────────────┼────────────────────────────────────┼─────────┼─────────┼─────────┼─────────┤
│ assets              │ STRUCT(analytic STRUCT("eo:bands…  │ YES     │ NULL    │ NULL    │ NULL    │
│ bbox                │ STRUCT(xmin DOUBLE, ymin DOUBLE,…  │ YES     │ NULL    │ NULL    │ NULL    │
│ geometry            │ GEOMETRY                           │ YES     │ NULL    │ NULL    │ NULL    │
│ id                  │ VARCHAR                            │ YES     │ NULL    │ NULL    │ NULL    │
...
```

If the `column_type` of the `geometry` column says `blob` instead of `GEOMETRY` make sure the [`spatial` extension](https://duckdb.org/docs/stable/extensions/spatial/overview) is installed and loaded.

This file occupied about 1.5GB in disk space.

#### Apply Spatial Sorting and Compression (optional/recommended)

Using `duckdb` run `sort-and-compress.sql`:

```sh
$ duckdb
D .read sort-and-compress.sql
```

_Remember, this may require a large amount of memory and temp directory space on disk._

This took about 10-20 minutes and produced a file named `sorted.level22.parquet`. The size?

**Just 275MB.**

(s/o to @marklit for the `sort-and-compress.sql` script!)

The spatially sorted, compressed STAC GeoParquet file containing the entirety of the Satellogic EarthView STAC resulting from this process is available on S3 at:

`s3://satellogic-earthview-stac-geoparquet/satellogic-earthview-stac-items.parquet`

**Check out the included [notebook](exploring-satellogic-earthview.ipynb) that demonstrates how to use `duckdb`, `h3`, `geopandas`, and `lonboard` explore and visualize this dataset.**

----

### Acknowledgements

* [Satellogic](https://satellogic.com/)
* [EarthView: A Large Scale Remote Sensing Dataset for Self-Supervision](https://arxiv.org/abs/2501.08111)

    ```bibtex
    @inproceedings{earthview2025,
        author={Velázquez, Diego and Rodríguez, Pau and Alonso, Sergio and Gonfaus, Josep M. and González, Jordi and, Richarte, Gerardo and Marín, Javier and Bengio, Yoshua and Lacoste, Alexandre},
        booktitle={2025 IEEE/CVF Winter Conference on Applications of Computer Vision Workshops (WACVW)}, 
        title={EarthView: A Large Scale Remote Sensing Dataset for Self-Supervision}, 
        year={2025},
        url={https://arxiv.org/abs/2501.08111}
    }     
    ```

* @marklit's blog post [Satellogic's Open Satellite Feed](https://tech.marksblogg.com/satellogic-open-data-feed.html)
* The STAC, GeoParquet, and Arrow communities

----

**Disclaimer:** I am not affiliated with Satellogic and all opinions are my own.
