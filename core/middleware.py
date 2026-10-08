class ApiVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/api/'):
            response['X-API-Version'] = '1'
            response['Vary'] = 'X-API-Version'
        return response
