from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include
from interview import views as interview_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", interview_views.login_view, name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="/login/"), name="logout"),
    path("", include("interview.urls")),
]
