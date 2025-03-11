import asyncio
import json
from pathlib import Path

import aiofiles
import aiohttp
import click
import pystac
import stac_geoparquet
from tqdm.asyncio import tqdm_asyncio


@click.group
def cli():
    pass


@cli.command
@click.argument("catalog_uri")
def list_catalog_children_uris(catalog_uri: str):
    """List child links of STAC Catalog."""
    catalog = pystac.Catalog.from_file(catalog_uri)
    for child in catalog.get_children():
        click.echo(child.self_href)


async def fetch_item_and_save(
    session: aiohttp.ClientSession,
    url: str,
    out_path: str | Path,
):
    """Asynchronously fetch Item and dump to ndjson file."""
    async with session.get(url) as response:
        response = await session.get(url)
        response.raise_for_status()
        data = await response.json()

    async with aiofiles.open(out_path, "a") as f:
        await f.write(json.dumps(data, separators=(",", ":")))
        await f.write("\n")


@cli.command
@click.argument("catalog_uri")
@click.option(
    "-d",
    "--directory",
    default="data",
    type=click.Path(
        path_type=Path,
        dir_okay=True,
        file_okay=False,
        writable=True,
    ),
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    default=False,
    show_default=True,
)
def scrape_catalog_to_ndjson(
    catalog_uri: str,
    directory: Path,
    quiet: bool,
):
    """Scrape a static STAC Catalog to ndjson."""
    Path(directory).mkdir(parents=True, exist_ok=True)

    async def _scrape_catalog():
        catalog = pystac.Catalog.from_file(catalog_uri)
        click.echo(f"Processing catalog {catalog.title}...")
        item_links = catalog.get_item_links()

        async with aiohttp.ClientSession() as session:
            tasks = [
                fetch_item_and_save(
                    session,
                    item_link.href,
                    Path(directory / f"{catalog.title}.json"),
                )
                for item_link in item_links
            ]
            if quiet:
                await asyncio.gather(*tasks)
            else:
                await tqdm_asyncio.gather(*tasks)

    asyncio.run(_scrape_catalog())


@cli.command
@click.argument(
    "file",
    type=click.Path(
        path_type=Path,
        file_okay=True,
        dir_okay=False,
        readable=True,
        exists=True,
    ),
)
def check_item_counts(file: Path):
    """Compare Item counts in ndjson file against count of Item links in parent
    Catalog.
    """
    with open(file) as f:
        line_count = sum(1 for _ in f)
        f.seek(0)
        item = pystac.Item.from_dict(json.loads(f.readline()))

    catalog = item.get_parent()

    if catalog is None:
        raise ValueError("Catalog not resolved")

    item_count = len(list(catalog.get_item_links()))

    click.echo(
        " | ".join(
            [
                str(file),
                catalog.get_self_href(),  # type: ignore
                click.style("OK", fg="green")
                if item_count == line_count
                else click.style("MISMATCH", fg="red"),
                str(item_count),
                str(line_count),
            ]
        )
    )


@cli.command
@click.argument(
    "input",
    type=click.Path(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        path_type=Path,
    ),
    nargs=-1,
)
@click.argument(
    "output",
    type=click.Path(
        exists=False,
        path_type=Path,
    ),
)
def parse_stac_ndjson_to_parquet(
    input: tuple[Path],
    output: Path,
):
    """Parse ndson files containing STAC Items and convert to GeoParquet."""
    if not output.suffix == ".parquet":
        output = output.with_suffix(".parquet")
        click.echo(click.style(f"WARNING: Renaming output to {output}", fg="yellow"))

    stac_geoparquet.arrow.parse_stac_ndjson_to_parquet(input, output)


if __name__ == "__main__":
    cli()
