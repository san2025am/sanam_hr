# django_project/api_guard/utils/maps.py
import re
from urllib.parse import urlparse, parse_qs, unquote

class LatLngNotFound(ValueError):
    pass

def parse_google_maps_latlng(url_or_text: str) -> dict:
    s = unquote((url_or_text or "").strip())
    if not s:
        raise LatLngNotFound("نص فارغ")
    num = r"-?\d+(?:\.\d+)?"

    def _valid(lat, lng):
        try:
            lat, lng = float(lat), float(lng)
        except Exception:
            return None
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return {"lat": round(lat, 5), "lng": round(lng, 5)}
        return None

    # query params: q, query, ll, center, destination
    try:
        parsed = urlparse(s)
        qs = parse_qs(parsed.query)
        for key in ("q", "query", "ll", "center", "destination"):
            if key in qs and qs[key]:
                cand = qs[key][0]
                m = re.search(rf"({num})\s*,\s*({num})", cand)
                if m:
                    res = _valid(m.group(1), m.group(2))
                    if res: return res
    except Exception:
        pass

    # /place/lat,lng
    m = re.search(rf"/place/({num})\s*,\s*({num})", s)
    if m:
        res = _valid(m.group(1), m.group(2))
        if res: return res

    # @lat,lng,zoom
    m = re.search(rf"@\s*({num})\s*,\s*({num})\s*,", s)
    if m:
        res = _valid(m.group(1), m.group(2))
        if res: return res

    # !3dLAT!4dLNG  أو !2dLNG!3dLAT
    m = re.search(rf"!3d({num})!4d({num})", s)
    if m:
        res = _valid(m.group(1), m.group(2))
        if res: return res
    m = re.search(rf"!2d({num})!3d({num})", s)
    if m:
        res = _valid(m.group(2), m.group(1))
        if res: return res

    # fallback: أول "lat,lng" في النص
    m = re.search(rf"({num})\s*,\s*({num})", s)
    if m:
        res = _valid(m.group(1), m.group(2))
        if res: return res

    raise LatLngNotFound("لم أستطع استخراج الإحداثيات من النص/الرابط.")
