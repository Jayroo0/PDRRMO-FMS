from django.urls import path
from . import views

app_name = 'dashboard_portal'

urlpatterns = [
    # Public entry points.
    path('', views.landing_page, name='landing'),
    path('request-vehicle/', views.vehicle_request, name='vehicle_request'),
    path('track-driver/<uuid:token>/', views.driver_location_sharing, name='driver_location_sharing'),
    path('driver/dashboard/', views.driver_dashboard, name='driver_dashboard'),
    path('driver/active-trip/', views.driver_active_trip, name='driver_active_trip'),
    path('login/', views.login_view, name='login'),

    # 📑 Public/internal home dashboard.
    path('home/', views.homepage, name='homepage'),
    path('api/public-trip-locations/', views.public_trip_locations, name='public_trip_locations'),

    # 🔀 Central Gateway Router
    path('portal/dispatch/', views.dashboard_router, name='dashboard_portal'),

    # 🔒 Authentication Utilities
    path('logout/', views.custom_user_logout, name='custom_logout'),
    path('logout/', views.custom_user_logout, name='custom_user_logout'),

    # 📊 Portal Operational Interfaces
    path('repair/', views.repairman_dashboard, name='repairman_dashboard'),
    path('maritime/dispatch/', views.seacraft_dispatch_view, name='seacraft_dispatch'),
    path('maritime/', views.seacraft_dashboard, name='seacraft_dashboard'),
    path('logistics/', views.logistics_dashboard, name='logistics_dashboard'),
    path('logistics/reports/land-dispatch.csv', views.land_dispatch_report, name='land_dispatch_report'),
]