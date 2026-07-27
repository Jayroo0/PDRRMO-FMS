from django.urls import path, include
from . import views

app_name = 'dashboard_portal'

urlpatterns = [
    # 🏠 Now the Root URL (http://127.0.0.1:8000/) loads the login view directly
    path('', views.login_view, name='login'),
    
    # 📑 If you still want your old homepage accessible somewhere else:
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
    # ⚓ Dedicated Seacraft Dispatch Mission Control Route
    
]