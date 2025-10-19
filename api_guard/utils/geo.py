"""
Geospatial helpers (lat/lng parsing, distance calculations).

Auto-added: module-level documentation and gentle guidance.
This block is safe to remove if you prefer.
"""
import math
from typing import List, Tuple, Optional
import re

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """المسافة بالمتر بين نقطتين (WGS84)."""
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    return 2 * R * math.asin(math.sqrt(a))

def point_in_polygon(point: Tuple[float, float], polygon: List[Tuple[float, float]]) -> bool:
    """
    فحص احتواء نقطة داخل مضلّع بسيط (Ray Casting).
    point: (lat, lng)
    polygon: [(lat1,lng1), (lat2,lng2), ...] (أقله 3 نقاط)
    """
    if not polygon or len(polygon) < 3:
        return False
    x, y = point[0], point[1]
    inside = False
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        # تحقق من تقاطع الحافة مع الشعاع
        cond = ((y1 > y) != (y2 > y))
        if cond:
            x_intersect = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
            if x_intersect > x:
                inside = not inside
    return inside


def parse_latlng_any(text: str) -> Optional[Tuple[float, float]]:
    """
    يحاول استخراج (lat, lng) من نص حر أو روابط خرائط شائعة.
    يدعم صيغًا مثل:
      - "24.7136, 46.6753"
      - "https://maps.google.com/?q=24.7136,46.6753"
      - "https://www.google.com/maps/@24.7136,46.6753,16z"
      - "...ll=24.7136,46.6753" أو "...center=24.7136,46.6753"
      - Apple Maps: "https://maps.apple.com/?ll=24.7136,46.6753"
    يعيد None إذا تعذر الاستخراج أو كانت القيم خارج النطاق.
    """
    if not text:
        return None
    s = str(text).strip()

    def _valid(lat: float, lng: float) -> bool:
        return -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0

    # 1) معلمات الاستعلام: ll= أو q= أو center=
    for key in ("ll", "q", "center"):
        m = re.search(rf"[?&]{key}=([-+]?\d{{1,2}}(?:\.\d+)?),\s*([-+]?\d{{1,3}}(?:\.\d+)?)", s)
        if m:
            lat = float(m.group(1)); lng = float(m.group(2))
            return (lat, lng) if _valid(lat, lng) else None

    # 2) نمط @lat,lng في روابط Google Maps
    m = re.search(r"@([-+]?\d{1,2}(?:\.\d+)?),\s*([-+]?\d{1,3}(?:\.\d+)?)", s)
    if m:
        lat = float(m.group(1)); lng = float(m.group(2))
        return (lat, lng) if _valid(lat, lng) else None

    # 3) أي زوج lat,lng ظاهر في النص
    m = re.search(r"([-+]?\d{1,2}(?:\.\d+)?),\s*([-+]?\d{1,3}(?:\.\d+)?)", s)
    if m:
        lat = float(m.group(1)); lng = float(m.group(2))
        return (lat, lng) if _valid(lat, lng) else None

    return None
