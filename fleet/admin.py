from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.template.response import TemplateResponse
from django.http import HttpResponseRedirect
from .models import Vehicle, VehicleType, Driver  # 🟢 Added Driver model here

# =========================================================================
# 1. ADMIN HEADERS PANEL STYLING TWEAKS
# =========================================================================
admin.site.site_header = "PDRRMO Fleet Control HQ Admin"
admin.site.site_title = "PDRRMO Portal"
admin.site.index_title = "Command & Control Configuration Center"


# =========================================================================
# 2. READ-ONLY ACTIONS AUDIT LOG VIEW
# =========================================================================
@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ('action_time', 'user', 'content_type', 'object_repr', 'action_flag')
    list_filter = ('action_time', 'user', 'action_flag')
    search_fields = ('object_repr', 'change_message')
    
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


# =========================================================================
# 3. VEHICLE TYPE CONFIGURATION
# =========================================================================
@admin.register(VehicleType)
class VehicleTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)


# =========================================================================
# 4. NEW: DRIVER MODEL REGISTRATION
# =========================================================================
@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'license_number', 'phone_number', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'license_number', 'phone_number')


# =========================================================================
# 5. VEHICLE CONFIGURATION WITH STYLING INJECTIONS (CLEANED)
# =========================================================================
@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = [
        'id', 
        'model_name', 
        'plate_number', 
        'vehicle_type', 
        'status', 
        'driver_phone'  # 🔍 Pulls from the custom display method below
    ]
    list_filter = ('status', 'vehicle_type')
    # 🔄 Note: we use assigned_driver__name because assigned_driver is now a model reference
    search_fields = ('model_name', 'plate_number', 'assigned_driver__name')

    def get_queryset(self, request):
        """
        Filters out archived or permanently disposed items from the active vehicle panel.
        """
        qs = super().get_queryset(request)
        return qs.exclude(status__in=['ARCHIVED', 'DISPOSED'])

    @admin.display(description="Driver Phone Number")
    def driver_phone(self, obj):
        """
        Safely reaches through the foreign key relationship to grab 
        the assigned operator's phone number from the Driver database table.
        """
        if obj.assigned_driver and obj.assigned_driver.phone_number:
            return obj.assigned_driver.phone_number
        return "-"


# =========================================================================
# 5B. PROXY SYSTEM FOR CLOSED ARCHIVES (SEPARATE VIEW PANEL)
# =========================================================================
class ArchivedVehicle(Vehicle):
    """
    A Django Proxy model shares the core vehicle table but allows a separate 
    isolated panel configuration inside the admin control dashboard.
    """
    class Meta:
        proxy = True
        verbose_name = "Archived / Disposed Asset"
        verbose_name_plural = "Archived / Disposed Assets"

@admin.register(ArchivedVehicle)
class ArchivedVehicleAdmin(admin.ModelAdmin):
    list_display = ['id', 'model_name', 'plate_number', 'vehicle_type', 'status', 'driver_phone']
    list_filter = ('status', 'vehicle_type')
    search_fields = ('model_name', 'plate_number', 'assigned_driver__name')
    actions = ['recover_disposed_vehicle']

    def get_queryset(self, request):
        """
        Restricts this panel to only display archived or permanently disposed assets.
        """
        qs = super().get_queryset(request)
        return qs.filter(status__in=['ARCHIVED', 'DISPOSED'])

    def has_add_permission(self, request): 
        return False  # Prevents direct accidental manual instantiation inside the dead archives

    @admin.display(description="Driver Phone Number")
    def driver_phone(self, obj):
        if obj.assigned_driver and obj.assigned_driver.phone_number:
            return obj.assigned_driver.phone_number
        return "-"

    @admin.action(description="🔄 Recover selected vehicle assets (Superuser Auth Required)")
    def recover_disposed_vehicle(self, request, queryset):
        """
        Intermediary action verifying superuser status and password before 
        reverting a vehicle asset back to an operational state.
        """
        if not request.user.is_superuser:
            self.message_user(request, "🛡️ Access Denied: Only superusers possess recovery access rights.", messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

        # If password form submission has been executed
        if request.POST.get('post') == 'yes':
            pwd_input = request.POST.get('superuser_password')
            
            if check_password(pwd_input, request.user.password):
                updated_count = queryset.count()
                for vehicle in queryset:
                    vehicle.status = 'OPERATIONAL'
                    if hasattr(vehicle, 'is_active'):
                        vehicle.is_active = True
                    vehicle.save()
                    
                    # Create internal administrative audit logging trail
                    LogEntry.objects.create(
                        user_id=request.user.id,
                        content_type_id=ContentType.objects.get_for_model(vehicle).id,
                        object_id=vehicle.id,
                        object_repr=str(vehicle),
                        action_flag=CHANGE,
                        change_message="Disposed vehicle asset securely unarchived and recovered."
                    )
                
                self.message_user(request, f"🔄 Successfully recovered {updated_count} vehicle records back to active inventory.", messages.SUCCESS)
                return HttpResponseRedirect(request.get_full_path())
            else:
                self.message_user(request, "❌ Authentication Failure: Incorrect superuser credentials matching. Operation dropped.", messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

        context = {
            **self.admin_site.each_context(request),
            'title': "Security Gate: Confirm Asset Recovery Authorization",
            'queryset': queryset,
            'opts': self.model._meta,
            'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
            'media': self.media,
        }
        return TemplateResponse(request, 'admin/recover_confirmation.html', context)


# =========================================================================
# 6. USER ACCOUNTS ACTIONS SYSTEM CONTROL
# =========================================================================
@admin.action(description="🔒 Deactivate selected user accounts")
def deactivate_users(modeladmin, request, queryset):
    queryset.update(is_active=False)
    modeladmin.message_user(request, "Selected accounts have been cleanly deactivated.", messages.SUCCESS)

@admin.action(description="🔓 Activate selected user accounts")
def activate_users(modeladmin, request, queryset):
    queryset.update(is_active=True)
    modeladmin.message_user(request, "Selected accounts have been reactivated.", messages.SUCCESS)

# Safely swap default User registration for our custom actionable layout
admin.site.unregister(User)
@admin.register(User)
class CustomUserAdmin(DefaultUserAdmin):
    actions = [deactivate_users, activate_users]