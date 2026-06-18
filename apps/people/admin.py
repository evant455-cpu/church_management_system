from django.contrib import admin

from .models import Household, Person, PersonHousehold


class PersonHouseholdInline(admin.TabularInline):
    model = PersonHousehold
    fk_name = "household"
    extra = 0
    autocomplete_fields = ["person"]


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "congregation", "membership_status", "is_archived")
    list_filter = ("congregation", "membership_status", "is_archived")
    search_fields = ("first_name", "last_name", "email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("name", "congregation", "primary_contact_person")
    list_filter = ("congregation",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [PersonHouseholdInline]


@admin.register(PersonHousehold)
class PersonHouseholdAdmin(admin.ModelAdmin):
    list_display = ("person", "household", "household_role", "is_primary")
    list_filter = ("congregation", "household_role", "is_primary")
    readonly_fields = ("created_at", "updated_at")
