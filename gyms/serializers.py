from rest_framework import serializers
from .models import Gym, GymBranch, GymEquipment

class GymBranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = GymBranch
        fields = ['id', 'name', 'address', 'phone']

class GymEquipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = GymEquipment
        fields = ['id', 'name', 'category', 'quantity']

class GymSerializer(serializers.ModelSerializer):
    branches = GymBranchSerializer(many=True, read_only=True)
    equipment = GymEquipmentSerializer(many=True, read_only=True)
    members_count = serializers.SerializerMethodField()

    class Meta:
        model = Gym
        fields = [
            'id', 'name', 'slug', 'description', 'address', 'city',
            'phone', 'email', 'logo_url', 'branches', 'equipment', 'members_count', 'created_at'
        ]

    def get_members_count(self, obj):
        return obj.memberships.filter(status='ACTIVE').count()
