"""
Shared test fixture for standing in for real Stripe SDK objects, used by
both apps.billing.tests and apps.onboarding.tests so there's exactly one
definition to keep accurate -- this used to be duplicated in both files,
which is exactly how it drifted out of sync with reality.

As of stripe-python v15, StripeObject no longer inherits from dict --
.get()/.keys()/.values()/.items() don't exist on real Stripe objects
anymore, only attribute access and bracket notation do. See
https://github.com/stripe/stripe-python/wiki/Migration-guide-for-v15.

The previous version of this fixture *did* inherit from dict, so it
silently tolerated `.get()` calls in production code that the real SDK
would have rejected with AttributeError -- which is exactly how two
separate bugs (current_period_start/end's location, and this) reached
Evan's real Stripe account before the test suite ever caught them. This
version deliberately does NOT support .get() or any other dict method,
so a test using the wrong access pattern fails the same way production
would, instead of silently passing.
"""

from __future__ import annotations


class FakeStripeObject:
    """
    Minimal stand-in for stripe-python v15's StripeObject: attribute
    access (`obj.id`) and bracket notation (`obj["id"]`) work; `.get()`
    and friends deliberately don't exist, matching the real SDK.

    Accepts either keyword arguments or a single positional dict (or
    both at once -- kwargs win on conflict), so existing call sites
    using either style keep working:
        FakeStripeObject(id="sub_123", status="trialing")
        FakeStripeObject({"id": "sub_123", "status": "trialing"})

    Dict and list values passed in are wrapped recursively, mirroring
    how the real SDK turns nested API response data into nested
    StripeObject/list instances -- so a fixture like
    FakeStripeObject(items={"data": [{"current_period_start": 123}]})
    correctly supports attribute-chasing all the way down:
    fake.items.data[0].current_period_start
    """

    def __init__(self, _data=None, **kwargs):
        data = dict(_data or {})
        data.update(kwargs)
        for key, value in data.items():
            object.__setattr__(self, key, _wrap(value))

    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def __contains__(self, key):
        return hasattr(self, key)

    def __repr__(self):
        return f"FakeStripeObject({self.__dict__!r})"


def _wrap(value):
    if isinstance(value, dict):
        return FakeStripeObject(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value
