"""Sample the public Da Nang raster tiles at the established monitoring points."""

from datetime import datetime, timezone
from hashlib import sha256
import math

from .flood_sources import POINTS, number

DEM_TILE = "Copernicus_DSM_COG_10_N16_00_E108_00_DEM"
DEM = f"https://copernicus-dem-30m.s3.amazonaws.com/{DEM_TILE}/{DEM_TILE}.tif"
WORLDCOVER = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
              "ESA_WorldCover_10m_2021_v200_N15E108_Map.tif")
LAND_CLASSES = {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}


def horn_slope(values, spacing_x, spacing_y):
    west = values[0, 0] + 2 * values[1, 0] + values[2, 0]
    east = values[0, 2] + 2 * values[1, 2] + values[2, 2]
    north = values[0, 0] + 2 * values[0, 1] + values[0, 2]
    south = values[2, 0] + 2 * values[2, 1] + values[2, 2]
    return math.degrees(math.atan(math.hypot((east - west) / (8 * spacing_x),
                                            (north - south) / (8 * spacing_y))))


def sample_raster(path, dataset, points=POINTS):
    import rasterio
    from rasterio.windows import Window

    with rasterio.open(path) as raster:
        transform = raster.transform
        if raster.crs is None or raster.crs.to_epsg() != 4326 or transform.b or transform.d:
            raise ValueError("Expected a north-up EPSG:4326 provider raster")
        expected = 1 / (3600 if dataset == "copernicus-dem" else 12000)
        if not (math.isclose(transform.a, expected, rel_tol=0.01)
                and math.isclose(-transform.e, expected, rel_tol=0.01)):
            raise ValueError("Unexpected provider raster cell spacing")
        for point in points:
            row, col = raster.index(point.longitude, point.latitude)
            if not (0 <= row < raster.height and 0 <= col < raster.width):
                raise ValueError(f"Provider tile does not cover {point.code}")
            radius = 1 if dataset == "copernicus-dem" else 5
            width = 2 * radius + 1
            values = raster.read(1, window=Window(col - radius, row - radius, width, width),
                                 boundless=True, masked=True)
            center = values[radius, radius]
            if values.mask[radius, radius]:
                continue
            base = dict(location=point.code, latitude=point.latitude, longitude=point.longitude)
            if dataset == "copernicus-dem":
                yield base | dict(feature="elevation", value=number(float(center), -12000, 9000), unit="m")
                if not values.mask.any() and all(math.isfinite(x) for x in values.flat):
                    lat = math.radians(point.latitude)
                    dx = math.radians(transform.a) * 6371008.8 * math.cos(lat)
                    dy = math.radians(-transform.e) * 6371008.8
                    yield base | dict(feature="surface_slope", value=horn_slope(values.astype(float), dx, dy),
                                      unit="degree")
            else:
                if int(center) not in LAND_CLASSES:
                    continue
                yield base | dict(feature="worldcover_class", value=int(center), unit="class_code")
                if not values.mask.any() and all(int(value) in LAND_CLASSES for value in values.flat):
                    yield base | dict(feature="worldcover_built_up_fraction_11x11",
                                      value=float((values == 50).mean()), unit="fraction")


def raster_batch(dataset, path):
    if dataset == "copernicus-dem":
        code, provider, title, url, licence, attribution, metadata = (
            "copernicus-dem-glo30", "Copernicus", "Copernicus DEM GLO-30", DEM,
            "Copernicus DEM GLO-30 Full, Free & Open",
            "Copernicus DEM © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018",
            {"resolution_m": 30, "method": "point cell and 3x3 Horn slope", "vertical_datum": "EGM2008"},
        )
    else:
        code, provider, title, url, licence, attribution, metadata = (
            "esa-worldcover-2021-v200", "ESA WorldCover", "ESA WorldCover 2021 v200", WORLDCOVER,
            "CC BY 4.0", "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021)",
            {"resolution_m": 10, "year": 2021, "method": "point class and 11x11 built-up cell fraction"},
        )
    with path.open("rb") as stream:
        checksum = sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return dict(code=code, provider=provider, dataset=title, source_ref=url, sha256=checksum.hexdigest(),
                retrieved_at=datetime.now(timezone.utc), licence=licence, attribution=attribution,
                metadata=metadata | {"expected_samples": len(POINTS) * 2, "method_version": 1,
                                     "asset_validation": "local tile supplied by operator"},
                kind="terrain", rows=list(sample_raster(path, dataset)))
