"""Independent MG region choices matching GestaltX's documented behavior.

These do not edit eligibilityd, enable EU sideloading, or patch CacheData.
Key mappings/precedence: huamidev/GestaltX 671f099, GestaltDocument.applyRegion.
"""
from .tweak_classes import Tweak
from src.exceptions.nugget_exception import NuggetException


class MobileGestaltRegionTweak(Tweak):
    REGION_CODE = "h63QSdBCiT/z0WU6rdQv6Q"
    SALES_KEYS = ("zHeENZu+wbg7PUprwNwBWg", "yK+xavymRGZ3xWc1tb8XDg")
    REGIONS = (("Keep current", ""), ("United States", "LL"), ("China (Mainland)", "CH"),
               ("Hong Kong", "ZA"), ("Taiwan", "TA"), ("Japan", "J"),
               ("United Kingdom", "B"), ("Canada", "C"))

    def __init__(self):
        super().__init__(key=None)
        self.region_code = ""
        self.sales_region = ""

    def set_regions(self, region_code: str = "", sales_region: str = ""):
        codes = {code for _, code in self.REGIONS}
        if region_code not in codes or sales_region not in codes:
            raise NuggetException("Unknown MobileGestalt region preset.")
        self.region_code, self.sales_region = region_code, sales_region
        self.set_enabled(bool(region_code or sales_region))

    def apply_tweak(self, plist: dict):
        if not self.enabled:
            return plist
        extra = plist["CacheExtra"]
        # Explicit code overrides the sales-region default. Code-only changes
        # deliberately leave BOTH sales suffix keys untouched (e.g. CH/A).
        extra[self.REGION_CODE] = self.region_code or self.sales_region
        if self.sales_region:
            present = [key for key in self.SALES_KEYS if key in extra]
            for key in present or [self.SALES_KEYS[0]]:
                extra[key] = self.sales_region + "/A"
        return plist
