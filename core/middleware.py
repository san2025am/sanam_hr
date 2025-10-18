from .utils.current import set_current_user, clear_current_user
class CurrentUserMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        try:
            if hasattr(request, "user"): set_current_user(request.user)
            response = self.get_response(request)
        finally:
            clear_current_user()
        return response
