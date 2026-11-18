from dataclasses import dataclass


@dataclass(frozen=True)
class SamplingPoint:
    code: str
    name: str
    latitude: float
    longitude: float


# The source for each fixed representative point is recorded in docs/ingestion.md.
DANANG_POINTS = (
    SamplingPoint("hai-chau", "Hải Châu", 16.076345, 108.221783),
    SamplingPoint("thanh-khe", "Thanh Khê", 16.071259, 108.191634),
    SamplingPoint("lien-chieu", "Liên Chiểu", 16.07272, 108.15815),
    SamplingPoint("cam-le", "Cẩm Lệ", 16.0153, 108.2013),
    SamplingPoint("ngu-hanh-son", "Ngũ Hành Sơn", 16.008333, 108.2525),
)
