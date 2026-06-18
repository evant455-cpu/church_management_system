from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.contrib.auth.forms import UserCreationForm as BaseUserCreationForm

from .models import User


class UserCreationForm(BaseUserCreationForm):
    """Admin "add user" form -- email instead of username, plus the required tenant/person FKs."""

    class Meta(BaseUserCreationForm.Meta):
        model = User
        fields = ("email", "congregation", "person")


class UserChangeForm(BaseUserChangeForm):
    class Meta(BaseUserChangeForm.Meta):
        model = User
        fields = "__all__"
