from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=120)
    end = serializers.CharField(max_length=120)
