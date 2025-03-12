-- Author: @marklit

INSTALL spatial;
INSTALL lindel;
LOAD spatial;
LOAD lindel;

CREATE OR REPLACE TABLE inventory AS
    FROM READ_PARQUET('data/all_items.parquet'); -- local filepath

SELECT COUNT(*) from inventory; -- 7,095,985

COPY (
    FROM     inventory
    WHERE    bbox.ymin IS NOT NULL -- Lindel extension crashes without this
    AND      bbox.xmin IS NOT NULL
    ORDER BY HILBERT_ENCODE([bbox.ymin,
                            bbox.xmin]::double[2])
) TO 'sorted.level22.pq' (
    FORMAT            'PARQUET',
    CODEC             'ZSTD',
    COMPRESSION_LEVEL 22,
    ROW_GROUP_SIZE    15000);

select COUNT(*) from READ_PARQUET('sorted.level22.pq'); -- 7,095,985 records & 284 MB