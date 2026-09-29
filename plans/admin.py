from django.contrib import admin
from .models import Blueprint

@admin.register(Blueprint)
class BlueprintAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'mode', 'difficulty', 'default_duration_days', 'is_active']
    list_filter = ['mode', 'difficulty', 'is_active']
    search_fields = ['name', 'slug']
