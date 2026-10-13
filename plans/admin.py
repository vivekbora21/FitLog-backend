from django.contrib import admin
from .models import Blueprint, TrainingSplit

@admin.register(Blueprint)
class BlueprintAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'mode', 'difficulty', 'default_duration_days', 'is_active']
    list_filter = ['mode', 'difficulty', 'is_active']
    search_fields = ['name', 'slug']

@admin.register(TrainingSplit)
class TrainingSplitAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'days_per_week', 'is_active', 'display_order']
    list_filter = ['is_active']
    search_fields = ['name', 'slug']
