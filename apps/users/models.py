import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, username=None, **extra_fields):
        if not username:
            username = uuid.uuid4().hex[:16]
        user = self.model(username=username, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.model(username=username)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    # Auto-generated slug — never entered by humans.
    username = models.CharField(max_length=64, unique=True)

    display_name = models.CharField(max_length=255, blank=True, default="")
    avatar_url = models.URLField(max_length=2000, blank=True, default="")

    # Micropub config — only populated for IndieAuth users who granted publish scope.
    # All Micropub features must check has_micropub before using these.
    micropub_endpoint = models.URLField(max_length=2000, blank=True, default="")
    micropub_token = models.TextField(blank=True, default="")

    # Daily summary settings
    daily_summary_enabled = models.BooleanField(default=False)
    daily_summary_time = models.TimeField(default="08:00")

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    @property
    def has_micropub(self):
        return bool(self.micropub_endpoint and self.micropub_token)

    def __str__(self):
        return self.display_name or self.username
