from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import CongregationModule
from .services import (
    ModuleDependencyError,
    ModuleDisableConfirmationRequired,
    disable_module,
    enable_module,
)


@login_required
def module_list(request):
    """
    Minimal, unstyled toggle screen -- enough to exercise enable/disable/
    cascade-confirmation through real HTTP requests. Real dashboard polish
    is Phase 13. No permission gating yet (Phase 3): any logged-in user
    can reach this for now, deliberately, since there's no role system to
    check against yet -- this view manages congregation_modules itself,
    so it can't be gated by access_required(module=...) the way feature
    views will be.
    """
    congregation_modules = (
        CongregationModule.objects.filter(congregation=request.user.congregation)
        .select_related("module")
        .order_by("module__sort_order")
    )
    return render(request, "module_system/module_list.html", {"congregation_modules": congregation_modules})


@login_required
def toggle_module(request, module_key):
    cm = get_object_or_404(CongregationModule, congregation=request.user.congregation, module__key=module_key)

    if request.method != "POST":
        return redirect("module_system:module_list")

    action = request.POST.get("action")
    confirmed = request.POST.get("confirm") == "true"

    if action == "enable":
        try:
            enable_module(request.user.congregation, module_key, request.user)
        except ModuleDependencyError as exc:
            messages.error(request, str(exc))
        return redirect("module_system:module_list")

    if action == "disable":
        try:
            disable_module(request.user.congregation, module_key, request.user, confirmed=confirmed)
            return redirect("module_system:module_list")
        except ModuleDisableConfirmationRequired as exc:
            return render(
                request,
                "module_system/confirm_disable.html",
                {"cm": cm, "affected": exc.affected},
            )

    return redirect("module_system:module_list")
