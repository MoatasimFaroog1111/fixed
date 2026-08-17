from dataclasses import dataclass


@dataclass(frozen=True)
class MetalConfig:
    name: str
    security_id: str


METALS = (
    MetalConfig("Gold", "AUXLN"),
    MetalConfig("Silver", "AGXLN"),
    MetalConfig("Platinum", "PTXLN"),
    MetalConfig("Palladium", "PDXLN"),
)

HORIZONS = {
    "1h": 1,
    "2h": 2,
    "4h": 4,
    "6h": 6,
    "12h": 12,
    "18h": 18,
    "24h": 24,
    "48h": 48,
    "1w": 24 * 7,
    "1m": 24 * 30,
}
