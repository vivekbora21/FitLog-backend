from django.db import models
from core.models import UUIDTimeStampedModel

class Gym(UUIDTimeStampedModel):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True)
    description = models.TextField(blank=True, default='')
    address = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    phone = models.CharField(max_length=30, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    logo_url = models.URLField(max_length=500, blank=True, null=True)

    def __str__(self):
        return self.name

class GymBranch(UUIDTimeStampedModel):
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=255)
    phone = models.CharField(max_length=30, blank=True, default='')

    def __str__(self):
        return f"{self.gym.name} - {self.name}"

class GymEquipment(UUIDTimeStampedModel):
    EQUIPMENT_CATEGORIES = [
        ('BARBELL', 'Barbell & Plates'),
        ('DUMBBELL', 'Dumbbells & Kettlebells'),
        ('CABLE', 'Cable Stations'),
        ('MACHINE', 'Pin/Plate-Loaded Machines'),
        ('CARDIO', 'Cardio Machines'),
        ('BODYWEIGHT', 'Calisthenics & Bodyweight'),
        ('ACCESSORY', 'Bands, Belts & Accessories'),
    ]

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name='equipment')
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=30, choices=EQUIPMENT_CATEGORIES)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.name} ({self.gym.name})"
