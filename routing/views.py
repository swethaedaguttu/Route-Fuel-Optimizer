import json

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteRequestSerializer
from .services import RoutePlanningError, plan_route_with_fuel


class RootAPIView(APIView):
    def get(self, request):
        return Response(
            {
                "message": "Route Fuel Optimizer API is running.",
                "route_endpoint": "/route/",
                "method": "POST",
            },
            status=status.HTTP_200_OK,
        )


@api_view(["POST"])
def route_view(request):
    payload = request.data if isinstance(request.data, dict) else {}
    if not payload and request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {}

    if not payload:
        payload = {
            "start": request.POST.get("start") or request.query_params.get("start"),
            "end": request.POST.get("end") or request.query_params.get("end"),
        }

    serializer = RouteRequestSerializer(data=payload)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError:
        return Response(
            {
                "error": "Invalid request",
                "message": "Both 'start' and 'end' fields are required.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    start = serializer.validated_data["start"].strip()
    end = serializer.validated_data["end"].strip()

    try:
        result = plan_route_with_fuel(start=start, end=end)
    except RoutePlanningError as exc:
        if getattr(exc, "payload", None):
            return Response(exc.payload, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        return Response(
            {"detail": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(result, status=status.HTTP_200_OK)
