# pdrrmo_fleet/pdrrmo_fleet/urls.py
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from fleet import views

urlpatterns = [
    path('', include('fleet.urls')),
    path('admin/', admin.site.urls),
    # This automatically forwards root traffic directly to your fleet app's urls.py
    
    path('', views.homepage, name='homepage'),

    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('portal/dispatch/', include('fleet.urls')),
    path('portal/', include('fleet.urls', namespace='dashboard_portal')),
]
# inside the respective urls.py file
app_name = 'dashboard_portal'