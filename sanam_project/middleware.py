from django.shortcuts import redirect

class RedirectPerFunction:
    MAP = {"HR":"/admin/hr/","Finance":"/admin/finance/","Operations":"/admin/ops/","Logistics":"/admin/logistics/"}
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        if request.path.rstrip("/") == "/admin" and request.user.is_authenticated and request.user.is_staff and not request.user.is_superuser:
            for g, url in self.MAP.items():
                if request.user.groups.filter(name=g).exists():
                    return redirect(url)
        return self.get_response(request)
