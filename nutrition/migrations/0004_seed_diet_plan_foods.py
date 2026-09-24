from django.db import migrations

# Verbatim from the "Diet Plan" sheet of New start.xlsx (Options A and B):
# (food item, portion, kcal, protein g, carbs g, fat g). The staples cheat sheet is
# left out because it only lists protein and calories, not carbs or fat.
DIET_PLAN_FOODS = [
    ('Black Coffee + Soaked Almonds + Banana', '1 mug coffee + 6 almonds + 1 banana', 150, 3, 28, 4),
    ('Rolled Oats with Toned Milk & Cinnamon', '65g oats + 200ml toned milk', 340, 14, 54, 6),
    ('Whole Boiled Eggs + Steamed Egg Whites', '2 whole eggs + 3 egg whites', 230, 23, 2, 11),
    ('Green Tea & Roasted Chana (Phutana)', '1 cup tea + 35g roasted chana', 125, 8, 19, 2),
    ('Soya Chunks Bhurji / Chicken Curry + Dal + Rotis', '50g soya chunks (or 120g chicken) + 1 bowl dal + 2 rotis + salad', 630, 50, 82, 8),
    ('Homemade Low-Fat Curd (Dahi) + Roasted Chana', '200g dahi + 35g roasted chana', 240, 17, 27, 6),
    ('Pan-Seared Chicken Breast / Paneer + Steamed Rice + Sabzi', '150g chicken breast (or 130g paneer) + 160g rice + 1 bowl sabzi', 445, 50, 52, 6),
    ('Black Coffee + 5 Soaked Almonds', '1 mug coffee + 5 almonds', 40, 1, 1, 3),
    ('Rolled Oats with Toned Milk & Boiled Eggs', '55g oats + 180ml milk + 2 whole eggs', 450, 26, 49, 16),
    ('Fresh Ripe Banana + Green Tea', '1 medium banana (100g) + 1 cup green tea', 100, 1, 25, 0),
    ('Spiced Chicken Breast Curry / Soya + Dal + 2 Rotis + Salad', '65g chicken (or 45g soya) + 200g dal + 2 rotis + cucumber', 515, 40, 77, 6),
    ('Dry Roasted Chana + Low-Fat Dahi', '45g roasted chana + 180g homemade curd', 280, 19, 33, 6),
    ('Chicken & Egg / Soya Bhurji + Steamed Rice + Sabzi', '65g chicken + 1 egg white (or 35g soya + 50g paneer) + 200g rice + sabzi', 535, 44, 70, 10),
]


def seed(apps, schema_editor):
    Food = apps.get_model('nutrition', 'Food')
    for name, serving, kcal, protein, carbs, fat in DIET_PLAN_FOODS:
        Food.objects.get_or_create(
            owner=None,
            name=name,
            defaults={'serving_label': serving, 'calories': kcal, 'protein_g': protein, 'carbs_g': carbs, 'fat_g': fat},
        )


def unseed(apps, schema_editor):
    Food = apps.get_model('nutrition', 'Food')
    Food.objects.filter(owner=None, name__in=[f[0] for f in DIET_PLAN_FOODS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('nutrition', '0003_mealentry_servings_food_mealentry_food'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
