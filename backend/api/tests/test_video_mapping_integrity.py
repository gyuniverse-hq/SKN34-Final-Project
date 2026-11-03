from app.repositories.video_mapping_files import VideoMappingFiles
from app.services.video_mapping_service import default_catalog


def test_video_mappings_and_catalog_integrity():
    files = VideoMappingFiles()
    sources = files.load_sources()
    catalog = {p.id: p for p in files.catalog(default_catalog()).products}
    assert len(sources["celebrity"]) == 34
    assert sum(len(v["products"]) for v in sources["celebrity"]) == 711
    assert len(sources["style"]) == 73
    assert sum(len(v["products"]) for v in sources["style"]) == 906
    for videos in sources.values():
        for video in videos:
            for row in video["products"]:
                if row.get("mappingVerified") is True:
                    assert row.get("catalogProductId") in catalog
                    product = catalog[row["catalogProductId"]]
                    if row.get("catalogShadeId"):
                        shade = next(
                            (s for s in product.shades if s.id == row["catalogShadeId"]), None
                        )
                        assert shade is not None
                        assert shade.measure_method != "placeholder"
                        assert shade.color_source != "placeholder"
                else:
                    assert not row.get("catalogProductId") and not row.get("catalogShadeId")
