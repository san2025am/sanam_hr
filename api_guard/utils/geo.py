import math
from typing import List, Tuple

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
