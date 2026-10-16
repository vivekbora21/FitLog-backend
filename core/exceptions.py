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
    details = None
    if isinstance(data, dict) and 'detail' in data:
        message = _flatten_error(data['detail'])
    elif isinstance(data, dict):
        message = _flatten_error(data) or 'Request validation failed.'
        details = data
    else:
        message = _flatten_error(data)

    code = getattr(exc, 'default_code', 'api_error')
    error_payload = {
        'error': {'code': str(code), 'message': message, **({'details': details} if details is not None else {})},
        'detail': message,
    }
    if isinstance(details, dict):
        for k, v in details.items():
            if k not in error_payload:
                error_payload[k] = v
    response.data = error_payload
    return response
