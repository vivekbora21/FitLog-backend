from datetime import date
from rest_framework.exceptions import ValidationError


def apply_date_range(queryset, request, field):
    start = request.query_params.get('date_from')
    end = request.query_params.get('date_to')
    filters = {}
    if start:
        date.fromisoformat(start)
        filters[f'{field}__gte'] = start
    if end:
        date.fromisoformat(end)
        filters[f'{field}__lte'] = end
    return queryset.filter(**filters) if filters else queryset
