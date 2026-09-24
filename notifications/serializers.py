from rest_framework import serializers
from .models import Notification

class NotificationSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    gym_name = serializers.CharField(source='gym.name', read_only=True)

    class Meta:
        model = Notification
        fields = ['id', 'actor', 'actor_name', 'gym', 'gym_name', 'verb', 'message', 'target_type', 'target_id', 'is_read', 'created_at']

    def get_actor_name(self, obj):
        if obj.actor:
            return obj.actor.get_full_name() or obj.actor.email
        return 'System'
