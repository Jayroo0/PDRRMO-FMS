# pdrrmo_fleet/pdrrmo_fleet/urls.py
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from django.http import HttpResponseRedirect


def admin_redirect_to_login(request):
    return HttpResponseRedirect('/login/')


urlpatterns = [
    path('', include(('fleet.urls', 'dashboard_portal'), namespace='dashboard_portal')),
    path('admin/', admin.site.urls),
    path('admin/fleet/vehicletype/', RedirectView.as_view(url='/admin/', permanent=False), name='admin_vehicletype_redirect'),
    path('admin/login/', admin_redirect_to_login),
    path('login/', auth_views.LoginView.as_view(), name='login'),
]