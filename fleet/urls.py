from django.urls import path
from . import views

app_name = 'dashboard_portal'

urlpatterns = [
    # 🏠 Root URL loads the login screen.
    path('', views.login_view, name='login'),

    # 📑 Public/internal home dashboard.
    path('home/', views.homepage, name='homepage'),
    path('home/deployments/', views.deployment_activity_log, name='deployment_activity_log'),
    path('logistics/reports/deployments/', views.logistics_generate_report, name='logistics_generate_report'),
    path('fleet/reports/activity/', views.logistics_generate_report, name='fleet_activity_report'),
    path('fleet/reports/incidents/', views.fleet_report_incident, name='fleet_report_incident'),
    path('fleet/reports/incidents/<int:incident_id>/edit/', views.fleet_edit_incident, name='fleet_edit_incident'),

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
]