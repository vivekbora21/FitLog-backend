from django.contrib import admin
from .models import Food


@admin.register(Food)
class FoodAdmin(admin.ModelAdmin):
    list_display = ('name', 'serving_label', 'calories', 'protein_g', 'carbs_g', 'fat_g', 'owner')
    list_filter = (('owner', admin.EmptyFieldListFilter),)
    search_fields = ('name',)
