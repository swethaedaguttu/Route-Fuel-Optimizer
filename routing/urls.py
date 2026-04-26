from django.urls import path

from .views import RootAPIView, route_view

urlpatterns = [
    path("", RootAPIView.as_view(), name="root"),
    path("route/", route_view, name="route"),
]
