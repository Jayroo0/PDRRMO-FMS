# fleet/decorators.py
from django.contrib.auth.decorators import user_passes_test

def role_required(allowed_roles=[]):
    """
    Validates group permissions. If validation fails, automatically redirects
    the browser back to the login interface instead of raising a 403 error page.
    """
    def check_user(user):
        if user.is_authenticated:
            # Grant access to superusers, or check if group list overlaps
            if user.is_superuser or user.groups.filter(name__in=allowed_roles).exists():
                return True
        return False
        
    # 🌟 Adding login_url forces an automatic redirect instead of throwing a 403
    return user_passes_test(check_user, login_url='login')