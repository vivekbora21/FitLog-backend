from rest_framework.views import exception_handler as drf_exception_handler


def _flatten_error(value):
    """Reduce a DRF error structure (str, ErrorDetail, or nested list/dict
    of them) to a single human-readable string."""
    if isinstance(value, (list, tuple)):
        return _flatten_error(value[0]) if value else ''
    if isinstance(value, dict):
        return _flatten_error(next(iter(value.values()))) if value else ''
    return str(value)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return response
    data = response.data
    if isinstance(data, dict) and 'detail' in data:
        message = _flatten_error(data['detail'])
        details = None
    elif isinstance(data, dict):
        message = 'Request validation failed.'
        details = data
    else:
        message = _flatten_error(data)
        details = None
    code = getattr(exc, 'default_code', 'api_error')
    response.data = {
        'error': {'code': str(code), 'message': message, **({'details': details} if details is not None else {})},
        'detail': message,
    }
    return response
