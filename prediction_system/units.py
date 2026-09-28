from dataclasses import dataclass


TROY_OUNCES_PER_KILOGRAM = 32.1507466


@dataclass(frozen=True)
class PriceUnitConverter:
    """Convert precious-metal prices from USD/troy oz to USD/kg for presentation."""

    troy_ounces_per_kilogram: float = TROY_OUNCES_PER_KILOGRAM

    def usd_per_troy_ounce_to_usd_per_kg(self, value: float) -> float:
        return float(value) * self.troy_ounces_per_kilogram
