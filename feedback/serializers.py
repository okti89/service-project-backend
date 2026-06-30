from rest_framework import serializers

from .models import Feedback


class AppFeedbackSerializer(serializers.ModelSerializer):
    user_full_name = serializers.CharField(source="user.get_full_name", read_only=True)

    class Meta:
        model = Feedback
        fields = [
            "id",
            "user",
            "user_full_name",
            "feedback_type",
            "subject",
            "message",
            "status",
            "tenant",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "user", "tenant"]

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["user"] = request.user
            validated_data["tenant"] = getattr(request.user, "tenant", None)
        return super().create(validated_data)


class AdminAppFeedbackSerializer(AppFeedbackSerializer):
    class Meta(AppFeedbackSerializer.Meta):
        read_only_fields = ["id", "created_at", "updated_at", "user", "tenant"]

    def update(self, instance, validated_data):
        instance.status = validated_data.get("status", instance.status)
        instance.save(update_fields=["status"])
        return instance
