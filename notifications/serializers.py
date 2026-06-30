from rest_framework import serializers
from django.utils import timezone
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    time_since = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            'id',
            'title',
            'message',
            'related_id',
            'related_screen',
            'is_read',
            'read_at',
            'created_at',
            'time_since',
        )
        read_only_fields = (
            'id',
            'created_at',
            'read_at',
            'time_since',
        )

    def get_time_since(self, obj):
        return (timezone.now() - obj.created_at).total_seconds()

    def update(self, instance, validated_data):
        is_read = validated_data.get("is_read", instance.is_read)

        if is_read and not instance.is_read:
            instance.read_at = timezone.now()

        return super().update(instance, validated_data)