from django.urls import path
from . import views

app_name = 'dashboard_portal'

urlpatterns = [
    # 🏠 Root URL loads the login screen.
    path('', views.login_view, name='login'),

    # 📑 Public/internal home dashboard.
    path('home/', views.homepage, name='homepage'),

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