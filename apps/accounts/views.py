from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """
    Placeholder post-login landing page.

    Deliberately not the Django Admin: ordinary congregation users won't
    have is_staff=True, so redirecting there after login would 403 for
    everyone except the platform operator. The real dashboard is Phase 13.
    """
    return render(request, "accounts/home.html")
