from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return response
    data = response.data
    if isinstance(data, dict) and 'detail' in data:
        message = str(data['detail'])
        details = None
    elif isinstance(data, dict):
        message = 'Request validation failed.'
        details = data
    else:
        message = str(data)
        details = None
    code = getattr(exc, 'default_code', 'api_error')
    response.data = {
        'error': {'code': str(code), 'message': message, **({'details': details} if details is not None else {})},
        'detail': message,
    }
    return response
